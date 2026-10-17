"""每日简报 Markdown 渲染（设计方案 §11 / v1.14 简报格式规范）。

固定结构（每日一致，不因字段缺失漂移）：
🔭 标题 → ⚡ 头条（含来源块）→ 📋 分条总览 → ✍️ 四节主编点评 →
分板块表格（空值 `—`）→ ⚔️ 矛盾点 → 💎 被低估 → 页脚。

**表格列固定**是"详略不一"的根治手段：没有增强字段的条目也保留整行，
`为什么重要` / `立场` 显示 `—`，不允许省略行导致结构漂移。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from aipulse.core.timeutil import DEFAULT_TZ, ensure_utc, to_local
from aipulse.schema.brief import DailyBrief, ItemComment
from aipulse.schema.items import SourceEnum
from aipulse.store.models import Item
from aipulse.utils.text import truncate_summary

_DATA_DISCLAIMER = "数据声明：仅存储标题、摘要与公开指标，均标注来源与原链接，不做全文转载。"

_SECTION_ICONS = {
    "开源项目": "🛠️",
    "论文与研究": "📄",
    "社区舆论": "💬",
    "产业与新闻": "🏢",
}
_EDITOR_SECTIONS = (
    ("🎯", "核心判断", "core"),
    ("🔍", "交叉信号", "cross_signal"),
    ("🔄", "反直觉", "counterintuitive"),
    ("⚠️", "风险提醒", "risk"),
)


def _mode_label(mode: str) -> str:
    return {
        "off": "off（未启用 LLM）",
        "hybrid": "hybrid（仅主编点评）",
        "full": "full（完整能力）",
    }.get(mode, mode)


def _source_label(source: str) -> str:
    try:
        return SourceEnum(source).display_name
    except ValueError:
        return source or "—"


def _cell(text: str | None, default: str = "—") -> str:
    """表格单元格：转义竖线、压平换行，空值固定用 `—`（保持列数不变）。"""
    value = " ".join(str(text or "").split())
    if not value:
        return default
    return value.replace("|", "\\|")


def _short(text: str | None, limit: int = 60) -> str:
    return _cell(truncate_summary(str(text or ""), limit))


def _comment_for(comments: dict[str, ItemComment], item_id: str) -> ItemComment | None:
    return comments.get(item_id)


def _resolve_headline_item(brief: DailyBrief, items: dict[str, Item]) -> Item | None:
    """头条必须落到一个真实条目上；LLM 没给 id 时用同标题/最高热度兜底。"""
    if brief.headline_item_id and brief.headline_item_id in items:
        return items[brief.headline_item_id]
    for item in items.values():
        if item.title and item.title == brief.headline:
            return item
    return max(items.values(), key=lambda it: float(it.hot_score or 0.0), default=None)


def _heat_cell(item: Item) -> str:
    hot = round(float(item.hot_score or 0.0), 1)
    text = f"{hot:.1f}"
    if hot >= 85:
        text += " 🔥"
    streak = int((item.metrics or {}).get("streak_days") or 0)
    if streak >= 2:
        text += f" · 连续 {streak} 天"
    return text


def _time_label(generated_at: datetime | None, tz_name: str) -> str:
    if generated_at is None:
        return "—"
    return to_local(ensure_utc(generated_at), tz_name).strftime("%Y-%m-%d %H:%M")


def _counts(meta: dict[str, Any], brief: DailyBrief) -> tuple[Any, Any]:
    analysis = meta.get("analysis")
    if isinstance(analysis, dict) and analysis.get("items") is not None:
        return analysis.get("items"), analysis.get("topics", 0)
    stats = brief.stats or {}
    return stats.get("total_items", "—"), stats.get("topics", "—")


def render_markdown(
    brief: DailyBrief,
    items: dict[str, Item],
    meta: dict[str, Any],
    *,
    generated_at: datetime | None = None,
    max_items_per_section: int = 10,
) -> str:
    mode = str(meta.get("mode", "off"))
    date_str = brief.date.isoformat() if brief.date else ""
    raw_win = meta.get("window")
    win: dict[str, Any] = raw_win if isinstance(raw_win, dict) else {}
    tz_name = str(win.get("tz") or DEFAULT_TZ)
    total_items, total_topics = _counts(meta, brief)

    out: list[str] = [f"# 🔭 AI 脉搏日报 · {date_str}", ""]
    out.append(
        f"> 🕐 生成 {_time_label(generated_at, tz_name)}（{tz_name}）"
        f" · 🤖 模式 {_mode_label(mode)}"
        f" · 📊 {total_items} 条 / {total_topics} 主题"
    )
    if win.get("since_local"):
        out.append(
            f"> ⏱ 覆盖窗口：{win['since_local']} → {win['until_local']}"
            f"（约 {win.get('hours', '?')} 小时）"
        )
    out.append("")

    # ── ⚡ 今日头条：标题 + 来源 / 标题 / 链接 / 平台标签 / 热度 ──────────
    out += ["## ⚡ 今日头条", ""]
    if brief.headline:
        out += [f"### {brief.headline}", ""]
    headline_item = _resolve_headline_item(brief, items)
    if headline_item is not None:
        title = headline_item.title or "(无标题)"
        url = headline_item.url or ""
        linked = f"[{title}]({url})" if url else title
        out.append(f"🔗 来源：{_source_label(headline_item.source)} · {linked}")
        hot = round(float(headline_item.hot_score or 0.0), 1)
        out.append(f"🏷️ `{headline_item.source or '—'}` · 🔥 热度 {hot:.1f}")
    else:
        out.append("🔗 来源：— · —")
        out.append("🏷️ — · 🔥 热度 —")
    out.append("")

    # ── 📋 总览：分条（图标 + 小标题 + 一句话）──────────────────────────
    # off 档的 bullet 是"各板块条数/最高热度"的目录，不是判断 → 标题改为「今日构成」
    overview_title = "今日构成" if mode == "off" else "总览"
    out += [f"## 📋 {overview_title}", ""]
    bullets = brief.overview_bullets
    if bullets:
        for bullet in bullets:
            out.append(f"- {bullet.icon or '📌'} **{_cell(bullet.topic)}**：{_cell(bullet.text)}")
    else:
        out.append(f"- 📌 **今日概览**：{_cell(brief.executive_summary)}")
    duplicate = (
        bool(bullets)
        and brief.executive_summary
        and len(bullets) == 1
        and bullets[0].text == brief.executive_summary
    )
    if brief.executive_summary and not duplicate:
        out += ["", f"> **一句话**：{_cell(brief.executive_summary)}"]
    out.append("")

    # ── ✍️ 主编点评：固定四节（缺字段也保留小节，显示 —）────────────────
    out += ["## ✍️ 主编点评", ""]
    note = brief.editor_note
    for icon, title, field in _EDITOR_SECTIONS:
        out += [f"### {icon} {title}", _cell(getattr(note, field)), ""]

    comments = {c.item_id: c for c in brief.comments}
    # ── 分板块：固定五列表格 ─────────────────────────────────────────
    for section in brief.sections:
        section_items = [items[iid] for iid in section.item_ids if iid in items]
        if not section_items:
            continue  # 空板块不渲染空标题（LLM 偶尔会返回空 item_ids）
        out += [f"## {_SECTION_ICONS.get(section.name, '🧩')} {section.name}", ""]
        if section.summary:
            out += [f"_{_cell(section.summary)}_", ""]
        first_col = "项目" if section.name == "开源项目" else "标题"
        limit = max(0, max_items_per_section)
        out.append(f"| {first_col} | 热度 | 要点 | 为什么重要 | 立场 |")
        out.append("|---|---|---|---|---|")
        for item in section_items[:limit]:
            comment = _comment_for(comments, item.id)
            title = _cell(item.title or "(无标题)")
            title_cell = f"[{title}]({item.url})" if item.url else title
            if comment and comment.one_liner:
                one_liner = comment.one_liner
            elif item.summary:
                one_liner = item.summary
            else:
                # 无摘要时不回退标题（会与第一列重复），保持 — 让"未生成"显式可见
                one_liner = ""
            out.append(
                "| "
                + " | ".join(
                    [
                        title_cell,
                        _heat_cell(item),
                        _short(one_liner),
                        _cell(comment.why_it_matters if comment else ""),
                        _cell(comment.stance if comment else ""),
                    ]
                )
                + " |"
            )
        if len(section_items) > limit:
            out += ["", f"_另有 {len(section_items) - limit} 条未展示（完整列表见 daily.json）_"]
        out.append("")

    if brief.contradictions:
        out += ["## ⚔️ 矛盾点", ""]
        out += [f"{idx}. {_cell(line)}" for idx, line in enumerate(brief.contradictions, 1)]
        out.append("")

    if brief.underrated:
        out += ["## 💎 被低估", ""]
        out += [f"- {_cell(line)}" for line in brief.underrated]
        out.append("")

    out += ["---", ""]
    if meta.get("degraded"):
        out.append(f"> 降级说明：{meta.get('degraded_reason', '部分 LLM 环节已降级')}")
        out.append("")
    out.append(f"<sub>🤖 运行模式 {_mode_label(mode)} · 📄 {_DATA_DISCLAIMER}</sub>")
    out.append("")
    return "\n".join(out)


__all__ = ["render_markdown"]
