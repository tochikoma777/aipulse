"""items / signals 入库层单测。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from aipulse.core.timeutil import utcnow
from aipulse.schema.items import RawItem, SourceEnum, SourceMetrics
from aipulse.store.db import init_db
from aipulse.store.models import Item, Signal
from aipulse.store.repo_items import (
    clusterable_items,
    item_id,
    list_items_in_window,
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


def test_state_source_stays_visible_for_three_consecutive_days(tmp_path):
    """★ v1.14 核心回归：持续在榜的 trending 项目必须连续三天都进窗口。

    旧实现把 trending 当事件型源，upsert 保留首次 `published_at`/`collected_at`，
    第二天窗口一滑就永久消失。现在状态型源看 `last_seen_at`。
    """
    engine = init_db(tmp_path / "a.db")
    try:
        with Session(engine) as session:
            first_day = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
            repo = _repo_item("morluto/rea")
            repo.published_at = first_day

            # 事件型对照：比首日窗口起点更早发布，之后不该因为"又被采到"而重现
            paper = RawItem(
                source=SourceEnum.ARXIV,
                external_id="2610.00001",
                title="A paper published on day one",
                url="arxiv:2610.00001",
                published_at=first_day - timedelta(hours=2),
            )

            for offset in range(3):
                collect_at = first_day + timedelta(days=offset)
                upsert_items(session, [repo, paper], now=collect_at)
                start = collect_at - timedelta(hours=24)
                end = collect_at + timedelta(hours=1)
                visible = list_items_in_window(
                    session,
                    since=start,
                    until=end,
                    state_sources={"github_trending"},
                )
                titles = {row.title for row in visible}
                assert "morluto/rea" in titles, f"第 {offset + 1} 天丢了持续在榜项目"
                assert ("A paper published on day one" in titles) is (offset == 0)
    finally:
        engine.dispose()


def test_discovery_source_appears_only_on_first_seen_day(tmp_path):
    """★ v1.15：索引滞后的论文连续三天被采到，只在首次发现那天出现一次。

    arXiv/HF 的 published_at 是 4 天前（索引滞后），不能按它过滤；
    discovery 用 first_seen_at，且 upsert 绝不覆盖——既不丢失，也不重复。
    """
    engine = init_db(tmp_path / "a.db")
    try:
        with Session(engine) as session:
            first_collect = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
            paper = RawItem(
                source=SourceEnum.ARXIV,
                external_id="2610.99999",
                title="A paper indexed three days late",
                url="arxiv:2610.99999",
                published_at=first_collect - timedelta(days=4),
            )

            for offset in range(3):
                collect_at = first_collect + timedelta(days=offset)
                upsert_items(session, [paper], now=collect_at)
                visible = list_items_in_window(
                    session,
                    # 23h 窗口：模拟真实滚动窗口相对采集时刻有偏移，
                    # 避免 first_seen_at 恰好落在窗口左边界上（边界属于 [since, until)）
                    since=collect_at - timedelta(hours=23),
                    until=collect_at + timedelta(hours=1),
                    discovery_sources={"arxiv"},
                )
                assert ("A paper indexed three days late" in {row.title for row in visible}) is (
                    offset == 0
                ), f"第 {offset + 1} 天出现状态错误"

            row = session.exec(
                select(Item).where(Item.title == "A paper indexed three days late")
            ).one()
            assert row.first_seen_at == first_collect
    finally:
        engine.dispose()
