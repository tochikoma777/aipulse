"""weekly.md 的人类层渲染（M5 S5）。

项目总原则：**机器层看过程，人类层看结论**。
这里只负责"给人看"的那一层——三句话 + 判断 + 表格 + 折叠免责 + 文末溯源。

★ 红线：不得为了排版好看而删掉 L1-L4 依赖的数据。
那些数据（7 节正文、裸 ID、violations、免责口径）全在 `weekly.json`
（`TrendReport.to_machine_json()`），**不是被删了，是移到不阻塞阅读的位置**。

- 正文零裸 ID：所有条目一律写成 `[标题](url)`，`it_` 只出现在文末「数据溯源」区。
- 表格数字全部来自 `analysis/cross_period` 的确定性计算，**不经过模型**，不会幻觉。
- 视觉锚点只用 emoji + Markdown 表格 + Unicode 条形图（█░），GitHub 原生可渲染。
"""

from __future__ import annotations

import re
from typing import Any

from aipulse.analysis.cross_period import (
    CrossPeriodIndex,
    PeriodItem,
    compute_all,
)
from aipulse.reasoning.selfcheck import structural_claim_count
from aipulse.reasoning.trend import slice_index
from aipulse.schema.trend import TrendReport

BAR_WIDTH = 10
_ITEM_ID_PREFIX = "it_"


def item_of(index: CrossPeriodIndex, item_id: str) -> PeriodItem | None:
    """按 id 取条目（取最近一次出现，用于标题与链接）。"""
    for day in reversed(index.days):
        snapshot = index.snapshots.get(day)
        if snapshot is None:
            continue
        found = snapshot.items.get(item_id)
        if found is not None:
            return found
    return None


def esc(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def cut(text: str, limit: int = 40) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def link_of(index: CrossPeriodIndex, item_id: str, limit: int = 40) -> str:
    item = item_of(index, item_id)
    if item is None:
        return "（条目已不在窗口内）"
    if not item.url:
        return cut(item.title, limit)
    return f"[{cut(item.title, limit)}]({item.url})"


_ITEM_ID_RE = re.compile(r"it_[0-9a-f]{6,}")


def linkify(index: CrossPeriodIndex, text: str) -> str:
    """把文本里的裸 `it_xxx` 就地换成 `[标题](url)`。

    折叠块里的「全文」是机器层原文，带满 ID；直接给人看仍然晦涩，
    所以渲染时统一换掉——ID 一份不少地留在文末「数据溯源」区。
    """
    seen: dict[str, str] = {}

    def _sub(match: re.Match[str]) -> str:
        item_id = match.group(0)
        if item_id not in seen:
            seen[item_id] = link_of(index, item_id)
        return seen[item_id]

    return _ITEM_ID_RE.sub(_sub, text or "")


_MANUAL_SOURCES = frozenset({"inbox"})
"""手动投喂通道：没有投喂就是 0 条，**不是采集失败**，不进 banner。"""


def _failure_runs(index: CrossPeriodIndex) -> dict[str, int]:
    """各来源在**窗口内**最长的「连续整源 0 条」天数。

    只统计 `source_runs.json` 里记为 failed / degraded 且 item_count=0 的源。
    ★ 口径是"窗口内最长连续段"，不是"截至末日的连续段"：
    arxiv 10-19→10-22 连挂 4 天、10-23 才恢复——若只看尾巴，这 4 天会整段消失，
    而它恰恰是读者判断本周结论可信度的前提。
    """
    longest: dict[str, int] = {}
    current: dict[str, int] = {}
    for day in index.days:
        snapshot = index.snapshots.get(day)
        if snapshot is None:
            continue
        for source, info in snapshot.source_runs.items():
            if source in _MANUAL_SOURCES:
                continue
            status, count = info
            if status in {"failed", "degraded"} and int(count or 0) == 0:
                current[source] = current.get(source, 0) + 1
                longest[source] = max(longest.get(source, 0), current[source])
            else:
                current[source] = 0
    return {source: days for source, days in longest.items() if days > 0}


def health_banner(index: CrossPeriodIndex) -> str:
    """数据健康 banner：**只在数据不健康时出现**，正常时返回空串。

    ★ 这不是新判据，是**呈现层搬家**：同样的信息本来在 `<details>` 折叠区里，
    而折叠区是人看不见的地方——"数据不健康"是读者理解结论可信度的前提，
    应该在正文最前。
    """
    runs = _failure_runs(index)
    claims = structural_claim_count(index)

    parts: list[str] = []
    for source, days in sorted(runs.items(), key=lambda kv: (-kv[1], kv[0]))[:2]:
        parts.append(f"{source} 连续 {days} 天整源 0 条" if days > 1 else f"{source} 整源 0 条")
    if claims < 5:
        parts.append(f"可判结构方向仅 {claims} 条（<5）")
    if not parts:
        return ""
    return "⚠️ 本周 " + "、".join(parts) + "，结论置信度有限"


def _bar(value: float, scale: float) -> str:
    """Unicode 条形图；scale 为满格对应的绝对值。"""
    if scale <= 0:
        return "➖"
    filled = min(BAR_WIDTH, max(1, round(abs(value) / scale * BAR_WIDTH)))
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def _share_rows(reports: dict[str, Any]) -> list[dict[str, Any]]:
    heat = reports.get("heat_migration")
    if heat is None:
        return []
    rows: list[dict[str, Any]] = []
    for entry in heat.entries:
        if not isinstance(entry, dict):
            continue
        rows.append(
            {
                "section": str(entry.get("section") or "未分板块"),
                "t0": entry.get("t0_share"),
                "t1": entry.get("t1_share"),
                "delta": entry.get("delta_pp"),
                "usable": bool(entry.get("trend_usable", True)),
                "note": str(entry.get("trend_note") or ""),
            }
        )
    return rows


def _render_share_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    scale = max((abs(float(r["delta"] or 0)) for r in rows), default=0.0)
    lines = [
        "## 📊 板块份额变化",
        "",
        "| 板块 | 上周 | 本周 | 变化 | |",
        "|---|---|---|---|---|",
    ]
    for row in sorted(rows, key=lambda r: -(abs(float(r["delta"] or 0)))):
        delta = row["delta"]
        if not row["usable"]:
            mark = "⚠️"
            delta_text = "**封锁**"
            left = right = "—"
            bar = ""
        elif delta is None:
            mark = "➖"
            delta_text = "—"
            left = right = "—"
            bar = ""
        else:
            value = float(delta)
            mark = "📉📉" if value <= -5 else ("📉" if value < 0 else "📈")
            delta_text = f"**{value:+.2f}pp**" if abs(value) >= 5 else f"{value:+.2f}pp"
            left = f"{float(row['t0']):.4f}" if row["t0"] is not None else "—"
            right = f"{float(row['t1']):.4f}" if row["t1"] is not None else "—"
            bar = f"`{_bar(value, scale)}`"
        lines.append(f"| {esc(row['section'])} | {left} | {right} | {delta_text} | {mark}{bar} |")
    lines.append("")
    return lines


def _render_dropped_table(index: CrossPeriodIndex, reports: dict[str, Any]) -> list[str]:
    emergence = reports.get("emergence")
    if emergence is None:
        return []
    dropped = [
        e
        for e in emergence.entries
        if isinstance(e, dict) and e.get("kind") == "dropped" and e.get("trend_eligible")
    ]
    dropped.sort(key=lambda e: (-int(e.get("days_on") or 0), -(e.get("hot_at_last_seen") or 0)))
    if not dropped:
        return []
    lines = [
        "## 🔥 值得看的条目",
        "",
        "**连续在榜后跌出 Top30**（不是消失，是掉出前 30）",
        "",
        "| 条目 | 连续在榜 | 跌出时热度 |",
        "|---|---|---|",
    ]
    for entry in dropped[:5]:
        lines.append(
            f"| {link_of(index, str(entry.get('item_id') or ''))} "
            f"| {int(entry.get('days_on') or 0)} 天 "
            f"| {float(entry.get('hot_at_last_seen') or 0):.2f} |"
        )
    lines.append("")
    return lines


def _render_watch_table(index: CrossPeriodIndex, report: TrendReport) -> list[str]:
    """下期观察：对象（链接）｜当前判断｜什么会推翻它（二元可判定）。"""
    if not index.days:
        return []
    last = index.days[-1]
    snapshot = index.snapshots.get(last)
    if snapshot is None:
        return []

    candidates: list[tuple[str, str, str]] = []
    # 长榜条目：连续在榜最久的两条
    on_board = sorted(
        snapshot.items.values(), key=lambda it: (-(it.streak_days or 0), -it.hot_score)
    )
    for item in on_board[:2]:
        candidates.append(
            (
                item.item_id,
                f"连续在榜 {item.streak_days or 1} 天，长榜延续尚未破坏",
                "下一窗口内跌出 Top30",
            )
        )
    # 本期新进榜：热度最高的两条
    fresh = [it for it in snapshot.items.values() if (it.streak_days or 1) <= 1]
    fresh.sort(key=lambda it: -it.hot_score)
    for item in fresh[:2]:
        candidates.append(
            (
                item.item_id,
                "单日冲高，尚不构成趋势",
                f"{_next_day(last)} 仍在 Top30",
            )
        )
    if not candidates:
        return []

    lines = [
        f"## 🎯 下期观察（{_next_day(report.window_end or last)} 起）",
        "",
        "| 观察对象 | 当前判断 | 什么会推翻它 |",
        "|---|---|---|",
    ]
    for item_id, judgement, falsify in candidates:
        lines.append(f"| {link_of(index, item_id)} | {judgement} | {falsify} |")
    lines.append("")
    return lines


def _next_day(day: str) -> str:
    from datetime import date, timedelta

    try:
        return (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    except ValueError:
        return day


def render_weekly(report: TrendReport, index: CrossPeriodIndex) -> str:
    """人类层 weekly.md。正文零裸 ID，免责进折叠块，ID 收进文末溯源区。"""
    sliced = slice_index(index, report.window_days or len(index.days)) if index.days else index
    reports = {r.key: r for r in compute_all(sliced)} if sliced.days else {}

    lines: list[str] = ["# AI 脉搏 · 周度趋势", ""]
    # 数据不健康时在正文最前提示（正常时不出现，不做永久免责）
    banner = health_banner(sliced)
    if banner:
        lines.append(banner)
        lines.append("")
    header = f"**取数 {report.window_start} → {report.window_end}**"
    if report.comparison_start and report.comparison_days:
        header += (
            f" ｜ 比较区间 **{report.comparison_start} → {report.comparison_end}**"
            f"（{report.comparison_days} 天，源集合同构）"
        )
    lines.append(header)
    lines.append("")

    # ── 本周三句话 ──────────────────────────────────────────────────
    if report.headlines:
        lines.append("> ### 📌 本周三句话")
        lines.append(">")
        for i, text in enumerate(report.headlines[:3], 1):
            lines.append(f"> {i}. **{text}**")
        lines.append("")

    lines.append("---")
    lines.append("")

    # ── 判断性结论（来自模型，链接来自代码）────────────────────────
    if report.judgements:
        lines.append("## 🧭 本周判断")
        lines.append("")
        for judgement in report.judgements:
            links = "、".join(link_of(sliced, item_id) for item_id in judgement.cited_item_ids[:3])
            suffix = f" — 依据 {links}" if links else ""
            lines.append(f"- **{judgement.title or judgement.key}**：{judgement.claim}{suffix}")
        lines.append("")

    # ── 表格（全部由 cross_period 确定性渲染）──────────────────────
    lines.extend(_render_share_table(_share_rows(reports)))
    lines.extend(_render_dropped_table(sliced, reports))
    lines.extend(_render_watch_table(sliced, report))

    # ── 免责与口径：折叠 ────────────────────────────────────────────
    if report.caveats:
        lines.append("<details>")
        lines.append("<summary>⚠️ 数据来源与口径说明（点击展开）</summary>")
        lines.append("")
        for caveat in report.caveats:
            text = caveat.strip()
            while text.startswith("- "):
                text = text[2:].strip()
            if text:
                lines.append(f"- {text}")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # ── 数据溯源（裸 ID 只在这里出现）──────────────────────────────
    cited: dict[str, str] = {}
    for segment in report.segments:
        for item_id in segment.cited_item_ids:
            item = item_of(sliced, item_id)
            cited[item_id] = item.title if item else "（不在窗口内）"
    if cited:
        lines.append("---")
        lines.append("")
        lines.append("## 数据溯源")
        lines.append("")
        lines.append("| item_id | 标题 |")
        lines.append("|---|---|")
        for item_id in sorted(cited):
            lines.append(f"| `{item_id}` | {esc(cut(cited[item_id], 60))} |")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


__all__ = ["cut", "esc", "health_banner", "item_of", "link_of", "render_weekly"]
