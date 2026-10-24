"""LLM 每日预算护栏（设计方案 §8.4）。

按 `llm_usage` 表汇总当日已花费，超限时按 `budget.degrade_order` 自动降级：
关闭 debate → 关闭 trend → 简报只保留 Top N → 只采集不做 LLM。

**降级语义（v1.22 P0-2 修正）**：`degrade_order` 是"牺牲顺序"，每超支
**一个 `daily_limit_cny` 的额度**推进一级：

- 超支 0 ~ 1 倍 → 关 debate（其余照跑）
- 超支 1 ~ 2 倍 → 再关 trend
- 超支 2 ~ 3 倍 → 再关 brief（`brief_topn`，匹配 `brief_*` 全部 purpose）
- 超支 ≥ 3 倍 或 到达 `all` → 全部关闭

这样做的理由：单日预算是"软上限 + 硬止损"——超几毛钱不该让整条日报停摆，
但不能无上限地烧。旧实现只会在超支后对**所有** purpose 抛错，等于让配置项失效。
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, date, datetime

from sqlalchemy import Engine, func
from sqlmodel import Session, select

from aipulse.core.timeutil import utcnow
from aipulse.store.models import LLMUsage

# 配置里的功能名 → 实际 purpose 前缀。配置写 `brief_topn`，代码里是
# `brief_daily` / `brief_item_comment` / `brief_item_enhance`，必须按前缀匹配。
_PURPOSE_PREFIXES: dict[str, tuple[str, ...]] = {
    "debate": ("debate",),
    "trend": ("trend",),
    "brief_topn": ("brief",),
}


def _purpose_matches(purpose: str, feature: str) -> bool:
    prefixes = _PURPOSE_PREFIXES.get(feature, (feature,))
    return any(purpose.startswith(prefix) for prefix in prefixes)


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
        inactive_features: Collection[str] = (),
    ) -> None:
        self.engine = engine
        self.daily_limit_cny = daily_limit_cny
        self.price_fast = price_fast_cny_per_1m
        self.price_strong = price_strong_cny_per_1m
        self.degrade_order = degrade_order or ["debate", "trend", "brief_topn", "all"]
        # ★ 红线 63：degrade 只对「本期确实要跑」（trigger_mode=auto）的阶段生效，
        #   否则会出现「降级了一个没在跑的东西」的假动作。inactive 里的名字
        #   即使进了 degrade_order 也不计入"被降级"清单。
        self.inactive_features = frozenset(inactive_features)
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
        # ★ 只取库里的总额：`record()` 已经把本次会话的花费写进 llm_usage 了，
        #   再叠加 session_cost 会把每一笔算两遍（实测 0.5 元记成 1.0 元），
        #   预算会提前一倍触发、降级级数也随之翻倍。
        return float(total)

    def remaining(self) -> float:
        return self.daily_limit_cny - self.spent_today()

    def estimate_cost(
        self, *, model_tier: str, prompt_tokens: int, completion_tokens: int
    ) -> float:
        price = self.price_strong if model_tier == "strong" else self.price_fast
        return (prompt_tokens + completion_tokens) * price / 1_000_000

    def degrade_stage(self) -> int:
        """当前降级级数：0 = 未超支；每超一个日额度多升一级；封顶 = 顺序长度。"""
        overage = self.spent_today() - self.daily_limit_cny
        if overage <= 0:
            return 0
        if self.daily_limit_cny <= 0:
            return len(self.degrade_order)
        # 超支 0~1 倍 → 1 级；1~2 倍 → 2 级；……
        steps = 1 + int(overage // self.daily_limit_cny)
        return min(steps, len(self.degrade_order))

    def disabled_features(self) -> list[str]:
        """当前被关闭的功能名（按 degrade_order 顺序取前缀）。

        只报「本期确实要跑」的：`inactive_features`（trigger_mode != auto）里的名字
        即使进了降级顺序，也不算"被降级"——它本来就没在跑。
        """
        closed = self.degrade_order[: self.degrade_stage()]
        return [f for f in closed if f not in self.inactive_features]

    def is_enabled(self, purpose: str) -> bool:
        """该 purpose 在当前降级级数下是否允许调用。"""
        for feature in self.disabled_features():
            if feature == "all":
                return False
            if _purpose_matches(purpose, feature):
                return False
        return True

    def can_afford(self, purpose: str, est_cost: float = 0.0) -> bool:
        """是否还能发起这次调用。

        第 0 级（未超支）沿用硬额度：剩余不够就 False。
        进入降级后，被关掉的 purpose 直接 False；**未被关掉的仍放行**——
        这是有意的"软上限"：超支不到下一级时，日报/预言不该因为几毛钱停摆，
        但每超一个额度就会再关掉一档，直到 `all` 硬止损。
        """
        if not self.is_enabled(purpose):
            return False
        if self.degrade_stage() == 0:
            return self.remaining() >= est_cost
        return True

    def record(
        self,
        *,
        purpose: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        model_tier: str = "fast",
        cache_hit: bool = False,
        error: str | None = None,
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
                    error=error,
                )
            )
            session.commit()


__all__ = ["BudgetTracker"]
