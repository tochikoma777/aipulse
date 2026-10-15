"""指标增速单测（设计方案 §7.2 / §9.1）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aipulse.analysis.signals import (
    build_signals_summary,
    item_signal_key,
    velocity_per_hour,
)
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
        "by_type": {},
        "series": [],
    }
