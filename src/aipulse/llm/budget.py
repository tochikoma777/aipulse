"""LLM 每日预算护栏（设计方案 §8.4）。

按 `llm_usage` 表汇总当日已花费，超限时按 `budget.degrade_order` 自动降级：
关闭 debate → 关闭 trend → 简报只保留 Top N → 只采集不做 LLM。
每次降级写日志，并体现在报告 meta.json（由 reasoning/brief.py 收集）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import Engine, func
from sqlmodel import Session, select

from aipulse.core.timeutil import utcnow
from aipulse.store.models import LLMUsage


class BudgetTracker:
    """预算跟踪：统计当日花费、估算成本、判定某 purpose 是否可执行。"""

    def __init__(
        self,
        engine: Engine | None,
        *,
        daily_limit_cny: float = 2.0,
        price_fast_cny_per_1m: float = 1.0,
        price_strong_cny_per_1m: float = 4.0,
        degrade_order: list[str] | None = None,
    ) -> None:
        self.engine = engine
        self.daily_limit_cny = daily_limit_cny
        self.price_fast = price_fast_cny_per_1m
        self.price_strong = price_strong_cny_per_1m
        self.degrade_order = degrade_order or ["debate", "trend", "brief_topn", "all"]
        # 运行期收集本次会话新增的花费（无 engine 时也能用，纯内存记账）
        self.session_cost = 0.0

    def _today(self) -> date:
        return utcnow().date()

    def spent_today(self) -> float:
        if self.engine is None:
            return self.session_cost
        today = self._today()
        with Session(self.engine) as session:
            total = session.exec(
                select(func.coalesce(func.sum(LLMUsage.cost_cny), 0.0)).where(
                    LLMUsage.ts >= datetime(today.year, today.month, today.day, tzinfo=UTC)
                )
            ).one()
        return float(total) + self.session_cost

    def remaining(self) -> float:
        return self.daily_limit_cny - self.spent_today()

    def estimate_cost(
        self, *, model_tier: str, prompt_tokens: int, completion_tokens: int
    ) -> float:
        price = self.price_strong if model_tier == "strong" else self.price_fast
        return (prompt_tokens + completion_tokens) * price / 1_000_000

    def can_afford(self, purpose: str, est_cost: float = 0.0) -> bool:
        """是否还能发起这次调用。超限一律 False（调用方据此降级）。"""
        return self.remaining() >= est_cost

    def record(
        self,
        *,
        purpose: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        model_tier: str = "fast",
        cache_hit: bool = False,
    ) -> None:
        cost = (
            0.0
            if cache_hit
            else self.estimate_cost(
                model_tier=model_tier,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )
        self.session_cost += cost
        if self.engine is None:
            return
        with Session(self.engine) as session:
            session.add(
                LLMUsage(
                    ts=utcnow(),
                    purpose=purpose,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_cny=cost,
                    cache_hit=cache_hit,
                )
            )
            session.commit()


__all__ = ["BudgetTracker"]
