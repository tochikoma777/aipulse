"""每日简报推演层（设计方案 §10.1）。

- 组装上下文：Top N 条目（含 hot_score / topic / 摘要）+ 主题 + 实体频次。
- 三档模式：
  - off：数据版简报（无 LLM，零网络）；hybrid：daily_brief（主编点评）；
  - full：daily_brief + 每条 item_comment（单条点评）。
- 任何 LLM 失败（网络 / 非法 JSON 降级）都回落到数据版简报，绝不中断流水线。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any, cast

from aipulse.core.config import RunMode, Settings
from aipulse.core.logging import get_logger
from aipulse.llm.base import ChatMessage, LLMClient
from aipulse.llm.prompt import render_prompt
from aipulse.llm.structured import generate_structured
from aipulse.schema.brief import DailyBrief, ItemComment, ItemComments, Section
from aipulse.store.models import Item, Topic
from aipulse.utils.text import estimate_tokens, truncate_summary

log = get_logger(__name__)

# 源 → 板块映射（off 档数据版简报用；LLM 档由模型自行归组）
_SOURCE_SECTION = {
    "github_trending": "开源项目",
    "arxiv": "论文与研究",
    "hf_papers": "论文与研究",
    "hackernews": "社区舆论",
    "reddit": "社区舆论",
    "rss": "产业与新闻",
    "inbox": "产业与新闻",
}

_MAX_CONTEXT_TOKENS = 12000


@dataclass
class BriefOutput:
    brief: DailyBrief
    items: dict[str, Item] = field(default_factory=dict)  # item_id → Item（渲染用）
    meta: dict[str, Any] = field(default_factory=dict)


def _item_context(item: Item, topic_name: str | None) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "source": item.source,
        "hot_score": round(float(item.hot_score or 0.0), 1),
        "topic": topic_name or "",
        "summary": truncate_summary(item.summary or "", 300),
    }


def _trim_to_budget(
    contexts: list[dict[str, Any]], budget: int = _MAX_CONTEXT_TOKENS
) -> list[dict[str, Any]]:
    """总量超预算时从尾部丢弃（已按 hot_score 降序，丢的是最不重要的）。"""
    kept: list[dict[str, Any]] = []
    total = 0
    for ctx in contexts:
        total += estimate_tokens(json.dumps(ctx, ensure_ascii=False))
        if total > budget:
            break
        kept.append(ctx)
    return kept


def _topic_name_map(topics: list[Topic]) -> dict[str, str]:
    return {t.id: t.name for t in topics}


def _data_brief(
    items: list[Item],
    topics: list[Topic],
    entity_counts: dict[str, dict[str, Any]],
    day: date,
    sections: list[str],
) -> DailyBrief:
    """off 档 / 降级兜底：纯数据版简报（§8.5.3 的替代方案）。"""
    top = items[0] if items else None
    headline = top.title if top else "今日无数据"

    grouped: dict[str, list[str]] = {s: [] for s in sections}
    for it in items:
        grouped.setdefault(_SOURCE_SECTION.get(it.source, "其他"), []).append(it.id)

    section_models = [
        Section(name=s, item_ids=grouped.get(s, [])) for s in sections if grouped.get(s)
    ]

    top_entities = sorted(entity_counts.items(), key=lambda kv: -kv[1]["count"])[:10]
    source_counts: dict[str, int] = {}
    for it in items:
        source_counts[it.source] = source_counts.get(it.source, 0) + 1

    summary = (
        f"今日共采集 {len(items)} 条，覆盖 {len(topics)} 个主题、{len(source_counts)} 个来源；"
        + (f"热度最高：{headline}。" if top else "")
    )
    stats: dict[str, Any] = {
        "total_items": len(items),
        "topics": len(topics),
        "sources": source_counts,
        "top_entities": [
            {"name": n, "type": v["type"], "count": v["count"]} for n, v in top_entities
        ],
    }
    return DailyBrief(
        date=day,
        headline=headline,
        executive_summary=summary,
        sections=section_models,
        editor_note="off 档：未启用 LLM，本简报为数据版（无点评）。",
        contradictions=[],
        underrated=[],
        comments=[],
        stats=stats,
    )


async def generate_brief(
    *,
    client: LLMClient,
    settings: Settings,
    items: list[Item],
    topics: list[Topic],
    entity_counts: dict[str, dict[str, Any]],
    day: date,
    mode: RunMode,
    skip_llm: bool = False,
    top_n: int | None = None,
) -> BriefOutput:
    """生成每日简报。返回 BriefOutput（brief + 渲染用的 items + meta）。"""
    top_n = int(top_n) if top_n is not None else int(settings.pipeline.daily_top_n)
    sections = list(settings.pipeline.brief_sections)
    topic_names = _topic_name_map(topics)

    # 按热度排序，取 Top N
    ranked = sorted(items, key=lambda it: -(float(it.hot_score or 0.0)))[:top_n]
    contexts = _trim_to_budget(
        [_item_context(it, topic_names.get(it.topic_id or "")) for it in ranked]
    )
    chosen_ids = [c["id"] for c in contexts]
    chosen_items = {it.id: it for it in ranked if it.id in chosen_ids}
    ordered_items = [chosen_items[cid] for cid in chosen_ids]

    if mode == RunMode.OFF or skip_llm:
        off_brief = _data_brief(ordered_items, topics, entity_counts, day, sections)
        return BriefOutput(brief=off_brief, items=chosen_items, meta={"mode": "off"})

    # ── hybrid / full：调 LLM ──────────────────────────────────────
    meta: dict[str, Any] = {"mode": mode.value, "degraded": False, "llm_calls": 0}
    brief: DailyBrief | None = None
    try:
        rendered, template = render_prompt(
            "brief/daily_brief",
            items_json=json.dumps(contexts, ensure_ascii=False),
            entities_json=json.dumps(
                [
                    {"name": n, "type": v["type"], "count": v["count"]}
                    for n, v in sorted(entity_counts.items(), key=lambda kv: -kv[1]["count"])[:20]
                ],
                ensure_ascii=False,
            ),
            sections_json=json.dumps(sections, ensure_ascii=False),
        )
        parsed, _ = await generate_structured(
            client,
            [ChatMessage(role="system", content=rendered)],
            response_model=DailyBrief,
            temperature=template.temperature,
            max_tokens=4000,
            purpose="brief_daily",
            model_tier=template.model_tier,
        )
        meta["llm_calls"] += 1
        if parsed is not None:
            daily = cast(DailyBrief, parsed)
            daily.date = day
            brief = daily
    except Exception as exc:  # 网络/预算等异常：降级不中断
        log.error("brief.llm_failed", error=repr(exc))
        meta["degraded"] = True
        meta["degraded_reason"] = f"LLM 调用失败：{type(exc).__name__}"

    if brief is None:
        brief = _data_brief(ordered_items, topics, entity_counts, day, sections)
        meta["degraded"] = True
        meta.setdefault("degraded_reason", "LLM 结构化输出失败，已降级为数据版")

    # ── full：单条点评 ─────────────────────────────────────────────
    if mode == RunMode.FULL and not meta.get("degraded"):
        try:
            brief.comments = await _item_comments(client, ordered_items, meta)
        except Exception as exc:
            log.warning("brief.item_comments_failed", error=repr(exc))

    return BriefOutput(brief=brief, items=chosen_items, meta=meta)


async def _item_comments(
    client: LLMClient, items: list[Item], meta: dict[str, Any]
) -> list[ItemComment]:
    """full 档：对 Top N 条目生成单条点评（一条批量调用）。"""
    contexts = [
        {
            "id": it.id,
            "title": it.title,
            "source": it.source,
            "summary": truncate_summary(it.summary or "", 300),
        }
        for it in items
    ]
    rendered, template = render_prompt(
        "brief/item_comment",
        items_json=json.dumps(contexts, ensure_ascii=False),
    )
    parsed, _ = await generate_structured(
        client,
        [ChatMessage(role="system", content=rendered)],
        response_model=ItemComments,
        temperature=template.temperature,
        max_tokens=3000,
        purpose="brief_item_comment",
        model_tier=template.model_tier,
    )
    meta["llm_calls"] += 1
    if parsed is None:
        return []
    return cast(ItemComments, parsed).comments


__all__ = ["BriefOutput", "generate_brief"]
