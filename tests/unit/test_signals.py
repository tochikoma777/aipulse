"""指标增速单测（设计方案 §7.2 / §9.1）。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlmodel import Session

from aipulse.analysis.signals import (
    MIN_VELOCITY_WINDOW_HOURS,
    build_signals_summary,
    item_signal_key,
    repo_star_snapshots,
    trending_streak_days,
    velocity_board,
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


# ── §5.14 star 总数 / 增量 / 增速榜 ─────────────────────────────────────


def _repo_signal(key: str, value: float, ts: datetime) -> Signal:
    return Signal(entity_type="repo", entity_key=key, metric="stars", value=value, ts=ts)


# REA 的真实快照（2026-10-17 诊断数据）：10.3 小时涨 8617
_REA = [
    _repo_signal("morluto/rea", 261752.0, datetime(2026, 10, 15, 14, 47, 30, tzinfo=UTC)),
    _repo_signal("morluto/rea", 270369.0, datetime(2026, 10, 16, 1, 3, 59, tzinfo=UTC)),
]


def test_repo_star_snapshots_ok_uses_window_endpoints():
    stars = repo_star_snapshots(_REA)
    rea = stars["morluto/rea"]
    assert rea.status == "ok"
    assert rea.total == 270369.0
    assert rea.delta == 8617.0
    assert rea.last_ts == _REA[-1].ts


def test_repo_star_snapshots_ignores_older_history():
    """lookback 窗口内的首末：7 天前的 100 不能混进增量。"""
    rows = [
        _repo_signal("org/a", 100.0, datetime(2026, 10, 9, 2, 0, tzinfo=UTC)),
        _repo_signal("org/a", 900.0, datetime(2026, 10, 16, 2, 0, tzinfo=UTC)),
        _repo_signal("org/a", 1000.0, datetime(2026, 10, 17, 2, 0, tzinfo=UTC)),
    ]
    star = repo_star_snapshots(rows)["org/a"]
    assert star.delta == 100.0  # 窗口首末之差，而不是含 10-09 的 900
    assert star.total == 1000.0


def test_repo_star_snapshots_dense_runs_still_report_series_delta():
    """★ 真实数据形态：REA 有 5 个快照（多次手动运行），增量仍是首末 +8617。

    如果只取"最近两次"，2 小时的间隔会把 DoD 要求的 +8617 打成 +几百/insufficient。
    """
    rows = [
        *_REA[:1],
        _repo_signal("morluto/rea", 264000.0, datetime(2026, 10, 15, 17, 20, tzinfo=UTC)),
        _repo_signal("morluto/rea", 267500.0, datetime(2026, 10, 15, 22, 20, tzinfo=UTC)),
        _repo_signal("morluto/rea", 269000.0, datetime(2026, 10, 16, 0, 10, tzinfo=UTC)),
        *_REA[1:],
    ]
    star = repo_star_snapshots(rows)["morluto/rea"]
    assert star.status == "ok"
    assert star.total == 270369.0
    assert star.delta == 8617.0
    assert star.first_ts == rows[0].ts


def test_repo_star_snapshots_insufficient_keeps_absolute_delta():
    """间隔 < 6h：仍给绝对增量，但状态标 insufficient（不参与增速榜）。"""
    rows = [
        _repo_signal("org/a", 100.0, datetime(2026, 10, 17, 1, 0, tzinfo=UTC)),
        _repo_signal("org/a", 103.0, datetime(2026, 10, 17, 1, 30, tzinfo=UTC)),
    ]
    star = repo_star_snapshots(rows, min_window_hours=MIN_VELOCITY_WINDOW_HOURS)["org/a"]
    assert star.status == "insufficient"
    assert star.delta == 3.0
    assert star.total == 103.0


def test_repo_star_snapshots_cold_start_has_no_delta():
    rows = [_repo_signal("org/a", 500.0, datetime(2026, 10, 17, 1, 0, tzinfo=UTC))]
    star = repo_star_snapshots(rows)["org/a"]
    assert star.status == "cold_start"
    assert star.total == 500.0
    assert star.delta is None


def test_repo_star_snapshots_no_data():
    assert repo_star_snapshots([]) == {}
    # 非 repo / 非 stars 的信号不参与
    rows = [
        Signal(
            entity_type="hn_story",
            entity_key="1",
            metric="points",
            value=10.0,
            ts=datetime(2026, 10, 17, 1, 0, tzinfo=UTC),
        )
    ]
    assert repo_star_snapshots(rows) == {}


def test_repo_star_snapshots_drops_stale_outside_lookback():
    """lookback 之外的老快照不进序列：只有今天 1 个 → cold_start（增量 —）。"""
    rows = [
        _repo_signal("org/a", 100.0, datetime(2026, 9, 1, 2, 0, tzinfo=UTC)),
        _repo_signal("org/a", 200.0, datetime(2026, 10, 17, 2, 0, tzinfo=UTC)),
    ]
    star = repo_star_snapshots(rows, lookback_days=7.0)["org/a"]
    assert star.status == "cold_start"
    assert star.delta is None


def test_velocity_board_keeps_dropped_repo():
    """★ 核心用例：REA 今天掉榜，但仍应在增速榜出现（不能被 exclusion 误伤）。"""
    rows = [
        *_REA,
        _repo_signal("org/displayed", 1000.0, datetime(2026, 10, 16, 1, 0, tzinfo=UTC)),
        _repo_signal("org/displayed", 1100.0, datetime(2026, 10, 16, 12, 0, tzinfo=UTC)),
    ]
    stars = repo_star_snapshots(rows)
    board = velocity_board(stars, exclude={"org/displayed"}, top_n=5)
    assert [star.entity_key for star in board] == ["morluto/rea"]
    assert board[0].delta == 8617.0


def test_velocity_board_only_ok_and_positive():
    rows = [
        # 间隔不足 → 不上榜
        _repo_signal("org/fast", 10.0, datetime(2026, 10, 17, 1, 0, tzinfo=UTC)),
        _repo_signal("org/fast", 900.0, datetime(2026, 10, 17, 1, 10, tzinfo=UTC)),
        # 掉了 star → 不上榜
        _repo_signal("org/down", 900.0, datetime(2026, 10, 16, 1, 0, tzinfo=UTC)),
        _repo_signal("org/down", 800.0, datetime(2026, 10, 16, 12, 0, tzinfo=UTC)),
        # 合规且上涨 → 上榜
        _repo_signal("org/up", 100.0, datetime(2026, 10, 16, 1, 0, tzinfo=UTC)),
        _repo_signal("org/up", 150.0, datetime(2026, 10, 16, 12, 0, tzinfo=UTC)),
    ]
    board = velocity_board(repo_star_snapshots(rows), top_n=5)
    assert [star.entity_key for star in board] == ["org/up"]


def test_velocity_board_top_n_and_empty():
    rows = []
    for idx in range(7):
        rows += [
            _repo_signal(f"org/r{idx}", 100.0, datetime(2026, 10, 16, 1, 0, tzinfo=UTC)),
            _repo_signal(f"org/r{idx}", 100.0 + idx, datetime(2026, 10, 16, 12, 0, tzinfo=UTC)),
        ]
    board = velocity_board(repo_star_snapshots(rows), top_n=5)
    assert len(board) == 5
    assert [star.entity_key for star in board[:3]] == ["org/r6", "org/r5", "org/r4"]
    assert velocity_board({}, top_n=5) == []


def test_velocity_board_ranks_by_daily_average_not_absolute_delta():
    """★ 核心回归：短窗口高日均必须排在长窗口高绝对值前面。

    长窗口 160h 涨 5000（≈750/天） vs 短窗口 10h 涨 3000（7200/天）。
    按绝对增量排会把前者放前面——那正是本次要修正的错误。
    """
    anchor = datetime(2026, 10, 17, 8, 0, tzinfo=UTC)
    rows = [
        _repo_signal("org/long", 10000.0, anchor - timedelta(hours=160)),
        _repo_signal("org/long", 15000.0, anchor),
        _repo_signal("org/short", 1000.0, anchor - timedelta(hours=10)),
        _repo_signal("org/short", 4000.0, anchor),
    ]
    stars = repo_star_snapshots(rows)

    assert stars["org/long"].delta == 5000.0
    assert stars["org/long"].delta_per_day == pytest.approx(750.0)
    assert stars["org/short"].delta == 3000.0
    assert stars["org/short"].delta_per_day == pytest.approx(7200.0)

    board = velocity_board(stars, top_n=5)
    assert [star.entity_key for star in board] == ["org/short", "org/long"]
