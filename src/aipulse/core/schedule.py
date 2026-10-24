"""触发调度（T9）：trigger_mode 三态 + 间隔推导。

**与 `budget.degrade_order` 的分界**（文档统一口径）：
`trigger_mode` 管**准入门**（这个阶段要不要自动跑），`degrade_order` 管**退出序**
（钱不够时先砍谁）——前者是计划，后者是预算。两者回答不同问题，
即使 `trend.trigger_mode=manual`，预算超支时 degrade 顺序里仍可能出现 `trend`
（只是当月它本来就没跑；实现上 degrade 只对"本期确实要跑"的阶段生效）。

间隔语义：`interval` **既是触发间隔，也是分析范围**。月度触发时分析的就是
整个自然月，不是"触发时看最近 N 天"——所以 `window_days` 不需要独立配置。
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

__all__ = [
    "DEFAULT_INTERVAL",
    "DEFAULT_MIN_CONTROVERSY",
    "DEFAULT_TRIGGER_MODE",
    "TRIGGER_MODES",
    "Interval",
    "describe_interval",
    "month_bounds",
    "parse_interval",
    "previous_month_bounds",
    "window_for",
]

# ── 三态 ────────────────────────────────────────────────────────────────
# auto    ：到点自动跑（interval 决定范围）
# manual  ：命令可用，但不自动跑（必须显式给 --range / --topic）
# disabled：该阶段整体退出自动流程
# ★ 不能用 off/hybrid/full——那是 LLM 三档（core/config.py 的 AIPULSE_MODE）
TRIGGER_AUTO = "auto"
TRIGGER_MANUAL = "manual"
TRIGGER_DISABLED = "disabled"
TRIGGER_MODES = (TRIGGER_AUTO, TRIGGER_MANUAL, TRIGGER_DISABLED)

DEFAULT_TRIGGER_MODE = TRIGGER_AUTO
DEFAULT_INTERVAL = "1m"  # 日历月
DEFAULT_MIN_CONTROVERSY = 6


@dataclass(frozen=True)
class Interval:
    """解析后的间隔：`1m`=日历月，`7d`/`30d`=滚动天数。"""

    kind: str  # "month" | "days"
    count: int

    @property
    def is_month(self) -> bool:
        return self.kind == "month"


_INTERVAL_RE = re.compile(r"^(?P<count>\d+)\s*(?P<unit>m|month|months|d|day|days)$", re.IGNORECASE)


def parse_interval(spec: str) -> Interval:
    """`1m` / `1month` / `7d` / `30d` → Interval；无法识别时按日历月。"""
    text = (spec or "").strip().lower()
    match = _INTERVAL_RE.match(text)
    if match is None:
        return Interval(kind="month", count=1)
    count = max(int(match.group("count")), 1)
    unit = match.group("unit")
    return Interval(kind="month" if unit.startswith("m") else "days", count=count)


def describe_interval(spec: str) -> str:
    """给人看的一句话：`1m` → 「日历月」、`7d` → 「7 天」。"""
    interval = parse_interval(spec)
    if interval.is_month:
        return "日历月" if interval.count == 1 else f"{interval.count} 个自然月"
    return f"{interval.count} 天"


# ── 日历月 ──────────────────────────────────────────────────────────────


def month_bounds(day: date) -> tuple[date, date]:
    """`day` 所在自然月的 (首日, 末日)。"""
    start = day.replace(day=1)
    last = calendar.monthrange(day.year, day.month)[1]
    return start, start.replace(day=last)


def previous_month_bounds(day: date) -> tuple[date, date]:
    """`day` 的上一个完整自然月的 (首日, 末日)。"""
    first = day.replace(day=1)
    prev_last = first - timedelta(days=1)
    start, _ = month_bounds(prev_last)
    return start, prev_last


def window_for(interval: Interval, today: date, *, complete_only: bool = True) -> tuple[date, date]:
    """按间隔推导**分析窗口**（不是"最近 N 天"）。

    - `1m` + complete_only → 上一个完整自然月（11-01 跑 → 10-01→10-31）
    - `1m` + complete_only=False → 本月至今
    - `Nd` → 截止到 `today`（含）的最近 N 天

    数据不足不在这里判——由调用方拿着窗口去比对实际有数据的日期。
    """
    if interval.is_month:
        if complete_only:
            return previous_month_bounds(today)
        start, end = month_bounds(today)
        return start, today
    end = today
    return end - timedelta(days=interval.count - 1), end
