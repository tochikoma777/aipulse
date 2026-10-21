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
from dataclasses import dataclass

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
from aipulse.schema.trend import TrendReport, TrendSegment

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
    "rising_topics": 500,
    "falling_topics": 500,
    "emerging_topics": 400,
    "structural_changes": 600,
    "second_order_effects": 600,
    "prediction_review": 100,
    "watchlist": 500,
}

WORD_BUDGET: dict[str, str] = {
    "rising_topics": "300-500 字",
    "falling_topics": "300-500 字",
    "emerging_topics": "250-400 字",
    "structural_changes": "450-600 字",
    "second_order_effects": "450-600 字",
    "prediction_review": "不超过 100 字，一句话说清即可",
    "watchlist": "300-500 字",
}


@dataclass(frozen=True)
class Evidence:
    """一段的证据文本 + 其中的标题（用于检测"复述标题"）。"""

    text: str
    titles: tuple[str, ...] = ()


def slice_index(index: CrossPeriodIndex, window_days: int) -> CrossPeriodIndex:
    """取最近 N 天构建子索引（30 天窗口留到下一阶段，本轮只做 7 天）。"""
    days = index.days[-window_days:] if window_days > 0 else index.days
    keep = set(days)
    return CrossPeriodIndex(
        days=days,
        snapshots={day: index.snapshots[day] for day in days},
        predictions=tuple(p for p in index.predictions if p.day in keep),
    )


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
    rows = [
        e
        for e in report.entries
        if e.get("trend_usable", True) and (float(e["delta_pp"]) > 0) == positive
    ]
    if not rows:
        return ["- 无可用板块（无符合方向的条目，或相关板块采集异常已剔除）"]
    out: list[str] = []
    for entry in rows[:limit]:
        ids = _ids(entry.get("t1_top_items"), 3)
        excluded = entry.get("excluded_days") or []
        note = f"；已排除 {len(excluded)} 个板块空日" if excluded else ""
        out.append(
            f"- {entry['section']}：份额 {entry['t0_share']}→{entry['t1_share']}"
            f"（{float(entry['delta_pp']):+.2f}pp）；"
            f"窗口斜率 {float(entry['slope_pp_per_day']):+.2f}pp/天"
            f"（基于 {entry['slope_days']} 天）{note}；代表 {ids}"
        )
    return out


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
        blocks.append("### 板块份额（上升）\n" + "\n".join(_heat_lines(reports, positive=True)))
        blocks.append(
            "### 同步变化组（未做显著性检验）\n"
            + "\n".join(_group_lines(reports, coherent_only=False))
        )
        blocks.append("### 相邻两日热度上升\n" + "\n".join(_top_movers(index, rising=True)))
        _append_taint()
        _append_failures()
    elif key == "falling_topics":
        blocks.append("### 板块份额（下降）\n" + "\n".join(_heat_lines(reports, positive=False)))
        blocks.append("### 连续在榜后跌出 Top30\n" + "\n".join(_event_lines(reports, ("dropped",))))
        blocks.append("### 相邻两日热度下降\n" + "\n".join(_top_movers(index, rising=False)))
        _append_taint()
        _append_failures()
    elif key == "emerging_topics":
        blocks.append(
            "### 今日新进榜（单日，不构成趋势）\n" + "\n".join(_event_lines(reports, ("new",)))
        )
        blocks.append(
            "### 回到榜与反复进出\n" + "\n".join(_event_lines(reports, ("returned", "fluctuating")))
        )
    elif key in ("structural_changes", "second_order_effects"):
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
) -> TrendReport:
    """按 7 节分段生成；单节失败只跳过该节。"""
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
            segment_title=title,
            segment_goal=goal,
            window_start=sliced.days[0],
            window_end=sliced.days[-1],
            window_days=len(sliced.days),
            evidence=evidence.text,
            word_budget=WORD_BUDGET.get(key, "300-600 字"),
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
        segment.violations = violations(
            body,
            evidence,
            requires_speculation=key in _SPECULATION_SEGMENTS,
            weak_corr=weak_corr,
            max_chars=SEGMENT_MAX_CHARS.get(key),
            # 预言复盘本来就是计数类结论，没有条目级事实可引用
            require_item_id=key != "prediction_review",
        )
        segment.llm_calls = 1
        segment.prompt_tokens = result.prompt_tokens
        segment.completion_tokens = result.completion_tokens
        segments.append(segment)

    return TrendReport(
        window_start=sliced.days[0],
        window_end=sliced.days[-1],
        window_days=len(sliced.days),
        segments=segments,
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
    "build_evidence",
    "char_count",
    "generate_trend",
    "slice_index",
    "violations",
]
