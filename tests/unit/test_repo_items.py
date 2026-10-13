"""items / signals 入库层单测。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session, select

from aipulse.core.timeutil import utcnow
from aipulse.schema.items import RawItem, SourceEnum, SourceMetrics
from aipulse.store.db import init_db
from aipulse.store.models import Item, Signal
from aipulse.store.repo_items import (
    clusterable_items,
    item_id,
    to_item_model,
    upsert_items,
    write_signals,
)

BASE = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)


def _repo_item(full_name: str = "owner/repo", stars: int = 1234) -> RawItem:
    return RawItem(
        source=SourceEnum.GITHUB_TRENDING,
        external_id=full_name,
        title=full_name,
        url=f"https://github.com/{full_name}",
        summary="a repo",
        published_at=BASE,
        metrics=SourceMetrics(stars_total=stars, forks=10),
        extra={"source_weight": 1.0},
    )


def test_item_id_is_cross_source_stable():
    """同一篇论文来自 arXiv 或 HF，必须算出同一个 id（存储层天然合并）。"""
    arxiv = RawItem(
        source=SourceEnum.ARXIV,
        external_id="2501.1",
        title="t",
        url="arxiv:2501.1",
        published_at=BASE,
    )
    hf = RawItem(
        source=SourceEnum.HF_PAPERS,
        external_id="2501.1",
        title="t",
        url="arxiv:2501.1",
        published_at=BASE,
    )
    assert item_id(arxiv) == item_id(hf)


def test_upsert_inserts_then_merges_seen_in(tmp_path):
    engine = init_db(tmp_path / "a.db")
    try:
        with Session(engine) as session:
            inserted, updated = upsert_items(session, [_repo_item()])
            assert (inserted, updated) == (1, 0)

            # 第二天再采到同一个 repo：不应新增行，且指标/见过来源被合并
            again = _repo_item(stars=2000)
            again.seen_in = ["github_trending", "hackernews"]
            inserted, updated = upsert_items(session, [again])
            assert (inserted, updated) == (0, 1)

            row = session.exec(select(Item)).one()
            assert row.metrics["stars_total"] == 2000
            assert row.seen_in == ["github_trending", "hackernews"]
    finally:
        engine.dispose()


def test_write_signals_records_star_snapshot(tmp_path):
    """DoD：GitHub stars 快照必须正确写入 signals 表。"""
    engine = init_db(tmp_path / "a.db")
    try:
        with Session(engine) as session:
            count = write_signals(session, [_repo_item(stars=5000)])
            assert count == 1
            signal = session.exec(select(Signal)).one()
            assert signal.entity_type == "repo"
            assert signal.entity_key == "owner/repo"
            assert signal.metric == "stars"
            assert signal.value == 5000.0

            # 同一次采集内（同一 ts）批量写入不会产生重复行；不同 ts 才会新增快照（增速靠它算）
            moment = utcnow()
            assert write_signals(session, [_repo_item(stars=5000)], ts=moment) == 1
            assert write_signals(session, [_repo_item(stars=5000)], ts=moment) == 0
    finally:
        engine.dispose()


def test_write_signals_for_hn_and_paper():
    engine = init_db(":memory:")
    try:
        with Session(engine) as session:
            hn = RawItem(
                source=SourceEnum.HACKERNEWS,
                external_id="123",
                title="story",
                url="https://example.com/s",
                published_at=BASE,
                metrics=SourceMetrics(points=120),
            )
            paper = RawItem(
                source=SourceEnum.HF_PAPERS,
                external_id="2501.5",
                title="paper",
                url="arxiv:2501.5",
                published_at=BASE,
                metrics=SourceMetrics(upvotes=9),
                extra={"arxiv_id": "2501.5"},
            )
            assert write_signals(session, [hn, paper]) == 2
            rows = session.exec(select(Signal)).all()
            assert {r.entity_type for r in rows} == {"hn_story", "paper"}
    finally:
        engine.dispose()


def test_title_only_items_are_not_clusterable(tmp_path):
    """DoD：v1.4 title_only 源（量子位）不得出现在聚类成员里。"""
    engine = init_db(tmp_path / "a.db")
    try:
        with Session(engine) as session:
            qbitai = RawItem(
                source=SourceEnum.RSS,
                external_id="https://qbitai.com/1",
                title="华为AI靠RSI通关25款游戏！",
                url="https://qbitai.com/1",
                published_at=BASE,
                summary="很短的摘要",
                extra={"title_only": True, "feed": "量子位"},
            )
            simon = RawItem(
                source=SourceEnum.RSS,
                external_id="https://simonwillison.net/1",
                title="A long post about agents and tooling",
                url="https://simonwillison.net/1",
                published_at=BASE,
                summary="x" * 500,
                extra={"title_only": False, "feed": "Simon Willison"},
            )
            upsert_items(session, [qbitai, simon])
            eligible = clusterable_items(session)
            assert len(eligible) == 1
            assert eligible[0].title.startswith("A long post")
            assert all("量子位" not in (i.url or "") for i in eligible)
    finally:
        engine.dispose()


def test_to_item_model_carries_metrics_and_hashes():
    model = to_item_model(_repo_item(), now=utcnow())
    assert model.source == "github_trending"
    assert model.cross_key == "repo:owner/repo"
    assert model.metrics["stars_total"] == 1234
    assert model.content_hash and model.simhash
    assert model.hot_score == 0.0
