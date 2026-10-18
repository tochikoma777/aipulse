"""每日简报 Markdown 渲染（设计方案 §11 / v1.14 简报格式规范）。

固定结构（每日一致，不因字段缺失漂移）：
🔭 标题 → ⚡ 头条（含来源块）→ 📋 分条总览 → ✍️ 四节主编点评 →
分板块表格（空值 `—`）→ ⚔️ 矛盾点 → 💎 被低估 → 页脚。

**表格列固定**是"详略不一"的根治手段：没有增强字段的条目也保留整行，
`为什么重要` / `立场` 显示 `—`，不允许省略行导致结构漂移。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from aipulse.analysis.signals import RepoStar, item_signal_key, velocity_board
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


def _repo_key(item: Item) -> str | None:
    key = item_signal_key(item)
    return key[1] if key is not None and key[0] == "repo" else None


def _stars_total(star: RepoStar | None) -> str:
    """★ 总数：整数、不加千分位（与增量列宽度一致）。无快照 → `—`。"""
    if star is None or star.total is None:
        return "—"
    return str(int(round(star.total)))


def _window_label(star: RepoStar | None) -> str:
    """窗口长度（首末快照时间差）：`10.3h → 10h`、`41.9h → 42h`、`2.5h → 2.5h`。"""
    if star is None or star.hours is None or star.hours <= 0:
        return ""
    hours = star.hours
    text = f"{round(hours)}" if hours >= 10 else f"{hours:.1f}".rstrip("0").rstrip(".")
    return f"{text}h"


def _stars_delta(star: RepoStar | None) -> str:
    """增量：**绝对增量 + 窗口**（如 `+8617 / 10h`），永远不换算成每小时速率。

    `insufficient`（间隔 < 6h）照样显示绝对增量；`cold_start` / 无数据 → `—`。
    窗口必须可见，否则读者无法判断"7 天涨 5000"和"1 天涨 3000"哪个快。
    """
    if star is None or star.delta is None:
        return "—"
    text = f"{int(round(star.delta)):+d}"
    window = _window_label(star)
    return f"{text} / {window}" if window else text


def _last_seen(star: RepoStar, tz_name: str) -> str:
    if star.last_ts is None:
        return ""
    return to_local(ensure_utc(star.last_ts), tz_name).strftime("%m-%d")


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
    repo_stars: Mapping[str, RepoStar] | None = None,
    velocity_board_enabled: bool = True,
    velocity_board_top_n: int = 5,
) -> str:
    """渲染日报。`repo_stars` 为 `{owner/repo: RepoStar}`（来自 signals 表）。

    不传 `repo_stars` 时表格两列固定显示 `—`——**列数不随数据缺失漂移**（v1.14 格式契约）。
    """
    mode = str(meta.get("mode", "off"))
    stars = repo_stars or {}
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
    # ── 分板块：固定列表格（开源项目额外两列：★ 总数 / 增量）─────────────
    for section in brief.sections:
        section_items = [items[iid] for iid in section.item_ids if iid in items]
        is_repo_section = section.name == "开源项目"
        limit = max(0, max_items_per_section)
        displayed = section_items[:limit]
        board: list[RepoStar] = []
        if is_repo_section and velocity_board_enabled and stars:
            # 排除"今日已展示"的项目，避免同一项目在表格与增速榜各出现一次
            shown = {key for key in (_repo_key(item) for item in displayed) if key}
            board = velocity_board(stars, exclude=shown, top_n=velocity_board_top_n)
        if not section_items and not board:
            continue  # 空板块不渲染空标题（LLM 偶尔会返回空 item_ids）
        out += [f"## {_SECTION_ICONS.get(section.name, '🧩')} {section.name}", ""]
        if section.summary:
            out += [f"_{_cell(section.summary)}_", ""]
        if section_items:
            if is_repo_section:
                # ★ 总数 / 增量紧跟热度：判断项目价值最直接的两个指标（§5.14）
                out.append("| 项目 | 热度 | ★ 总数 | 增量 | 要点 | 为什么重要 | 立场 |")
                out.append("|---|---|---|---|---|---|---|")
            else:
                out.append("| 标题 | 热度 | 要点 | 为什么重要 | 立场 |")
                out.append("|---|---|---|---|---|")
            for item in displayed:
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
                star = stars.get(_repo_key(item) or "") if is_repo_section else None
                cells = [title_cell, _heat_cell(item)]
                if is_repo_section:
                    cells += [_stars_total(star), _stars_delta(star)]
                cells += [
                    _short(one_liner),
                    _cell(comment.why if comment else ""),
                    _cell(comment.stance if comment else ""),
                ]
                out.append("| " + " | ".join(cells) + " |")
            if len(section_items) > limit:
                out += [
                    "",
                    f"_另有 {len(section_items) - limit} 条未展示（完整列表见 daily.json）_",
                ]
        if board:
            out += ["", "### 📈 增速榜（追踪中）", ""]
            out.append(
                "_今日未上榜、但 star 仍在快速增长的项目"
                "（仅取有合规增速窗口的快照；完整序列见 signals.json）_"
            )
            out.append("")
            for star in board:
                line = (
                    f"- **{_cell(star.entity_key)}** · ★{_stars_total(star)} · {_stars_delta(star)}"
                )
                last_seen = _last_seen(star, tz_name)
                if last_seen:
                    line += f" · 上次在榜 {last_seen}"
                out.append(line)
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
