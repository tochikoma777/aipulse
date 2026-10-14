"""热度打分（设计方案 §9.1，纯算法，零成本）。

hot_score = 100 * (
    w_engagement * engagement_norm      # 源内分位归一化
  + w_freshness  * freshness            # exp(-max(0, age-6)/36)
  + w_velocity   * velocity_norm        # Δmetric/Δhours，冷启动取中位数
  + w_source     * source_weight        # sources.yaml 静态权重
  + cross_bonus                          # 0.05 * (len(seen_in)-1)，多源印证加成
)

所有权重/阈值一律从 `configs/scoring.yaml` 读取，禁止硬编码；改配置即生效，无需改代码。
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping
from dataclasses import dataclass

from sqlmodel import Session

from aipulse.analysis.signals import velocity_for_item
from aipulse.core.config import load_scoring, load_sources
from aipulse.core.logging import get_logger
from aipulse.core.timeutil import age_hours, utcnow
from aipulse.store.models import Item

log = get_logger(__name__)


@dataclass(frozen=True)
class ScoringConfig:
    w_engagement: float
    w_freshness: float
    w_velocity: float
    w_source: float
    grace_hours: float
    tau_hours: float
    cross_source_bonus: float
    velocity_neutral: float
    title_only_weight: float
    engagement_coeffs: dict[str, dict[str, float]]


def load_scoring_config() -> ScoringConfig:
    raw = load_scoring()
    weights = raw.get("weights", {})
    freshness = raw.get("freshness", {})
    cold_start = raw.get("cold_start", {})
    return ScoringConfig(
        w_engagement=float(weights.get("engagement", 0.45)),
        w_freshness=float(weights.get("freshness", 0.20)),
        w_velocity=float(weights.get("velocity", 0.20)),
        w_source=float(weights.get("source_weight", 0.15)),
        grace_hours=float(freshness.get("grace_hours", 6)),
        tau_hours=float(freshness.get("tau_hours", 36)),
        cross_source_bonus=float(raw.get("cross_source_bonus", 0.05)),
        velocity_neutral=float(cold_start.get("velocity_neutral", 0.5)),
        title_only_weight=float(raw.get("title_only_weight", 0.35)),
        engagement_coeffs={
            str(k): {str(m): float(c) for m, c in v.items()}
            for k, v in raw.get("engagement", {}).items()
        },
    )


def engagement_raw(item: Item, cfg: ScoringConfig) -> float:
    """按源配置的指标系数算 engagement 原始分：Σ coeff * log1p(metric)。"""
    coeffs = cfg.engagement_coeffs.get(item.source, {})
    metrics = item.metrics or {}
    total = 0.0
    for metric, coeff in coeffs.items():
        value = metrics.get(metric)
        if value is None:
            continue
        try:
            total += coeff * math.log1p(float(value))
        except (TypeError, ValueError):
            continue
    return total


def percentile_rank(values: list[float]) -> list[float]:
    """平均秩分位归一化到 [0,1]（并列取平均秩）。单元素返回 [1.0]。"""
    n = len(values)
    if n == 1:
        return [1.0]
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return [r / (n - 1) for r in ranks]


def _normalize_group(values: list[float]) -> list[float]:
    """组内分位归一化；全为 0（无信号）时归一化为 0，避免无中生有的热度。"""
    if all(v == 0.0 for v in values):
        return [0.0] * len(values)
    return percentile_rank(values)


def _source_weight(item: Item, cfg: ScoringConfig) -> float:
    """条目所属源的静态权重；仅标题源（skip_cluster）降到最低档。"""
    if item.skip_cluster:
        return cfg.title_only_weight
    sources = load_sources().sources
    src_cfg = sources.get(item.source)
    return float(src_cfg.weight) if src_cfg is not None else 1.0


def compute_hot_scores(
    items: list[Item],
    velocities: Mapping[str, float | None],
    cfg: ScoringConfig | None = None,
) -> dict[str, float]:
    """纯函数：给定条目与各自 velocity（可为 None），算出 hot_score。可脱离 DB 单测。"""
    cfg = cfg or load_scoring_config()
    now = utcnow()

    # 按源分组做「源内归一化」（engagement 与 velocity 都不可跨源比较）
    groups: dict[str, list[Item]] = {}
    for item in items:
        groups.setdefault(item.source, []).append(item)

    eng_norm: dict[str, float] = {}
    vel_norm: dict[str, float] = {}

    for source, group in groups.items():
        eng_raw = [engagement_raw(it, cfg) for it in group]
        for item, norm in zip(group, _normalize_group(eng_raw), strict=True):
            eng_norm[item.id] = norm

        group_vel = [velocities.get(it.id) for it in group]
        computed = [v for v in group_vel if v is not None]
        if not computed:
            # 冷启动：该源一条 velocity 都算不出 → 中性值 + warning
            log.warning("score.cold_start", source=source, msg="无 signals 历史，velocity 取中性值")
            for item in group:
                vel_norm[item.id] = cfg.velocity_neutral
        else:
            norms = percentile_rank(computed)
            norm_by_value: dict[float, float] = {}
            for v, norm in zip(computed, norms, strict=True):
                norm_by_value[v] = norm
            median = statistics.median(norms)
            for item, vel in zip(group, group_vel, strict=True):
                vel_norm[item.id] = norm_by_value[vel] if vel is not None else median

    scores: dict[str, float] = {}
    for item in items:
        seen = item.seen_in or []
        cross_bonus = cfg.cross_source_bonus * max(0, len(seen) - 1)
        freshness = math.exp(
            -max(0.0, age_hours(item.published_at, now) - cfg.grace_hours) / cfg.tau_hours
        )
        score_01 = (
            cfg.w_engagement * eng_norm[item.id]
            + cfg.w_freshness * freshness
            + cfg.w_velocity * vel_norm[item.id]
            + cfg.w_source * _source_weight(item, cfg)
            + cross_bonus
        )
        scores[item.id] = max(0.0, min(100.0, 100.0 * score_01))
    return scores


def score_items(session: Session, items: list[Item]) -> dict[str, float]:
    """打分入口：算 velocity → 算 hot_score。返回 {item_id: hot_score}。"""
    velocities = {item.id: velocity_for_item(session, item) for item in items}
    return compute_hot_scores(items, velocities)


__all__ = [
    "ScoringConfig",
    "compute_hot_scores",
    "engagement_raw",
    "load_scoring_config",
    "percentile_rank",
    "score_items",
]
