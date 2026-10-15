"""analysis/stats.py 与 render/scoreboard.py 单测（纯函数）。

重点：Brier / 命中率口径、unverifiable 与 pending 不计入分母、校准含低置信桶 `[0.05,0.5)`。
"""

from __future__ import annotations

from datetime import date

from aipulse.analysis.stats import compute_prediction_stats
from aipulse.render.scoreboard import render_scoreboard_markdown
from aipulse.store.models import Prediction

_SCORES = {"hit": 1.0, "partial": 0.5, "miss": 0.0}
_counter = {"n": 0}


def _p(
    verdict: str | None,
    confidence: float,
    *,
    status: str = "verified",
    **kw,
) -> Prediction:
    _counter["n"] += 1
    return Prediction(
        id=f"p{_counter['n']}",
        date=date(2026, 1, 1),
        due_date=date(2026, 1, 31),
        statement="s",
        category=kw.get("category", "product"),
        horizon_days=kw.get("horizon_days", 30),
        origin=kw.get("origin", "llm"),
        model=kw.get("model", "m"),
        prompt_version=kw.get("prompt_version", "v"),
        confidence=confidence,
        status=status,
        verdict=verdict,
        verdict_score=_SCORES.get(verdict or "") if status == "verified" else None,
    )


def test_empty_stats_is_graceful():
    stats = compute_prediction_stats([])
    assert stats.total == 0
    assert not stats.has_results
    board = render_scoreboard_markdown(stats)
    assert "尚无到期判定结果" in board


def test_hit_rate_weighted_and_brier():
    rows = [
        _p("hit", 0.8),  # (0.8-1.0)^2 = 0.04
        _p("miss", 0.6),  # 0.36
        _p("partial", 0.5),  # 0.0
    ]
    stats = compute_prediction_stats(rows)
    assert stats.verified == 3
    assert stats.hits == 1 and stats.partials == 1 and stats.misses == 1
    assert stats.hit_rate == 1 / 3
    assert stats.weighted_score == (1.0 + 0.5 + 0.0) / 3
    assert stats.brier is not None and abs(stats.brier - (0.04 + 0.36 + 0.0) / 3) < 1e-9


def test_unverifiable_and_pending_excluded_from_denominator():
    rows = [
        _p("hit", 0.7),
        _p(None, 0.9, status="unverifiable"),
        _p(None, 0.9, status="pending"),
    ]
    stats = compute_prediction_stats(rows)
    assert stats.total == 3
    assert stats.verified == 1
    assert stats.unverifiable == 1
    assert stats.pending == 1
    assert stats.hit_rate == 1.0  # 分母只有 1 条
    assert stats.brier is not None and abs(stats.brier - 0.09) < 1e-9


def test_calibration_includes_low_confidence_bucket():
    rows = [
        _p("hit", 0.3),  # 应落入 [0.05, 0.5)
        _p("miss", 0.55),  # [0.5, 0.6)
        _p("hit", 0.85),  # [0.8, 0.95]
    ]
    stats = compute_prediction_stats(rows)
    by_label = {b.label: b for b in stats.calibration}
    low = by_label["[0.05, 0.5)"]
    assert low.n == 1 and low.hits == 1 and low.hit_rate == 1.0
    assert by_label["[0.5, 0.6)"].n == 1 and by_label["[0.5, 0.6)"].hit_rate == 0.0
    assert by_label["[0.8, 0.95]"].n == 1


def test_groups_by_category_and_origin():
    rows = [
        _p("hit", 0.8, category="product", origin="llm"),
        _p("miss", 0.6, category="product", origin="human"),
        _p("hit", 0.7, category="research", origin="human"),
    ]
    stats = compute_prediction_stats(rows)
    cats = {g.label: g for g in stats.groups["category"]}
    assert cats["product"].n == 2 and cats["product"].hit_rate == 0.5
    origins = {g.label: g for g in stats.groups["origin"]}
    assert origins["human"].n == 2 and origins["human"].hit_rate == 0.5


def test_scoreboard_non_empty_contains_key_sections():
    stats = compute_prediction_stats([_p("hit", 0.8), _p("miss", 0.6)])
    board = render_scoreboard_markdown(stats)
    assert "预言记分板" in board
    assert "Brier Score" in board
    assert "置信度校准" in board
    assert "[0.05, 0.5)" in board
