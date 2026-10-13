"""items / signals 的写入仓库层（设计方案 §7.1 / §7.2）。

- `upsert_items`：按**源无关的稳定 id** 做 upsert。跨源同一条目（如 arXiv 与 HF 同一篇论文）
  会落到同一行，`seen_in` 累加——这是"合并为一条"在存储层的落地方式。
- `write_signals`：把可观测指标（repo stars / HN points / 论文 upvotes）写成时间序列，
  供后续算增速（star 增速是本项目判断"真在涨"的唯一可靠办法）。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from aipulse.core.hashing import content_hash, cross_source_key, simhash64
from aipulse.core.timeutil import utcnow
from aipulse.schema.items import RawItem
from aipulse.store.models import Item, Signal

_PREFIX = "it_"


def item_id(raw: RawItem) -> str:
    """稳定 id：以跨源键（arxiv:{id} / repo:{full_name}）优先，否则用规范 URL。

    源无关，保证"同一事件"永远落在同一行——跨源合并因此在存储层天然成立。
    """
    key = cross_source_key(raw.url) or raw.url
    return _PREFIX + content_hash(key)[:16]


def item_content_hash(raw: RawItem) -> str:
    """行级指纹（源无关）。注意：dedup 层的 L1 用的是 `sha1(url + source)`，两者用途不同。"""
    return content_hash(raw.url)


def to_item_model(raw: RawItem, *, now: datetime | None = None) -> Item:
    collected = now or utcnow()
    metrics = raw.metrics.model_dump(exclude_none=True)
    return Item(
        id=item_id(raw),
        source=raw.source.value,
        external_id=raw.external_id,
        cross_key=cross_source_key(raw.url),
        title=raw.title,
        url=raw.url,
        summary=raw.summary,
        author=raw.author,
        published_at=raw.normalized_published_at(),
        collected_at=collected,
        language=raw.language,
        tags=list(raw.tags),
        metrics=metrics,
        seen_in=raw.seen_in or [raw.source.value],
        content_hash=item_content_hash(raw),
        simhash=str(simhash64(f"{raw.title} {raw.summary[:500]}")),
        hot_score=0.0,
        # v1.4：仅标题源不参与聚类（M2 聚类器据此跳过）
        skip_cluster=bool((raw.extra or {}).get("title_only")),
    )


def upsert_items(
    session: Session, items: Sequence[RawItem], *, now: datetime | None = None
) -> tuple[int, int]:
    """批量 upsert。返回 `(新增条数, 更新条数)`。"""
    inserted = updated = 0
    for raw in items:
        model = to_item_model(raw, now=now)
        existing = session.get(Item, model.id)
        if existing is None:
            session.add(model)
            inserted += 1
            continue
        # 已存在：合并 seen_in / 指标 / 摘要，不覆盖发布时间（保留首次观测）
        seen = set(existing.seen_in or []) | set(model.seen_in or [])
        existing.seen_in = sorted(seen)
        for key, value in model.metrics.items():
            current = (existing.metrics or {}).get(key)
            if current is None or (isinstance(value, (int, float)) and value > current):
                existing.metrics = {**(existing.metrics or {}), key: value}
        if len(model.summary) > len(existing.summary or ""):
            existing.summary = model.summary
        # 只要有一个源不是仅标题源，就允许参与聚类
        existing.skip_cluster = bool(existing.skip_cluster) and bool(model.skip_cluster)
        updated += 1
    session.commit()
    return inserted, updated


def _signal_rows(raw: RawItem, ts: datetime) -> list[Signal]:
    metrics = raw.metrics
    extra = raw.extra or {}
    rows: list[Signal] = []
    if metrics.stars_total is not None:
        rows.append(
            Signal(
                entity_type="repo",
                entity_key=raw.external_id or str(extra.get("full_name") or raw.title),
                metric="stars",
                value=float(metrics.stars_total),
                ts=ts,
            )
        )
    if metrics.points is not None:
        rows.append(
            Signal(
                entity_type="hn_story",
                entity_key=raw.external_id,
                metric="points",
                value=float(metrics.points),
                ts=ts,
            )
        )
    if metrics.upvotes is not None and extra.get("arxiv_id"):
        rows.append(
            Signal(
                entity_type="paper",
                entity_key=str(extra["arxiv_id"]),
                metric="upvotes",
                value=float(metrics.upvotes),
                ts=ts,
            )
        )
    return rows


def write_signals(session: Session, items: Sequence[RawItem], *, ts: datetime | None = None) -> int:
    """写入指标快照（同一 entity/metric/ts 已存在则跳过，避免重复）。"""
    moment = ts or utcnow()
    count = 0
    for raw in items:
        for row in _signal_rows(raw, moment):
            exists = session.exec(
                select(Signal).where(
                    Signal.entity_type == row.entity_type,
                    Signal.entity_key == row.entity_key,
                    Signal.metric == row.metric,
                    Signal.ts == moment,
                )
            ).first()
            if exists:
                continue
            session.add(row)
            count += 1
    session.commit()
    return count


def clusterable_items(session: Session) -> list[Item]:
    """允许参与聚类的条目（v1.4：排除 `skip_cluster` 的仅标题源）。"""
    return list(session.exec(select(Item).where(Item.skip_cluster.is_(False))).all())  # type: ignore[attr-defined]


def item_to_dict(item: Item) -> dict[str, Any]:
    return {
        "id": item.id,
        "source": item.source,
        "title": item.title,
        "url": item.url,
        "seen_in": item.seen_in,
        "skip_cluster": item.skip_cluster,
        "published_at": item.published_at.isoformat() if item.published_at else None,
    }
