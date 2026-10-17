"""指标增速单测（设计方案 §7.2 / §9.1）。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlmodel import Session

from aipulse.analysis.signals import (
    MIN_VELOCITY_WINDOW_HOURS,
    build_signals_summary,
    item_signal_key,
    trending_streak_days,
    velocity_per_hour,
)
from aipulse.store.db import init_db
from aipulse.store.models import Item, Signal


def _signal(value: float, hours_ago: float, *, key: str = "org/a") -> Signal:
    return Signal(
        entity_type="repo",
        entity_key=key,
        metric="stars",
        value=value,
        ts=datetime.now(tz=UTC) - timedelta(hours=hours_ago),
    )


def test_velocity_per_hour_computes_rate():
    signals = [_signal(100.0, 48.0), _signal(200.0, 0.0)]  # 48 小时涨 100 → 100/48
    assert velocity_per_hour(signals) == pytest.approx(100.0 / 48.0)


def test_velocity_per_hour_requires_two_snapshots():
    assert velocity_per_hour([_signal(100.0, 0.0)]) is None
    assert velocity_per_hour([]) is None


def test_velocity_per_hour_zero_time_returns_none():
    ts = datetime.now(tz=UTC)
    s = [
        Signal(entity_type="repo", entity_key="org/a", metric="stars", value=1.0, ts=ts),
        Signal(entity_type="repo", entity_key="org/a", metric="stars", value=2.0, ts=ts),
    ]
    assert velocity_per_hour(s) is None


def test_item_signal_key_maps_sources():
    gh = Item(id="i", source="github_trending", external_id="org/a")
    assert item_signal_key(gh) == ("repo", "org/a", "stars")

    hn = Item(id="i", source="hackernews", external_id="123")
    assert item_signal_key(hn) == ("hn_story", "123", "points")

    arxiv = Item(id="i", source="arxiv", external_id="2501.1")
    assert item_signal_key(arxiv) is None


def test_build_signals_summary_computes_velocity_per_entity():
    """M4 DoD：连续两天的快照要能算出 star 增速。"""
    summary = build_signals_summary([_signal(100.0, 48.0), _signal(200.0, 24.0)])

    assert summary["entity_count"] == 1
    assert summary["point_count"] == 2
    assert summary["with_velocity"] == 1
    assert summary["by_type"] == {"repo": {"entities": 1, "points": 2}}

    entry = summary["series"][0]
    assert entry["entity_key"] == "org/a"
    assert entry["delta"] == 100.0
    assert entry["velocity_per_hour"] == pytest.approx(100.0 / 24.0)
    assert entry["velocity_24h"] == pytest.approx(100.0)


def test_build_signals_summary_cold_start_single_point():
    """只有一个快照（跨天不足）时不报错，增速为 None。"""
    summary = build_signals_summary([_signal(100.0, 0.0)])

    assert summary["with_velocity"] == 0
    assert summary["series"][0]["velocity_per_hour"] is None
    assert summary["series"][0]["delta"] == 0.0


def test_build_signals_summary_sorts_velocity_first():
    """有增速的序列排前面，冷启动的排后面（便于肉眼比对跨天变化）。"""
    rows = [
        _signal(10.0, 24.0, key="org/cold"),
        _signal(100.0, 48.0, key="org/hot"),
        _signal(300.0, 24.0, key="org/hot"),
    ]
    keys = [s["entity_key"] for s in build_signals_summary(rows)["series"]]
    assert keys == ["org/hot", "org/cold"]


def test_build_signals_summary_empty():
    summary = build_signals_summary([])
    assert summary == {
        "point_count": 0,
        "entity_count": 0,
        "with_velocity": 0,
        "insufficient": 0,
        "cold_start": 0,
        "min_window_hours": MIN_VELOCITY_WINDOW_HOURS,
        "by_type": {},
        "series": [],
    }


def test_velocity_requires_minimum_window():
    """★ M4 保护：两次快照间隔 < 6h 必须标 insufficient 且不给数字。

    调试/手动重跑常在同一小时内连跑，Δ/hour 会把"几分钟涨 3 star"放大成"日增 3000"——
    离谱数据比没有数据更伤可信度。
    """
    summary = build_signals_summary([_signal(100.0, 2.0), _signal(103.0, 1.0)])

    entry = summary["series"][0]
    assert entry["status"] == "insufficient"
    assert entry["hours"] < MIN_VELOCITY_WINDOW_HOURS
    assert entry["velocity_per_hour"] is None
    assert entry["velocity_24h"] is None
    assert entry["delta"] == 3.0  # 绝对增量仍如实记录，只是不给"率"
    assert summary["with_velocity"] == 0
    assert summary["insufficient"] == 1


def test_velocity_boundary_exactly_min_window_is_ok():
    rows = [_signal(100.0, MIN_VELOCITY_WINDOW_HOURS), _signal(160.0, 0.0)]
    entry = build_signals_summary(rows)["series"][0]

    assert entry["status"] == "ok"
    assert entry["velocity_per_hour"] == pytest.approx(10.0)  # 60 / 6h


def test_velocity_window_is_configurable():
    """阈值走配置（`signals.min_velocity_window_hours`），可由调用方传入。"""
    rows = [_signal(100.0, 2.0), _signal(120.0, 0.0)]

    assert build_signals_summary(rows)["series"][0]["status"] == "insufficient"
    relaxed = build_signals_summary(rows, min_window_hours=1.0)
    assert relaxed["series"][0]["status"] == "ok"
    assert relaxed["min_window_hours"] == 1.0


def test_cold_start_is_distinct_from_insufficient():
    single = build_signals_summary([_signal(100.0, 0.0)])["series"][0]
    assert single["status"] == "cold_start"
    assert build_signals_summary([_signal(100.0, 0.0)])["cold_start"] == 1


def test_trending_streak_days_counts_consecutive_local_days(tmp_path):
    """v1.14：连续在榜天数由 signals 快照的本地日期倒推（同日多次只算一天）。"""
    engine = init_db(tmp_path / "a.db")
    try:
        with Session(engine) as session:
            for day in (15, 16, 17):
                session.add(
                    Signal(
                        entity_type="repo",
                        entity_key="morluto/rea",
                        metric="stars",
                        value=1000.0 + day,
                        ts=datetime(2026, 10, day, 2, 0, tzinfo=UTC),  # 北京 10:00，同一本地日
                    )
                )
            # 同一天再跑一次不增加天数
            session.add(
                Signal(
                    entity_type="repo",
                    entity_key="morluto/rea",
                    metric="stars",
                    value=2000.0,
                    ts=datetime(2026, 10, 17, 6, 0, tzinfo=UTC),
                )
            )
            session.commit()

            item = Item(id="i", source="github_trending", external_id="morluto/rea")
            assert trending_streak_days(session, item, anchor=date(2026, 10, 17)) == 3
            # 17 号没采到 → 不能把历史连续天数算成"仍在榜"
            assert trending_streak_days(session, item, anchor=date(2026, 10, 18)) == 0
    finally:
        engine.dispose()


def test_trending_streak_days_breaks_on_gap(tmp_path):
    engine = init_db(tmp_path / "a.db")
    try:
        with Session(engine) as session:
            for day in (15, 17):
                session.add(
                    Signal(
                        entity_type="repo",
                        entity_key="org/gap",
                        metric="stars",
                        value=1.0,
                        ts=datetime(2026, 10, day, 2, 0, tzinfo=UTC),
                    )
                )
            session.commit()
            item = Item(id="i", source="github_trending", external_id="org/gap")
            assert trending_streak_days(session, item, anchor=date(2026, 10, 17)) == 1
    finally:
        engine.dispose()
