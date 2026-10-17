"""items / signals 的写入仓库层（设计方案 §7.1 / §7.2）。

- `upsert_items`：按**源无关的稳定 id** 做 upsert。跨源同一条目（如 arXiv 与 HF 同一篇论文）
  会落到同一行，`seen_in` 累加——这是"合并为一条"在存储层的落地方式。
- `write_signals`：把可观测指标（repo stars / HN points / 论文 upvotes）写成时间序列，
  供后续算增速（star 增速是本项目判断"真在涨"的唯一可靠办法）。
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import date, datetime
from typing import Any, cast

from sqlalchemy import and_, or_
from sqlmodel import Session, select

from aipulse.core.hashing import content_hash, cross_source_key, short_hash, simhash64
from aipulse.core.timeutil import utcnow
from aipulse.schema.items import RawItem
from aipulse.store.models import Entity, Item, Signal, Topic

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
        first_seen_at=collected,
        last_seen_at=collected,
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
        # ★ 状态型源的关键：只要本次仍被采到就刷新 last_seen_at（无条件，不做 max 比较）。
        #   事件型源的 published_at 保持首次观测，不受影响。
        existing.last_seen_at = model.last_seen_at
        # ★ discovery 语义（arXiv/HF）：first_seen_at 绝不覆盖——同一篇论文即使连续多天
        #   出现在回看结果里，也只在"首次发现那天"进入日报一次。
        #   （新行由 to_item_model 设置，这里对已存在行不做任何操作。）
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


# ── 分析层（M2）读/写辅助 ────────────────────────────────────────────


def list_items(
    session: Session,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int | None = None,
) -> list[Item]:
    """按时间窗取条目（按 published_at 倒序）。since/until 为 UTC。"""
    stmt = select(Item)
    if since is not None:
        stmt = stmt.where(Item.published_at >= since)
    if until is not None:
        stmt = stmt.where(Item.published_at < until)
    stmt = stmt.order_by(Item.published_at.desc())  # type: ignore[attr-defined]
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.exec(stmt).all())


def list_items_collected(
    session: Session,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int | None = None,
) -> list[Item]:
    """按 `collected_at` 时间窗取条目（Web 兜底视图用，不用于日报窗口）。"""
    stmt = select(Item)
    if since is not None:
        stmt = stmt.where(Item.collected_at >= since)
    if until is not None:
        stmt = stmt.where(Item.collected_at < until)
    stmt = stmt.order_by(Item.collected_at.desc())  # type: ignore[attr-defined]
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.exec(stmt).all())


def list_items_in_window(
    session: Session,
    *,
    since: datetime,
    until: datetime,
    state_sources: Collection[str] = (),
    discovery_sources: Collection[str] = (),
) -> list[Item]:
    """按源的时间语义取窗口内条目（设计方案 §5.13 / v1.15 三态）。

    - `event`：`published_at` 落在 `[since, until)`（HN / RSS，发布时间不滞后）；
    - `state`：`last_seen_at` 落在 `[since, until)`（Trending，只要本次还在榜）；
    - `discovery`：`first_seen_at` 落在 `[since, until)`（arXiv / HF，索引滞后 3-4 天，
      关心"今天新发现了什么"；首次发现后即使再次采到也不会重复出现）。

    `state_sources` / `discovery_sources` 来自 `configs/sources.yaml::time_semantics`；
    其余源按 `event` 处理。
    """
    states = set(state_sources)
    discoveries = set(discovery_sources)
    excluded = states | discoveries
    stmt = select(Item)
    if not excluded:
        stmt = stmt.where(Item.published_at >= since, Item.published_at < until)
    else:
        # SQLModel 的类属性在 mypy 眼里是 str/datetime，运行时才是列表达式（沿用仓库里的 cast 收口）
        source_col = cast(Any, Item.source)
        last_seen = cast(Any, Item.last_seen_at)
        first_seen = cast(Any, Item.first_seen_at)
        published = cast(Any, Item.published_at)
        clauses = []
        if states:
            clauses.append(
                and_(
                    source_col.in_(states),
                    last_seen >= since,
                    last_seen < until,
                )
            )
        if discoveries:
            clauses.append(
                and_(
                    source_col.in_(discoveries),
                    first_seen >= since,
                    first_seen < until,
                )
            )
        clauses.append(
            and_(
                source_col.notin_(excluded),
                published >= since,
                published < until,
            )
        )
        stmt = stmt.where(or_(*clauses))
    stmt = stmt.order_by(Item.published_at.desc())  # type: ignore[attr-defined]
    return list(session.exec(stmt).all())


def list_topics(session: Session, day: date) -> list[Topic]:
    return list(session.exec(select(Topic).where(Topic.date == day)).all())


def list_entities(session: Session, day: date) -> list[Entity]:
    return list(session.exec(select(Entity).where(Entity.date == day)).all())


def apply_hot_scores(session: Session, scores: Mapping[str, float]) -> int:
    """把 hot_score 回写到对应条目。返回更新条数。"""
    updated = 0
    for item_id, score in scores.items():
        item = session.get(Item, item_id)
        if item is None:
            continue
        item.hot_score = round(float(score), 4)
        updated += 1
    session.commit()
    return updated


def apply_topic_ids(session: Session, mapping: Mapping[str, str | None]) -> int:
    """回写 items.topic_id（None 表示取消归属）。返回更新条数。"""
    updated = 0
    for item_id, topic_id in mapping.items():
        item = session.get(Item, item_id)
        if item is None:
            continue
        item.topic_id = topic_id
        updated += 1
    session.commit()
    return updated


def topic_uid(name: str, day: date) -> str:
    """主题稳定 id（同一天同名主题复用同一行，避免每日重复建主题）。"""
    return "tp_" + short_hash(f"{day.isoformat()}:{name}", length=12)


def upsert_topics(session: Session, topics: Sequence[Topic]) -> int:
    """按 id upsert 主题。返回写入条数。"""
    count = 0
    for topic in topics:
        session.merge(topic)
        count += 1
    session.commit()
    return count


def upsert_entities(session: Session, entities: Sequence[Entity]) -> int:
    """批量写入实体提及。同一 (name, type, item_id, date) 只写一次。"""
    count = 0
    for entity in entities:
        exists = session.exec(
            select(Entity).where(
                Entity.name == entity.name,
                Entity.type == entity.type,
                Entity.item_id == entity.item_id,
                Entity.date == entity.date,
            )
        ).first()
        if exists is not None:
            continue
        session.add(entity)
        count += 1
    session.commit()
    return count


def list_signals(
    session: Session,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int | None = None,
) -> list[Signal]:
    """取指标快照（按 ts 升序）。M4：供当日 `signals.json` 导出与增速复盘。"""
    stmt = select(Signal)
    if since is not None:
        stmt = stmt.where(Signal.ts >= since)
    if until is not None:
        stmt = stmt.where(Signal.ts <= until)
    stmt = stmt.order_by(Signal.ts.asc())  # type: ignore[attr-defined]
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.exec(stmt).all())


def signals_for_entity(
    session: Session, entity_type: str, entity_key: str, metric: str
) -> list[Signal]:
    """取某实体的指标时间序列（按 ts 升序），供增速计算。"""
    return list(
        session.exec(
            select(Signal)
            .where(
                Signal.entity_type == entity_type,
                Signal.entity_key == entity_key,
                Signal.metric == metric,
            )
            .order_by(Signal.ts.asc())  # type: ignore[attr-defined]
        ).all()
    )


# ── 到期验证（M3b）读辅助 ───────────────────────────────────────────


def signals_max_value(
    session: Session,
    *,
    entity_type: str,
    entity_key: str,
    metric: str,
    since: datetime | None = None,
    until: datetime | None = None,
) -> float | None:
    """某实体-指标在时间窗内的最大值（量化判据查表用）。无数据返回 None。"""
    stmt = select(Signal).where(
        Signal.entity_type == entity_type,
        Signal.entity_key == entity_key,
        Signal.metric == metric,
    )
    if since is not None:
        stmt = stmt.where(Signal.ts >= since)
    if until is not None:
        stmt = stmt.where(Signal.ts <= until)
    values = [row.value for row in session.exec(stmt).all()]
    return max(values) if values else None


def signal_first_seen_map(
    session: Session, *, entity_type: str, key_prefix: str
) -> dict[str, datetime]:
    """某前缀下所有实体键的**首次观测时间** → `{entity_key: first_ts}`。

    用于 `github_new_repo`：首次观测落在窗口内的键 = 窗口内"新出现"的仓库。
    """
    stmt = select(Signal).where(
        Signal.entity_type == entity_type,
        Signal.entity_key.like(f"{key_prefix}%"),  # type: ignore[attr-defined]
    )
    first: dict[str, datetime] = {}
    for row in session.exec(stmt).all():
        current = first.get(row.entity_key)
        if current is None or row.ts < current:
            first[row.entity_key] = row.ts
    return first


def count_entities_in_range(
    session: Session,
    *,
    since_day: date,
    until_day: date,
    name: str | None = None,
) -> int:
    """统计窗口内实体提及行数；`name=None` 时统计全部（用于判断"有无覆盖"）。"""
    stmt = select(Entity).where(Entity.date >= since_day, Entity.date <= until_day)
    if name is not None:
        stmt = stmt.where(Entity.name == name)
    return len(list(session.exec(stmt).all()))


def items_by_source(
    session: Session,
    *,
    source: str,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int | None = None,
) -> list[Item]:
    """按源 + `published_at` 时间窗取条目（量化判据关键词检索用）。"""
    stmt = select(Item).where(Item.source == source)
    if since is not None:
        stmt = stmt.where(Item.published_at >= since)
    if until is not None:
        stmt = stmt.where(Item.published_at <= until)
    stmt = stmt.order_by(Item.published_at.desc())  # type: ignore[attr-defined]
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.exec(stmt).all())


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
