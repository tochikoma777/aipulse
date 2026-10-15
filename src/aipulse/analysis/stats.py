"""预言统计（设计方案 §10.2.3 v1.9，纯算法，零成本）。

口径（v1.9 裁定，违反即统计失真）：
- **分母**：`unverifiable` 与 `pending` **不计入**命中率 / Brier（它们没有判定结果）。
- **Brier** = `mean((confidence - verdict_score)^2)`，`partial` 按 `outcome = 0.5` 计入。
- **校准分桶**含低置信桶 `[0.05, 0.5)`——confidence 下限是 0.05，只统计 0.5+ 会静默
  丢弃低置信样本，让校准曲线系统性偏高失真。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from aipulse.core.timeutil import utcnow
from aipulse.store.models import Prediction

# 校准分桶（上界用 0.951 以纳入 confidence 上限 0.95）
CALIBRATION_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("[0.05, 0.5)", 0.05, 0.5),
    ("[0.5, 0.6)", 0.5, 0.6),
    ("[0.6, 0.7)", 0.6, 0.7),
    ("[0.7, 0.8)", 0.7, 0.8),
    ("[0.8, 0.95]", 0.8, 0.951),
)

_GROUP_FIELDS: tuple[str, ...] = ("category", "horizon_days", "origin", "model", "prompt_version")


@dataclass
class CalibrationBucket:
    label: str
    n: int = 0
    hits: int = 0
    confidence_sum: float = 0.0

    @property
    def mean_confidence(self) -> float | None:
        return self.confidence_sum / self.n if self.n else None

    @property
    def hit_rate(self) -> float | None:
        return self.hits / self.n if self.n else None


@dataclass
class GroupStat:
    key: str
    label: str
    n: int = 0
    hits: int = 0
    score_sum: float = 0.0

    @property
    def hit_rate(self) -> float | None:
        return self.hits / self.n if self.n else None

    @property
    def weighted_score(self) -> float | None:
        return self.score_sum / self.n if self.n else None


@dataclass
class PredictionStats:
    total: int = 0
    verified: int = 0
    unverifiable: int = 0
    pending: int = 0
    hits: int = 0
    partials: int = 0
    misses: int = 0
    hit_rate: float | None = None
    weighted_score: float | None = None
    brier: float | None = None
    calibration: list[CalibrationBucket] = field(default_factory=list)
    groups: dict[str, list[GroupStat]] = field(default_factory=dict)
    earliest_date: date | None = None
    generated_at: str = ""

    @property
    def has_results(self) -> bool:
        return self.verified > 0


def compute_prediction_stats(
    rows: Sequence[Prediction], *, generated_at: str | None = None
) -> PredictionStats:
    """从预言行计算全部统计量。只把 `verified` 且有 verdict 的行计入分母。"""
    stats = PredictionStats(generated_at=generated_at or utcnow().isoformat())
    buckets: dict[str, CalibrationBucket] = {
        label: CalibrationBucket(label=label) for label, _, _ in CALIBRATION_BUCKETS
    }
    groups: dict[str, dict[str, GroupStat]] = {f: {} for f in _GROUP_FIELDS}
    brier_sum = 0.0
    score_sum = 0.0
    results = 0
    dates = [row.date for row in rows if row.date]
    stats.earliest_date = min(dates) if dates else None

    for row in rows:
        stats.total += 1
        if row.status == "unverifiable":
            stats.unverifiable += 1
            continue
        if row.status != "verified" or row.verdict is None or row.verdict_score is None:
            stats.pending += 1
            continue

        # ── 计入分母 ──
        stats.verified += 1
        results += 1
        score = float(row.verdict_score)
        score_sum += score
        if row.verdict == "hit":
            stats.hits += 1
        elif row.verdict == "partial":
            stats.partials += 1
        else:
            stats.misses += 1
        confidence = float(row.confidence)
        brier_sum += (confidence - score) ** 2

        for bucket_label, lo, hi in CALIBRATION_BUCKETS:
            if lo <= confidence < hi:
                bucket = buckets[bucket_label]
                bucket.n += 1
                bucket.confidence_sum += confidence
                if row.verdict == "hit":
                    bucket.hits += 1
                break

        for field_name in _GROUP_FIELDS:
            raw = getattr(row, field_name, None)
            label = str(raw) if raw not in (None, "") else "(未知)"
            entry = groups[field_name].setdefault(label, GroupStat(key=field_name, label=label))
            entry.n += 1
            entry.score_sum += score
            if row.verdict == "hit":
                entry.hits += 1

    if results:
        stats.hit_rate = stats.hits / results
        stats.weighted_score = score_sum / results
        stats.brier = brier_sum / results
    stats.calibration = [buckets[label] for label, _, _ in CALIBRATION_BUCKETS]
    stats.groups = {
        name: sorted(values.values(), key=lambda g: -g.n) for name, values in groups.items()
    }
    return stats


__all__ = [
    "CALIBRATION_BUCKETS",
    "CalibrationBucket",
    "GroupStat",
    "PredictionStats",
    "compute_prediction_stats",
]
