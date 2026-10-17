"""每日简报 JSON 渲染（设计方案 §11：`daily.json`，机器可读）。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from aipulse.schema.brief import DailyBrief
from aipulse.store.models import Item


def _item_dict(item: Item) -> dict[str, Any]:
    return {
        "id": item.id,
        "source": item.source,
        "title": item.title,
        "url": item.url,
        "summary": item.summary,
        "hot_score": round(float(item.hot_score or 0.0), 4),
        "topic_id": item.topic_id,
        "seen_in": item.seen_in or [],
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "last_seen_at": item.last_seen_at.isoformat() if item.last_seen_at else None,
        "metrics": item.metrics or {},
        "streak_days": int((item.metrics or {}).get("streak_days") or 0),
        "language": item.language,
    }


def render_json(
    brief: DailyBrief,
    items: dict[str, Item],
    meta: dict[str, Any],
    *,
    generated_at: datetime | None = None,
) -> str:
    """产出 daily.json 全文（含 brief、条目明细、运行元信息）。"""
    payload: dict[str, Any] = {
        "date": brief.date.isoformat() if brief.date else None,
        "headline": brief.headline,
        "headline_item_id": brief.headline_item_id,
        "overview_bullets": [b.model_dump() for b in brief.overview_bullets],
        "executive_summary": brief.executive_summary,
        "editor_note": brief.editor_note.model_dump(),
        "contradictions": brief.contradictions,
        "underrated": brief.underrated,
        "sections": [
            {"name": s.name, "summary": s.summary, "item_ids": s.item_ids} for s in brief.sections
        ],
        "comments": [c.model_dump() for c in brief.comments],
        "stats": brief.stats,
        "items": {iid: _item_dict(it) for iid, it in items.items()},
        "meta": {
            **meta,
            "generated_at": generated_at.isoformat() if generated_at else None,
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


__all__ = ["render_json"]
