"""指标增速单测（设计方案 §7.2 / §9.1）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aipulse.analysis.signals import item_signal_key, velocity_per_hour
from aipulse.store.models import Item, Signal


def _signal(value: float, hours_ago: float) -> Signal:
    return Signal(
        entity_type="repo",
        entity_key="org/a",
        metric="stars",
        value=value,
        ts=datetime.now(tz=UTC) - timedelta(hours=hours_ago),
    )


def test_velocity_per_hour_computes_rate():
    import pytest

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
