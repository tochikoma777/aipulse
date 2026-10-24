"""周度趋势长文生成（M5 S2）。

设计判断：趋势由代码算（`analysis/cross_period.py`），模型只负责解释与判断。
本模块做三件事：

1. **分段**：把 TrendReport 拆成 7 节，每节一次 LLM 调用（300-600 字），
   避免单次输出 2000-4000 字 + 表格撞 `max_tokens`；每段上下文更聚焦、可单独校验。
2. **给证据**：每段只喂与该节相关的数字与 item_id，且紧凑（不回显原始条目）。
3. **做校验**：锚定 id 数、套话命中、措辞红线（「消失」）、推测标注、复述标题。

任何一段失败（含 `finish_reason=length` 抛出的 LLMError）只跳过该段，不拖垮整篇。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from aipulse.analysis.cross_period import (
    CrossPeriodIndex,
    StructureReport,
    collection_failures,
    compute_all,
)
from aipulse.core.errors import LLMError, LLMTruncationError
from aipulse.core.logging import get_logger
from aipulse.llm.base import ChatMessage, LLMClient
from aipulse.llm.prompt import render_prompt
from aipulse.llm.structured import generate_structured
from aipulse.schema.trend import HeadlinesPayload, Judgement, TrendReport, TrendSegment

log = get_logger(__name__)

BOILERPLATE_PHRASES: tuple[str, ...] = (
    "值得关注",
    "未来可期",
    "有望",
    "具有重要意义",
    "值得期待",
    "或将",
    "大概率",
)

_SPECULATION_SEGMENTS = frozenset({"structural_changes", "second_order_effects"})
_ITEM_ID_RE = re.compile(r"it_[0-9a-f]{6,}")

# (key, 标题, 本节任务)
SEGMENTS: tuple[tuple[str, str, str], ...] = (
    (
        "rising_topics",
        "上升主题",
        "指出本周份额或热度上升的板块与条目，说明上升的证据（份额变化、斜率、同步变化组）。"
        "同步变化组必须注明天数与「未做显著性检验」。",
    ),
    (
        "falling_topics",
        "降温主题",
        "指出份额或热度下降的板块与连续在榜后跌出 Top30 的条目。"
        "只写「跌出 Top30」，并给出跌出前的连续在榜天数与当时热度。",
    ),
    (
        "emerging_topics",
        "新进榜",
        "描述本周新进榜的内容构成。单日条目只能作为观察，不能据此断言新趋势。",
    ),
    (
        "structural_changes",
        "结构变化",
        "从份额、来源构成、持续性分布、同步变化组里提炼结构性变化。"
        "必须标注「推测」，并说明依据的是哪个数字。",
    ),
    (
        "second_order_effects",
        "二阶影响",
        "基于上面的结构变化推演二阶影响（谁受益、谁承压、下一步看什么）。"
        "必须标注「推测」，不要把它写成已发生的事实。",
    ),
    (
        "prediction_review",
        "预言复盘",
        "说明本周预言的到期与验证情况。没有已验证样本时，必须直说「尚无到期样本」，"
        "不要编造命中率。",
    ),
    (
        "watchlist",
        "下期观察",
        "给出下期值得盯的 2-4 个具体对象（带 item_id），以及什么证据会证伪当前判断。",
    ),
)


# 每节的字数上限（prompt 里给区间，校验时用硬上限）
SEGMENT_MAX_CHARS: dict[str, int] = {
    "rising_topics": 600,
    "falling_topics": 600,
    "emerging_topics": 400,
    "structural_changes": 600,
    "second_order_effects": 600,
    "prediction_review": 100,
    "watchlist": 600,
}

WORD_BUDGET: dict[str, str] = {
    "rising_topics": "300-500 字",
    "falling_topics": "300-500 字",
    "emerging_topics": "250-400 字",
    "structural_changes": "450-600 字",
    "second_order_effects": "450-550 字",
    "prediction_review": "不超过 100 字，一句话说清即可",
    "watchlist": "300-500 字",
}


@dataclass(frozen=True)
class Evidence:
    """一段的证据文本 + 其中的标题（用于检测"复述标题"）。"""

    text: str
    titles: tuple[str, ...] = ()


def window_shortfall_note(requested: int, days: Sequence[str]) -> str:
    """请求窗口比实际数据长时，给出"还差多少天"的明确说明（否则静默缩短窗口）。

    30 天窗口不是"把 7 改成 30"就完事：跨度不足时斜率更难与噪声区分，
    结论的置信度本来就该更低。说清楚缺多少天，比假装跑完了诚实。
    """
    available = len(days)
    if requested <= 0 or available >= requested:
        return ""
    missing = requested - available
    span = f"{days[0]} → {days[-1]}" if days else "无数据"
    return (
        f"请求 {requested} 天窗口，实际只有 {available} 天（{span}）；"
        f"结构判定按 {available} 天进行，还需再攒 {missing} 天日报才能覆盖完整 {requested} 天。"
        "跨度不足时「走平」与「慢趋势」更难区分，请按较低置信度阅读。"
    )


def range_shortfall_note(start: str, end: str, days: Sequence[str]) -> str:
    """日期范围版缺口说明（T9 日历月）：说清"应有几天 / 实有几天 / 缺哪几天"。

    与 `window_shortfall_note` 的区别：这里的分母是**日历天数**而不是请求的 N 天，
    因为月度间隔的分析范围就是整个自然月。
    """
    expected = calendar_days(start, end)
    present = [day for day in days if start <= day <= end]
    if expected <= 0 or len(present) >= expected:
        return ""
    missing = expected - len(present)
    span = f"{present[0]} → {present[-1]}" if present else "无数据"
    return (
        f"分析范围 {start} → {end}（应有 {expected} 天），实际只有 {len(present)} 天（{span}）；"
        f"缺 {missing} 天日报。跨度不足时「走平」与「慢趋势」更难区分，请按较低置信度阅读。"
    )


def slice_index(index: CrossPeriodIndex, window_days: int) -> CrossPeriodIndex:
    """取最近 N 天构建子索引；N 大于可用天数时返回全部（缺口由 window_shortfall_note 报出）。"""
    days = index.days[-window_days:] if window_days > 0 else index.days
    keep = set(days)
    return CrossPeriodIndex(
        days=days,
        snapshots={day: index.snapshots[day] for day in days},
        predictions=tuple(p for p in index.predictions if p.day in keep),
    )


def slice_by_range(index: CrossPeriodIndex, start: str, end: str) -> CrossPeriodIndex:
    """按**日期范围**切片（T9：日历月间隔需要它，`slice_index` 的 last-N-days 表达不了
    "分析整个 10 月"）。范围外的日期直接丢弃；范围内没有数据的日期算缺口，
    由 `window_shortfall_note` 报出，不静默缩短。
    """
    days = tuple(day for day in index.days if start <= day <= end)
    keep = set(days)
    return CrossPeriodIndex(
        days=days,
        snapshots={day: index.snapshots[day] for day in days},
        predictions=tuple(p for p in index.predictions if p.day in keep),
    )


def calendar_days(start: str, end: str) -> int:
    """闭区间 [start, end] 的日历天数（用于"应有 N 天"）。"""
    try:
        first = date.fromisoformat(start)
        last = date.fromisoformat(end)
    except ValueError:
        return 0
    return (last - first).days + 1


# ══════════════════════════════════════════════════════════════════════════
# 证据组装
# ══════════════════════════════════════════════════════════════════════════


def _ids(items: object, limit: int = 4) -> str:
    if not isinstance(items, list):
        return ""
    return ", ".join(str(it.get("item_id")) for it in items[:limit] if isinstance(it, dict))


def _heat_lines(
    reports: dict[str, StructureReport], *, positive: bool, limit: int = 4
) -> list[str]:
    report = reports.get("heat_migration")
    if report is None or not report.entries:
        return ["- 无板块份额数据"]
    want = "up" if positive else "down"
    rows = [
        e
        for e in report.entries
        if e.get("trend_usable", True) and str(e.get("direction", "")) == want
    ]
    if not rows:
        return [
            "- 无可用板块（按斜率判定的方向为空；走平或采集异常的板块已剔除，"
            "不要把首末差为正的板块写成上升）"
        ]
    out: list[str] = []
    for entry in rows[:limit]:
        ids = _ids(entry.get("t1_top_items"), 3)
        excluded = entry.get("excluded_days") or []
        note = f"；已排除 {len(excluded)} 个板块空日" if excluded else ""
        conflict = (
            "；⚠ 首末差与斜率方向不一致，必须同时给出两个数字并说明拐点"
            if entry.get("signal_conflict")
            else ""
        )
        out.append(
            f"- {entry['section']}：份额 {entry['t0_share']}→{entry['t1_share']}"
            f"（首末差 {float(entry['delta_pp']):+.2f}pp，仅作幅度参照）"
            f"；斜率 {float(entry['slope_pp_per_day']):+.2f}pp/天"
            f"（{entry['slope_days']} 天，方向以此为准）{note}{conflict}；代表 {ids}"
        )
    return out


def _comparison_line(reports: dict[str, StructureReport]) -> list[str]:
    """告诉模型：份额对比用哪个区间，以及为什么不能跨源集合变更日。"""
    report = reports.get("heat_migration")
    if report is None:
        return []
    m = report.metrics
    line = (
        f"- 对比区间 {m.get('comparison_start')}→{m.get('comparison_end')}"
        f"（{m.get('comparison_days')} 天，源集合同构；全窗口 {m.get('full_window_days')} 天）"
    )
    changes = m.get("source_change_days") or []
    if changes:
        line += f"；源集合变更日 {'/'.join(str(d) for d in changes)}，禁止跨该日比较"
    # T9（P1-4 替代方案）：短尾巴要可见——说明白"窗口多少天、本段只用多少天、
    # 剩下几天为什么没参与"，而不是让读者以为整个窗口都参与了比较。
    used = int(m.get("comparison_days") or 0)
    total = int(m.get("full_window_days") or 0)
    if total > used > 0:
        line += (
            f"；窗口 {total} 天中本段仅 {used} 天，"
            f"其余 {total - used} 天因源集合变更或首段过短未参与份额对比"
        )
    return [line]


def _taint_lines(reports: dict[str, StructureReport]) -> list[str]:
    """被采集失败污染的板块：禁止对其作结构性趋势判断。"""
    report = reports.get("heat_migration")
    if report is None:
        return []
    out: list[str] = []
    for entry in report.entries:
        if entry.get("trend_usable", True):
            continue
        out.append(
            f"- {entry['section']}：供给源 {'/'.join(entry.get('taint_sources') or [])} "
            f"在 {'/'.join(entry.get('taint_days') or [])} 整源 0 条"
            f"（份额 {entry['t0_share']}→{entry['t1_share']}，斜率 "
            f"{float(entry['slope_pp_per_day']):+.2f}pp/天 仅供参考）"
        )
    return out


def _failure_lines(index: CrossPeriodIndex) -> list[str]:
    """逐日的采集失败（failed/degraded 且 item_count=0）。"""
    rows = [
        r for r in collection_failures(index) if r["item_count"] == 0 and r["source"] != "inbox"
    ]
    return [f"- {row['day']} {row['source']}：{row['status']}，item_count=0" for row in rows] or [
        "- 窗口内无整源 0 条的采集失败"
    ]


def _group_lines(reports: dict[str, StructureReport], *, coherent_only: bool) -> list[str]:
    report = reports.get("co_movement")
    if report is None or not report.entries:
        return ["- 无可用的同步变化组"]
    out: list[str] = []
    for group in report.entries:
        if coherent_only and not group.get("is_coherent"):
            continue
        out.append(
            f"- [{group['scope']}:{group['label']}] {group['size']} 条；"
            f"mean r={group['mean_correlation']}，min r={group['min_correlation']}，"
            f"n_days={group['n_days_min']}~{group['n_days_max']}，"
            f"coherent={group['is_coherent']}，未做显著性检验；"
            f"成员 {', '.join(str(m['item_id']) for m in group['members'][:5])}"
        )
    return out or ["- 无可用的同步变化组"]


def _top_movers(index: CrossPeriodIndex, *, rising: bool, limit: int = 5) -> list[str]:
    if len(index.days) < 2:
        return ["- 窗口不足两天，无法计算变化"]
    prev, cur = index.snapshots[index.days[-2]], index.snapshots[index.days[-1]]
    rows: list[tuple[float, str, str, float, float]] = []
    for item_id in set(prev.items) & set(cur.items):
        old, new = prev.items[item_id], cur.items[item_id]
        rows.append(
            (new.hot_score - old.hot_score, item_id, new.title, old.hot_score, new.hot_score)
        )
    rows.sort(key=lambda row: row[0], reverse=rising)
    picked = [row for row in rows if (row[0] > 0) == rising][:limit]
    if not picked:
        return [f"- 相邻两日没有{'上升' if rising else '下降'}的条目"]
    return [
        f"- [{item_id}] {title[:30]}｜{old:.2f}→{new:.2f}（{delta:+.2f}）"
        for delta, item_id, title, old, new in picked
    ]


def _event_lines(
    reports: dict[str, StructureReport], kinds: tuple[str, ...], *, limit: int = 8
) -> list[str]:
    report = reports.get("emergence")
    if report is None or not report.entries:
        return ["- 无在榜事件"]
    out: list[str] = []
    for event in report.entries:
        if event["kind"] not in kinds:
            continue
        if not event.get("trend_eligible") and event["kind"] == "dropped":
            continue  # 口径异常导致的跌出，按规则不得入趋势
        caution = event.get("caution", "")
        out.append(
            f"- [{event['item_id']}] {str(event['title'])[:30]}｜{event.get('section', '')}"
            f"｜在榜 {event['days_on']} 天／最长连续 {event['longest_run']} 天"
            f"｜最后在榜 {event.get('last_seen')}｜热度 {event.get('hot_at_last_seen')}"
            + (f"｜{caution}" if caution else "")
        )
        if len(out) >= limit:
            break
    return out or ["- 无符合条件的在榜事件"]


def _persistence_lines(reports: dict[str, StructureReport]) -> list[str]:
    report = reports.get("persistence")
    if report is None:
        return ["- 无持续性数据"]
    out = [f"- {entry['bucket']} 天：{entry['count']} 条" for entry in report.entries]
    long_lived = report.metrics.get("max_longest_run")
    out.append(f"- 窗口内最长连续在榜：{long_lived} 天")
    return out


def _source_lines(reports: dict[str, StructureReport]) -> list[str]:
    report = reports.get("source_share")
    if report is None or not report.entries:
        return ["- 无来源份额数据"]
    out: list[str] = []
    for entry in report.entries:
        if not entry.get("trend_usable", True):
            failed = "/".join(entry.get("collection_failure_days") or [])
            out.append(f"- {entry['source']}：不可用（{failed} 整源 0 条，采集失败）")
            continue
        out.append(
            f"- {entry['source']}：条目 {entry['t0_count']}→{entry['t1_count']}"
            f"（{float(entry['count_delta_pp']):+.2f}pp），热度份额"
            f" {entry['hot_share_t0']}→{entry['hot_share_t1']}"
        )
    return out


def _prediction_lines(reports: dict[str, StructureReport]) -> list[str]:
    report = reports.get("prediction_review")
    if report is None:
        return ["- 无预言数据"]
    m = report.metrics
    lines = [
        f"- 解析到预言 {m.get('total')} 条：已验证 {m.get('verified')}、待验证 {m.get('pending')}",
        f"- 最早到期日 {m.get('earliest_due') or '未知'}；当前报告最后一天 {m.get('latest_day')}",
    ]
    if not m.get("verified"):
        lines.append("- 结论：尚无到期样本，命中率/Brier 均不可估，不要编造")
    for entry in report.entries[:5]:
        lines.append(f"- 已验证：[{entry['statement'][:40]}] → {entry['verdict']}")
    return lines


def _watchlist_lines(reports: dict[str, StructureReport]) -> list[str]:
    lines: list[str] = []
    report = reports.get("unrealized")
    if report is not None and report.entries:
        for entry in report.entries[:4]:
            lines.append(
                f"- 上期被低估但未发生：{entry['marker'][:40]}"
                f"（{entry['outcome']}，热度 {entry['t0_hot']}→{entry['t1_hot']}）"
            )
    persistence = reports.get("persistence")
    if persistence is not None:
        for bucket in persistence.entries:
            if bucket["bucket"] != "≥5":
                continue
            for item in bucket["items"][:3]:
                lines.append(
                    f"- 连续在榜 {item['longest_run']} 天：[{item['item_id']}] "
                    f"{str(item['title'])[:30]}"
                )
    return lines or ["- 无明确的观察对象"]


def _titles_in(text: str, limit: int = 40) -> tuple[str, ...]:
    """从证据行里粗提标题（`- [id] 标题｜...` 这种格式）。"""
    out: list[str] = []
    for line in text.splitlines():
        match = re.search(r"\[it_[0-9a-f]+\]\s*([^｜|]{4,40})", line)
        if match:
            title = match.group(1).strip()
            if len(title) >= 6:
                out.append(title)
        if len(out) >= limit:
            break
    return tuple(dict.fromkeys(out))


def build_evidence(
    index: CrossPeriodIndex, reports: dict[str, StructureReport], key: str
) -> Evidence:
    """按节组装证据。每块都带 item_id 与数字，且保持紧凑。"""
    blocks: list[str] = []
    taint = _taint_lines(reports)
    failures = _failure_lines(index)

    def _append_taint() -> None:
        if taint:
            blocks.append("### 采集异常：禁止对这些板块作趋势判断\n" + "\n".join(taint))

    def _append_failures() -> None:
        blocks.append("### 逐日采集失败（供归因，不得当作趋势）\n" + "\n".join(failures))

    if key == "rising_topics":
        blocks.append("### 对比区间（源集合同构）\n" + "\n".join(_comparison_line(reports)))
        blocks.append("### 板块份额（上升）\n" + "\n".join(_heat_lines(reports, positive=True)))
        blocks.append(
            "### 同步变化组（未做显著性检验）\n"
            + "\n".join(_group_lines(reports, coherent_only=False))
        )
        blocks.append("### 相邻两日热度上升\n" + "\n".join(_top_movers(index, rising=True)))
        _append_taint()
        _append_failures()
    elif key == "falling_topics":
        blocks.append("### 对比区间（源集合同构）\n" + "\n".join(_comparison_line(reports)))
        blocks.append("### 板块份额（下降）\n" + "\n".join(_heat_lines(reports, positive=False)))
        blocks.append("### 连续在榜后跌出 Top30\n" + "\n".join(_event_lines(reports, ("dropped",))))
        blocks.append("### 相邻两日热度下降\n" + "\n".join(_top_movers(index, rising=False)))
        _append_taint()
        _append_failures()
    elif key == "emerging_topics":
        blocks.append("### 对比区间（源集合同构）\n" + "\n".join(_comparison_line(reports)))
        blocks.append(
            "### 今日新进榜（单日，不构成趋势）\n" + "\n".join(_event_lines(reports, ("new",)))
        )
        blocks.append(
            "### 回到榜与反复进出\n" + "\n".join(_event_lines(reports, ("returned", "fluctuating")))
        )
    elif key in ("structural_changes", "second_order_effects"):
        blocks.append("### 对比区间（源集合同构）\n" + "\n".join(_comparison_line(reports)))
        blocks.append("### 板块份额斜率\n" + "\n".join(_heat_lines(reports, positive=True)))
        blocks.append("### 板块份额（下降侧）\n" + "\n".join(_heat_lines(reports, positive=False)))
        blocks.append("### 来源构成\n" + "\n".join(_source_lines(reports)))
        blocks.append("### 持续性分布\n" + "\n".join(_persistence_lines(reports)))
        blocks.append(
            "### 结构一致的同步变化组\n" + "\n".join(_group_lines(reports, coherent_only=True))
        )
        _append_taint()
        _append_failures()
    elif key == "prediction_review":
        blocks.append("### 预言到期与验证\n" + "\n".join(_prediction_lines(reports)))
    elif key == "watchlist":
        blocks.append("### 上期预期与长榜条目\n" + "\n".join(_watchlist_lines(reports)))
        blocks.append(
            "### 当前最高热度新进榜\n" + "\n".join(_event_lines(reports, ("new",), limit=4))
        )
    else:  # pragma: no cover - 调用方只传固定 key
        blocks.append("### 无证据")

    text = "\n\n".join(blocks)
    return Evidence(text=text, titles=_titles_in(text))


# ══════════════════════════════════════════════════════════════════════════
# 校验
# ══════════════════════════════════════════════════════════════════════════


def char_count(text: str) -> int:
    """字数口径：去掉所有空白后的字符数（中文 1 字 = 1）。"""
    return len(re.sub(r"\s+", "", text))


def boilerplate_hits(text: str) -> list[str]:
    return [phrase for phrase in BOILERPLATE_PHRASES if phrase in text]


def _has_weak_correlation(reports: dict[str, StructureReport]) -> bool:
    report = reports.get("co_movement")
    if report is None:
        return False
    return any(int(g.get("n_days_min", 0)) < 5 for g in report.entries)


_CORRELATION_WORDS = ("存在相关", "共动", "高度相关")
_NEGATIONS = ("不", "未", "无", "没有")


def _claims_correlation(body: str) -> bool:
    """是否存在**肯定**的相关性表述。

    按分句判断：只要该分句同时出现否定词（不/未/无/没有）就视为澄清句，
    例如「不补充相关性或共动判断」不算违规；「两条存在相关」才算。
    """
    for clause in re.split(r"[。；;！？\n]", body):
        if not any(word in clause for word in _CORRELATION_WORDS):
            continue
        if any(neg in clause for neg in _NEGATIONS):
            continue
        return True
    return False


def segment_violations(body: str, key: str, evidence: Evidence, *, weak_corr: bool) -> list[str]:
    """按节规则校验一段正文；生成时与事后自检（S3 L1）共用同一套判据。"""
    return violations(
        body,
        evidence,
        requires_speculation=key in _SPECULATION_SEGMENTS,
        weak_corr=weak_corr,
        max_chars=SEGMENT_MAX_CHARS.get(key),
        # 预言复盘本来就是计数类结论，没有条目级事实可引用
        require_item_id=key != "prediction_review",
    )


def weak_correlation_present(reports: dict[str, StructureReport]) -> bool:
    """是否所有共动组都 <5 天（外部需要复用同一判定时用）。"""
    return _has_weak_correlation(reports)


def violations(
    body: str,
    evidence: Evidence,
    *,
    requires_speculation: bool,
    weak_corr: bool,
    max_chars: int | None = None,
    require_item_id: bool = True,
) -> list[str]:
    out: list[str] = []
    if not body.strip():
        return ["空输出"]
    if "消失" in body or "退场" in body:
        out.append("使用了「消失/退场」措辞（只能写跌出 Top30）")
    if require_item_id and not _ITEM_ID_RE.findall(body):
        out.append("未引用任何 item_id")
    if requires_speculation and "推测" not in body:
        out.append("未标注「推测」")
    if weak_corr and _claims_correlation(body):
        out.append("对 n_days<5 的组使用了「相关/共动」表述")
    if max_chars is not None and char_count(body) > max_chars:
        out.append(f"超出本节字数上限（{char_count(body)} > {max_chars}）")
    for title in evidence.titles:
        if title in body:
            out.append(f"复述了标题：{title[:20]}")
            break
    return out


# ══════════════════════════════════════════════════════════════════════════
# S5 人类层：口径免责 + 三句话 / 判断性结论
# ══════════════════════════════════════════════════════════════════════════


def _with_shortfall(caveats: list[str], requested_days: int, sliced: CrossPeriodIndex) -> list[str]:
    note = window_shortfall_note(requested_days, sliced.days)
    return ([note] if note else []) + caveats


def _with_range_shortfall(
    caveats: list[str], window_range: tuple[str, str] | None, sliced: CrossPeriodIndex
) -> list[str]:
    """日历月间隔的缺口说明（T9）：分母是日历天数，不是请求的 N 天。"""
    if window_range is None:
        return caveats
    note = range_shortfall_note(window_range[0], window_range[1], sliced.days)
    return ([note] if note else []) + caveats


def build_caveats(index: CrossPeriodIndex, reports: dict[str, StructureReport]) -> list[str]:
    """口径与免责：全部收进机器层与 `<details>`，不占正文。"""
    lines: list[str] = []
    lines.extend(_comparison_line(reports))
    lines.extend(_taint_lines(reports))
    lines.extend(_failure_lines(index))
    co = reports.get("co_movement")
    if co is not None and co.entries:
        days = {int(e.get("n_days") or 0) for e in co.entries if isinstance(e, dict)}
        days.discard(0)
        if days:
            lines.append(f"同步变化组 n_days={min(days)}~{max(days)}，未做显著性检验，不作同向解读")
    # 上游 _taint_lines / _failure_lines 带自己的 "- " 前缀，这里统一剥掉，
    # 由渲染器决定用什么列表符号（否则会渲染成 "- - …"）
    out: list[str] = []
    for line in lines:
        text = line.strip()
        while text.startswith("- "):
            text = text[2:].strip()
        if text:
            out.append(text)
    return out


def build_headline_candidates(index: CrossPeriodIndex, reports: dict[str, StructureReport]) -> str:
    """三句话的候选池：全部 9 个结构里**已经发生的具体变化**。

    ★ 议题不能只说"份额"：S5 首跑三句话全在板块份额上，第 3 句还写成
    "上升方向为空"——那是把"没观察到"当结论，既不好读，也容易被误当成免责。
    候选池给全 9 个结构，模型只需挑三个最重要的**已发生事实**。
    """
    lines: list[str] = []
    heat = reports.get("heat_migration")
    if heat is not None:
        usable = [e for e in heat.entries if isinstance(e, dict) and e.get("trend_usable")]
        usable.sort(key=lambda e: -abs(float(e.get("delta_pp") or 0.0)))
        for entry in usable[:3]:
            lines.append(
                f"板块份额变化：{entry.get('section')} {float(entry.get('delta_pp') or 0):+.2f}pp"
            )
    co = reports.get("co_movement")
    if co is not None and co.entries:
        lines.append(f"同步变化组：{len(co.entries)} 组条目同向变动")
    emergence = reports.get("emergence")
    if emergence is not None:
        dropped = [
            e
            for e in emergence.entries
            if isinstance(e, dict) and e.get("kind") == "dropped" and e.get("trend_eligible")
        ]
        dropped.sort(key=lambda e: -int(e.get("days_on") or 0))
        for entry in dropped[:2]:
            lines.append(
                f"连续在榜 {int(entry.get('days_on') or 0)} 天后跌出 Top30：{entry.get('title')}"
            )
        fresh = int(emergence.metrics.get("new") or 0) if emergence.metrics else 0
        if fresh:
            lines.append(f"新进榜 {fresh} 条")
    persistence = reports.get("persistence")
    if persistence is not None:
        buckets = {
            str(e.get("bucket")): int(e.get("count") or 0)
            for e in persistence.entries
            if isinstance(e, dict)
        }
        if buckets:
            short = sum(v for k, v in buckets.items() if k in {"1-2", "1", "2"})
            longest = persistence.metrics.get("max_longest_run")
            lines.append(f"只在榜 1-2 天的条目 {short} 条（最长连续 {longest} 天）")
    share = reports.get("source_share")
    if share is not None:
        usable_share = [e for e in share.entries if isinstance(e, dict) and e.get("trend_usable")]
        usable_share.sort(key=lambda e: -abs(float(e.get("count_delta_pp") or 0.0)))
        for entry in usable_share[:2]:
            lines.append(
                f"来源份额变化：{entry.get('source')} "
                f"{float(entry.get('count_delta_pp') or 0):+.2f}pp"
            )
    review = reports.get("prediction_review")
    if review is not None:
        lines.append(
            f"预言：{review.metrics.get('total', 0)} 条，"
            f"到期 {review.metrics.get('verified', 0)} 条"
        )
    unusable = [
        str(e.get("section"))
        for e in (heat.entries if heat is not None else [])
        if isinstance(e, dict) and not e.get("trend_usable")
    ]
    if unusable:
        lines.append(
            f"被封锁、不可作趋势判断的板块：{'、'.join(unusable)}（只能作限制说明，不能当作三句话之一）"
        )
    return "\n".join(f"- {line}" for line in lines)


async def generate_headlines(
    index: CrossPeriodIndex,
    segments: list[TrendSegment],
    client: LLMClient,
    *,
    max_tokens: int,
    candidates: str = "",
) -> tuple[list[str], list[Judgement], int, int]:
    """第 8 次调用：把 7 节正文压成「三句话 + 各节判断性结论」。

    机器层看过程（7 节正文），人类层看结论（三句话）。
    返回 `(headlines, judgements, prompt_tokens, completion_tokens)`；
    失败只降级为空，绝不拖垮周报。
    """
    bodies = "\n\n".join(
        f"### {seg.title}\n{seg.body.strip()}" for seg in segments if seg.body.strip()
    )
    if not bodies.strip():
        return [], [], 0, 0

    prompt, template = render_prompt(
        "trend/headlines",
        window_start=index.days[0] if index.days else "",
        window_end=index.days[-1] if index.days else "",
        window_days=len(index.days),
        sections=bodies,
        candidates=candidates or "（无）",
        segments=[(key, title) for key, title, _ in SEGMENTS],
    )
    try:
        parsed, result = await generate_structured(
            client,
            [ChatMessage(role="user", content=prompt)],
            response_model=HeadlinesPayload,
            temperature=template.temperature,
            max_tokens=max_tokens,
            purpose=template.purpose,
            model_tier=template.model_tier or "strong",
        )
    except LLMTruncationError as exc:
        log.warning("trend.headlines_truncated", error=str(exc))
        return [], [], exc.prompt_tokens, exc.completion_tokens
    except LLMError as exc:
        log.warning("trend.headlines_failed", error=str(exc))
        return [], [], 0, 0

    if parsed is None or result is None:
        return [], [], result.prompt_tokens if result else 0, 0

    assert isinstance(parsed, HeadlinesPayload)
    headlines = [h.strip() for h in parsed.headlines if h.strip()][:3]
    judgements = [j for j in parsed.judgements if j.claim.strip()]
    return headlines, judgements, result.prompt_tokens, result.completion_tokens


# ══════════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════════


async def generate_trend(
    index: CrossPeriodIndex,
    client: LLMClient,
    *,
    window_days: int = 7,
    max_tokens: int = 2000,
    purpose: str = "trend_weekly",
    price_strong_cny_per_1m: float = 4.0,
    segment_keys: tuple[str, ...] | None = None,
    admission_rule: str = "",
    requested_days: int = 0,
    window_range: tuple[str, str] | None = None,
) -> TrendReport:
    """按 7 节分段生成；单节失败只跳过该节。

    `window_range`：显式分析范围（日历月间隔用）；给了就按范围切片，
    否则按 `window_days` 取最近 N 天。
    """
    if window_range is not None:
        sliced = slice_by_range(index, window_range[0], window_range[1])
    else:
        sliced = slice_index(index, window_days)
    if not sliced.days:
        return TrendReport()
    reports = {report.key: report for report in compute_all(sliced)}
    weak_corr = _has_weak_correlation(reports)

    segments: list[TrendSegment] = []
    calls = 0
    attempts = 0
    truncated: list[str] = []
    prompt_tokens = 0
    completion_tokens = 0

    for key, title, goal in SEGMENTS:
        if segment_keys is not None and key not in segment_keys:
            continue
        evidence = build_evidence(sliced, reports, key)
        prompt, template = render_prompt(
            "trend/weekly",
            segment_key=key,
            segment_title=title,
            segment_goal=goal,
            window_start=sliced.days[0],
            window_end=sliced.days[-1],
            window_days=len(sliced.days),
            evidence=evidence.text,
            word_budget=WORD_BUDGET.get(key, "300-600 字"),
            admission_rule=admission_rule,
        )
        segment = TrendSegment(key=key, title=title)
        attempts += 1
        try:
            result = await client.chat(
                [ChatMessage(role="user", content=prompt)],
                temperature=template.temperature,
                max_tokens=max_tokens,
                purpose=purpose,
                model_tier="strong",
            )
        except LLMTruncationError as exc:
            # 截断也是真花钱：token 随异常带出，必须计入总成本
            log.warning("trend.segment_truncated", segment=key, error=str(exc))
            prompt_tokens += exc.prompt_tokens
            completion_tokens += exc.completion_tokens
            truncated.append(key)
            segment.skipped_reason = f"输出被 max_tokens 截断：{exc}"
            segments.append(segment)
            continue
        except LLMError as exc:
            log.warning("trend.segment_failed", segment=key, error=str(exc))
            segment.skipped_reason = f"LLM 调用失败：{exc}"
            segments.append(segment)
            continue

        calls += 1
        prompt_tokens += result.prompt_tokens
        completion_tokens += result.completion_tokens
        body = (result.content or "").strip()
        segment.body = body
        segment.char_count = char_count(body)
        segment.cited_item_ids = sorted(set(_ITEM_ID_RE.findall(body)))
        segment.boilerplate_hits = boilerplate_hits(body)
        segment.violations = segment_violations(body, key, evidence, weak_corr=weak_corr)
        segment.llm_calls = 1
        segment.prompt_tokens = result.prompt_tokens
        segment.completion_tokens = result.completion_tokens
        segments.append(segment)

    heat = reports.get("heat_migration")
    comp_start = str(heat.metrics.get("comparison_start") or "") if heat else ""
    comp_end = str(heat.metrics.get("comparison_end") or "") if heat else ""
    comp_days = int(heat.metrics.get("comparison_days") or 0) if heat else 0

    # ── 第 8 次调用：三句话 + 各节判断性结论（人类层）──────────────
    headlines: list[str] = []
    judgements: list[Judgement] = []
    if any(segment.body.strip() for segment in segments):
        attempts += 1
        headlines, judgements, h_prompt, h_completion = await generate_headlines(
            sliced,
            segments,
            client,
            max_tokens=max_tokens,
            candidates=build_headline_candidates(sliced, reports),
        )
        prompt_tokens += h_prompt
        completion_tokens += h_completion
        if headlines or judgements:
            calls += 1

    return TrendReport(
        window_start=sliced.days[0],
        window_end=sliced.days[-1],
        window_days=len(sliced.days),
        comparison_start=comp_start,
        comparison_end=comp_end,
        comparison_days=comp_days,
        segments=segments,
        headlines=headlines,
        judgements=judgements,
        caveats=_with_range_shortfall(
            _with_shortfall(build_caveats(sliced, reports), requested_days, sliced),
            window_range,
            sliced,
        ),
        llm_calls=calls,
        attempts=attempts,
        truncated_segments=truncated,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_cny=(prompt_tokens + completion_tokens) * price_strong_cny_per_1m / 1_000_000,
        model_tier="strong",
    )


__all__ = [
    "BOILERPLATE_PHRASES",
    "SEGMENTS",
    "SEGMENT_MAX_CHARS",
    "WORD_BUDGET",
    "Evidence",
    "boilerplate_hits",
    "build_caveats",
    "build_evidence",
    "build_headline_candidates",
    "char_count",
    "generate_headlines",
    "generate_trend",
    "calendar_days",
    "range_shortfall_note",
    "slice_by_range",
    "slice_index",
    "window_shortfall_note",
    "violations",
]
