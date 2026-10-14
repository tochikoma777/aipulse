"""指标增速计算（设计方案 §7.2 / §9.1）。

`signals` 表是计算"真在涨"（velocity）的唯一可靠来源：对同一实体取两次快照，
`Δmetric / Δhours` 即为增速。无历史（<2 个快照）时返回 None，由打分层做中位数兜底。
"""

from __future__ import annotations

from sqlmodel import Session

from aipulse.store.models import Item, Signal
from aipulse.store.repo_items import signals_for_entity

# 各源可算增速的 (entity_type, metric) 映射；不在表内的源（arxiv/rss/inbox）无信号。
_SOURCE_SIGNAL = {
    "github_trending": ("repo", "stars"),
    "hackernews": ("hn_story", "points"),
    "hf_papers": ("paper", "upvotes"),
}


def item_signal_key(item: Item) -> tuple[str, str, str] | None:
    """由条目推断其在 signals 表中的 (entity_type, entity_key, metric)。"""
    mapping = _SOURCE_SIGNAL.get(item.source)
    if mapping is None:
        return None
    entity_type, metric = mapping
    # 论文类实体以 arXiv 编号为 key；repo 以 full_name；hn 以 objectID（均 == external_id）
    entity_key = item.external_id or item.cross_key or ""
    if not entity_key:
        return None
    return entity_type, entity_key, metric


def velocity_per_hour(signals: list[Signal]) -> float | None:
    """由快照序列算 `Δvalue / Δhours`；少于 2 个快照或时间无进展返回 None。"""
    if len(signals) < 2:
        return None
    first, last = signals[0], signals[-1]
    hours = (last.ts - first.ts).total_seconds() / 3600.0
    if hours <= 0:
        return None
    return (last.value - first.value) / hours


def velocity_for_item(session: Session, item: Item) -> float | None:
    """计算单条目的增速；无信号或历史不足返回 None（调用方做冷启动兜底）。"""
    key = item_signal_key(item)
    if key is None:
        return None
    entity_type, entity_key, metric = key
    return velocity_per_hour(signals_for_entity(session, entity_type, entity_key, metric))


__all__ = ["item_signal_key", "velocity_for_item", "velocity_per_hour"]
