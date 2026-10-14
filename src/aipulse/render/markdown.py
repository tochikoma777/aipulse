"""每日简报 Markdown 渲染（设计方案 §11）。

产物 `brief.md`：顶部元信息块 + 头条 + 总览 + 主编点评 + 分板块条目 + 矛盾/被低估 +
末尾固定「本次运行模式」与数据声明。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from aipulse.schema.brief import DailyBrief, ItemComment
from aipulse.store.models import Item

_DATA_DISCLAIMER = "数据声明：仅存储标题、摘要与公开指标，均标注来源与原链接，不做全文转载。"


def _mode_label(mode: str) -> str:
    return {
        "off": "off（未启用 LLM）",
        "hybrid": "hybrid（仅主编点评）",
        "full": "full（完整能力）",
    }.get(mode, mode)


def _comment_block(comment: ItemComment | None) -> str:
    if comment is None:
        return ""
    lines = [f"- **一句话**：{comment.one_liner}"] if comment.one_liner else []
    if comment.why_it_matters:
        lines.append(f"- **为什么重要**：{comment.why_it_matters}")
    if comment.who_cares:
        lines.append(f"- **对谁重要**：{comment.who_cares}")
    if comment.what_to_watch:
        lines.append(f"- **下一步关注**：{comment.what_to_watch}")
    if comment.stance:
        lines.append(f"- **立场**：{comment.stance}")
    return "\n".join(lines)


def _item_line(item: Item) -> str:
    title = item.title or "(无标题)"
    url = item.url or ""
    hot = round(float(item.hot_score or 0.0), 1)
    link = f"[{title}]({url})" if url else title
    seen = f" · 来源 {','.join(item.seen_in or [item.source])}" if item.seen_in else ""
    return f"- {link} `[{item.source}]` 热度 {hot}{seen}"


def render_markdown(
    brief: DailyBrief,
    items: dict[str, Item],
    meta: dict[str, Any],
    *,
    generated_at: datetime | None = None,
) -> str:
    mode = str(meta.get("mode", "off"))
    date_str = brief.date.isoformat() if brief.date else ""
    out: list[str] = [f"# AI 脉搏日报 · {date_str}", ""]

    ts = generated_at.isoformat() if generated_at else ""
    out.append(f"> 生成时间：{ts} · 运行模式：{_mode_label(mode)}")
    stats = brief.stats or {}
    if stats.get("total_items") is not None:
        out.append(f"> 条目 {stats['total_items']} · 主题 {stats.get('topics', 0)}")
    out.append("")

    if brief.headline:
        out += ["## 今日头条", "", f"**{brief.headline}**", ""]

    if brief.executive_summary:
        out += ["## 总览", "", brief.executive_summary, ""]

    if brief.editor_note:
        out += ["## 主编点评", "", brief.editor_note, ""]

    comments = {c.item_id: c for c in brief.comments}
    for section in brief.sections:
        out += [f"## {section.name}", ""]
        if section.summary:
            out += [f"_{section.summary}_", ""]
        for item_id in section.item_ids:
            item = items.get(item_id)
            if item is None:
                continue
            out.append(_item_line(item))
            comment = comments.get(item_id)
            if comment is not None:
                block = _comment_block(comment)
                if block:
                    out.append(block)
        out.append("")

    if brief.contradictions:
        out += ["## 矛盾点", ""]
        out += [f"- {c}" for c in brief.contradictions]
        out.append("")

    if brief.underrated:
        out += ["## 被低估", ""]
        out += [f"- {u}" for u in brief.underrated]
        out.append("")

    out += ["---", ""]
    out.append(f"本次运行模式：{_mode_label(mode)}")
    if meta.get("degraded"):
        out.append(f"降级说明：{meta.get('degraded_reason', '部分 LLM 环节已降级')}")
    out.append(_DATA_DISCLAIMER)
    out.append("")
    return "\n".join(out)


__all__ = ["render_markdown"]
