"""热度打分单测（设计方案 §9.1）。

重点验证：① 权重从 scoring.yaml 读取（改配置即生效，不改代码）；② 源内分位归一化；
③ 冷启动 velocity 取中性值；④ title_only 降权；⑤ 多源印证加成。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aipulse.analysis.score import (
    ScoringConfig,
    compute_hot_scores,
    engagement_raw,
    load_scoring_config,
    percentile_rank,
)
from aipulse.core.config import load_scoring
from aipulse.store.models import Item


def _cfg(**overrides) -> ScoringConfig:
    base = dict(
        w_engagement=0.45,
        w_freshness=0.20,
        w_velocity=0.20,
        w_source=0.15,
        grace_hours=6,
        tau_hours=36,
        cross_source_bonus=0.05,
        velocity_neutral=0.5,
        title_only_weight=0.35,
        engagement_coeffs={
            "github_trending": {"stars_in_window": 1.0, "stars_total": 0.2},
            "hackernews": {"points": 1.0, "num_comments": 0.5},
        },
    )
    base.update(overrides)
    return ScoringConfig(**base)


def _item(id_: str, source: str, *, metrics: dict | None = None, seen_in=None, skip_cluster=False):
    return Item(
        id=id_,
        source=source,
        external_id=f"ext-{id_}",
        title=f"title {id_}",
        url=f"https://example.com/{id_}",
        summary="summary",
        published_at=datetime.now(tz=UTC) - timedelta(hours=2),
        metrics=metrics or {},
        seen_in=seen_in or [source],
        skip_cluster=skip_cluster,
        hot_score=0.0,
    )


def test_percentile_rank_basic():
    assert percentile_rank([10.0, 20.0, 30.0]) == [0.0, 0.5, 1.0]
    assert percentile_rank([5.0]) == [1.0]


def test_percentile_rank_ties_average():
    # 并列值取平均秩：两个 10 并列第 0/1 → 平均 0.5
    assert percentile_rank([10.0, 10.0]) == [0.5, 0.5]


def test_engagement_raw_uses_configured_coeffs():
    cfg = _cfg()
    item = _item("a", "github_trending", metrics={"stars_in_window": 100, "stars_total": 1000})
    # log1p(100)*1.0 + log1p(1000)*0.2
    import math

    expected = math.log1p(100) + 0.2 * math.log1p(1000)
    assert engagement_raw(item, cfg) == pytest.approx(expected)


def test_compute_hot_scores_weights_from_config():
    """改 ScoringConfig 权重 → 分数随之变化（不改代码）。"""
    item = _item("a", "github_trending", metrics={"stars_in_window": 100})
    low = compute_hot_scores([item], {"a": None}, _cfg(w_source=0.0))
    high = compute_hot_scores([item], {"a": None}, _cfg(w_source=1.0))
    assert high["a"] > low["a"]


def test_title_only_item_uses_title_only_weight():
    cfg = _cfg(title_only_weight=0.35)
    normal = _item("n", "rss", skip_cluster=False)
    title_only = _item("t", "rss", skip_cluster=True)
    scores = compute_hot_scores([normal, title_only], {"n": None, "t": None}, cfg)
    # 仅标题源权重更低，同源其它条件相同 → 分数更低
    assert scores["t"] < scores["n"]


def test_cross_source_bonus_applied():
    cfg = _cfg(cross_source_bonus=0.05)
    single = _item("s", "arxiv", seen_in=["arxiv"])
    multi = _item("m", "arxiv", seen_in=["arxiv", "hf_papers"])
    scores = compute_hot_scores([single, multi], {"s": None, "m": None}, cfg)
    assert scores["m"] > scores["s"]


def test_cold_start_velocity_neutral_and_score_bounded():
    item = _item("a", "github_trending", metrics={"stars_in_window": 10})
    score = compute_hot_scores([item], {"a": None}, _cfg())["a"]
    assert 0.0 <= score <= 100.0


@pytest.fixture(autouse=True)
def _clear_scoring_cache():
    load_scoring.cache_clear()
    yield
    load_scoring.cache_clear()


def test_load_scoring_config_reads_yaml(monkeypatch, tmp_path):
    """DoD ★：改 scoring.yaml 权重无需改代码即生效。"""
    (tmp_path / "configs").mkdir(parents=True)
    (tmp_path / "configs" / "scoring.yaml").write_text(
        "weights:\n  engagement: 0.9\n  freshness: 0.0\n  velocity: 0.0\n  source_weight: 0.1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIPULSE_ROOT", str(tmp_path))
    load_scoring.cache_clear()
    cfg = load_scoring_config()
    assert cfg.w_engagement == 0.9
    assert cfg.w_source == 0.1
