"""指标增速计算（设计方案 §7.2 / §9.1）。

`signals` 表是计算"真在涨"（velocity）的唯一可靠来源：对同一实体取两次快照，
`Δmetric / Δhours` 即为增速。无历史（<2 个快照）时返回 None，由打分层做中位数兜底。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlmodel import Session

from aipulse.core.timeutil import DEFAULT_TZ, to_local, today_local
from aipulse.store.models import Item, Signal
from aipulse.store.repo_items import signals_for_entity

# 两次快照的最小间隔（小时）：不足则不给增速（`insufficient`）。
# 真实阈值走 `configs/default.yaml::signals.min_velocity_window_hours`，
# 这里只是直接调用本模块时的兜底默认值（保持纯函数可测）。
MIN_VELOCITY_WINDOW_HOURS = 6.0

# 只看最近 N 天的快照。用全表首末会把"多天前的老快照"混进来，
# 让"今天的增量"变成"近一周的增量"（§5.14 任务 1 的明确要求）。
REPO_LOOKBACK_DAYS = 7.0

# 各源可算增速的 (entity_type, metric) 映射；不在表内的源（arxiv/rss/inbox）无信号。
_SOURCE_SIGNAL = {
    "github_trending": ("repo", "stars"),
    "hackernews": ("hn_story", "points"),
    "hf_papers": ("paper", "upvotes"),
}


def item_signal_key(item: Item) -> tuple[str, str, str] | None:
    """由条目推断其在 signals 表中的 (entity_type, entity_key, metric)。"""
    mapping = _SOURCE_SIGNAL.get(item.source)
    if mapping is None:
        return None
    entity_type, metric = mapping
    # 论文类实体以 arXiv 编号为 key；repo 以 full_name；hn 以 objectID（均 == external_id）
    entity_key = item.external_id or item.cross_key or ""
    if not entity_key:
        return None
    return entity_type, entity_key, metric


def velocity_per_hour(signals: list[Signal]) -> float | None:
    """由快照序列算 `Δvalue / Δhours`；少于 2 个快照或时间无进展返回 None。"""
    if len(signals) < 2:
        return None
    first, last = signals[0], signals[-1]
    hours = (last.ts - first.ts).total_seconds() / 3600.0
    if hours <= 0:
        return None
    return (last.value - first.value) / hours


def velocity_for_item(session: Session, item: Item) -> float | None:
    """计算单条目的增速；无信号或历史不足返回 None（调用方做冷启动兜底）。"""
    key = item_signal_key(item)
    if key is None:
        return None
    entity_type, entity_key, metric = key
    return velocity_per_hour(signals_for_entity(session, entity_type, entity_key, metric))


def trending_streak_days(
    session: Session,
    item: Item,
    *,
    anchor: date | None = None,
    tz_name: str = DEFAULT_TZ,
) -> int:
    """「连续在榜 N 天」：按 signals 快照的本地日期倒推连续天数。

    只看状态型 repo 信号（`github_trending` → `repo/stars`）。`anchor` 默认今天；
    最新快照必须正好落在 anchor，否则返回 0（说明今天已掉榜/未采到）。
    同一自然日多次运行只算一天，符合"连续在榜"的直觉。
    """
    key = item_signal_key(item)
    if key is None or key[0] != "repo":
        return 0
    rows = signals_for_entity(session, *key)
    if not rows:
        return 0
    days = sorted({to_local(row.ts, tz_name).date() for row in rows})
    end = anchor or today_local(tz_name)
    if days[-1] < end:
        return 0
    streak = 0
    expected = end
    for day in reversed(days):
        if day == expected:
            streak += 1
            expected -= timedelta(days=1)
        elif day < expected:
            break
    return streak


@dataclass
class SignalSeries:
    """某实体-指标的快照序列摘要（首个 vs 最新，即增速的原料）。"""

    entity_type: str
    entity_key: str
    metric: str
    points: int
    first_ts: datetime
    last_ts: datetime
    first_value: float
    last_value: float
    min_window_hours: float = MIN_VELOCITY_WINDOW_HOURS

    @property
    def delta(self) -> float:
        return self.last_value - self.first_value

    @property
    def hours(self) -> float:
        return (self.last_ts - self.first_ts).total_seconds() / 3600.0

    @property
    def status(self) -> str:
        """`ok` 可算增速 / `cold_start` 少于 2 个快照 / `insufficient` 间隔不足。"""
        if self.points < 2:
            return "cold_start"
        if self.hours < self.min_window_hours:
            return "insufficient"
        return "ok"

    @property
    def velocity_per_hour(self) -> float | None:
        """`Δvalue / Δhours`；`status != ok` 时一律为 None（宁缺毋滥）。"""
        if self.status != "ok":
            return None
        return self.delta / self.hours

    def to_dict(self) -> dict[str, Any]:
        velocity = self.velocity_per_hour
        return {
            "entity_type": self.entity_type,
            "entity_key": self.entity_key,
            "metric": self.metric,
            "points": self.points,
            "status": self.status,
            "first_ts": self.first_ts.isoformat(),
            "last_ts": self.last_ts.isoformat(),
            "first_value": self.first_value,
            "last_value": self.last_value,
            "delta": self.delta,
            "hours": round(self.hours, 4),
            "velocity_per_hour": None if velocity is None else round(velocity, 6),
            "velocity_24h": None if velocity is None else round(velocity * 24.0, 4),
        }


def _series_from(rows: Sequence[Signal], *, min_window_hours: float) -> SignalSeries:
    first, last = rows[0], rows[-1]
    return SignalSeries(
        entity_type=first.entity_type,
        entity_key=first.entity_key,
        metric=first.metric,
        points=len(rows),
        first_ts=first.ts,
        last_ts=last.ts,
        first_value=float(first.value),
        last_value=float(last.value),
        min_window_hours=min_window_hours,
    )


def build_signals_summary(
    rows: Sequence[Signal], *, min_window_hours: float = MIN_VELOCITY_WINDOW_HOURS
) -> dict[str, Any]:
    """把 signals 快照聚合成「每实体一条序列摘要」，含绝对增量与增速。

    **增速口径**：两次快照间隔必须 ≥ `min_window_hours`，否则标 `insufficient` 不给数字
    （同一小时内连跑会把 Δ/hour 放大成荒谬的"日增"，那比没有数据更伤可信度）。

    **为什么按全量历史（而非当日窗口）聚合**：增速的定义是"两次快照之差 / 时间差"，
    只取当天一个点永远算不出增速。聚合全量历史后，连续跑两天即可得到 star 增速——
    这正是 M4 DoD"证明 Actions 内 SQLite 恢复机制生效"的判定依据。

    产出随报告 commit 回仓库，因此即使某天 SQLite 恢复失败，历史 signals.json
    仍能追溯增速，不依赖任何持久化存储。
    """
    grouped: dict[tuple[str, str, str], list[Signal]] = {}
    for row in rows:
        grouped.setdefault((row.entity_type, row.entity_key, row.metric), []).append(row)

    series = [
        _series_from(sorted(points, key=lambda s: s.ts), min_window_hours=min_window_hours)
        for points in grouped.values()
    ]
    # 有增速的排前面（增速降序），冷启动（单点）的按实体名排在后面稳定输出
    series.sort(
        key=lambda s: (
            s.velocity_per_hour is None,
            -(s.velocity_per_hour or 0.0),
            s.entity_type,
            s.entity_key,
        )
    )

    by_type: dict[str, dict[str, int]] = {}
    for entry in series:
        slot = by_type.setdefault(entry.entity_type, {"entities": 0, "points": 0})
        slot["entities"] += 1
        slot["points"] += entry.points

    return {
        "point_count": len(rows),
        "entity_count": len(series),
        "with_velocity": sum(1 for s in series if s.status == "ok"),
        "insufficient": sum(1 for s in series if s.status == "insufficient"),
        "cold_start": sum(1 for s in series if s.status == "cold_start"),
        "min_window_hours": min_window_hours,
        "by_type": by_type,
        "series": [s.to_dict() for s in series],
    }


@dataclass(frozen=True)
class RepoStar:
    """单个 repo 的 star 快照摘要：最新总数 + 窗口内的**绝对增量**与窗口长度。

    `delta` 是绝对增量（主显示值）；`delta_per_day` 只用于**排序**，不对外显示——
    不同项目的窗口长度不同（REA 10h、ghidra 7 天），按绝对增量排名不可比。
    """

    entity_key: str
    total: float | None
    delta: float | None
    status: str  # ok / insufficient / cold_start / missing
    last_ts: datetime | None = None
    first_ts: datetime | None = None
    hours: float | None = None

    @property
    def delta_per_day(self) -> float | None:
        """日均增量 = `delta / hours * 24`，仅用于排序。"""
        if self.delta is None or self.hours is None or self.hours <= 0:
            return None
        return self.delta / self.hours * 24.0


def repo_star_snapshots(
    rows: Sequence[Signal],
    *,
    min_window_hours: float = MIN_VELOCITY_WINDOW_HOURS,
    lookback_days: float = REPO_LOOKBACK_DAYS,
) -> dict[str, RepoStar]:
    """按 repo 聚合 star 快照：`{owner/repo: RepoStar}`。

    取值规则（§5.14）：
    - 先把序列裁到 `lookback_days` 内（**不用全表首末**，否则多天前的老数据会混进来），
      再取该窗口的**首末两个快照**算绝对增量；锚点用数据里最新的快照时刻而不是
      `utcnow()`，历史报告与测试因此可复现，掉榜项目也仍能出现；
    - 只有 1 个快照 → `cold_start`（总数有、增量 `—`）；
    - 间隔 < `min_window_hours` → `insufficient`：**仍给绝对增量**，只是不参与增速榜。

    **为什么不用"最近两次"**：一轮开发/重跑会在 2 小时内留下多个快照，
    拿最近两次会把"2 小时涨 132 star"当成日报增量；而且 `signals.json` 用的是
    窗口首末，两处口径不一致会让读者对不上数。窗口首末 = 该项目被持续追踪以来的增长。
    """
    repo_rows = [row for row in rows if row.entity_type == "repo" and row.metric == "stars"]
    if not repo_rows:
        return {}
    anchor = max(row.ts for row in repo_rows)
    cutoff = anchor - timedelta(days=lookback_days)

    grouped: dict[str, list[Signal]] = {}
    for row in repo_rows:
        if row.ts < cutoff:
            continue
        grouped.setdefault(row.entity_key, []).append(row)

    result: dict[str, RepoStar] = {}
    for key, points in grouped.items():
        points.sort(key=lambda row: row.ts)
        first, last = points[0], points[-1]
        total = float(last.value)
        if len(points) < 2:
            result[key] = RepoStar(key, total, None, "cold_start", last.ts)
            continue
        hours = (last.ts - first.ts).total_seconds() / 3600.0
        delta = float(last.value) - float(first.value)
        # hours <= 0 说明时间戳相同（调试/并发写入），同样不给"合规窗口"
        status = "ok" if hours >= min_window_hours else "insufficient"
        result[key] = RepoStar(key, total, delta, status, last.ts, first.ts, hours)
    return result


def velocity_board(
    snapshots: Mapping[str, RepoStar],
    *,
    exclude: Iterable[str] = (),
    top_n: int = 5,
) -> list[RepoStar]:
    """增速榜：按**日均增量**降序取 Top N。

    为什么不是绝对增量：各项目的窗口长度不同（REA 10h、ghidra 可能 7 天），
    "7 天涨 5000" 会排在 "1 天涨 3000" 前面，但后者快 7 倍。
    日均只用于排序；对外仍显示绝对增量 + 窗口（如 `+8617 / 10h`）。

    只纳入 `status == "ok"`（有合规速率窗口）且增量 > 0 的项目——
    `insufficient` 是"几分钟内涨了几个 star"，放进榜会制造假热点。
    调用方负责把"今日 trending 已展示"的项目放进 `exclude`，避免重复。
    """
    excluded = set(exclude)
    ranked = [
        star
        for star in snapshots.values()
        if star.status == "ok"
        and star.delta is not None
        and star.delta > 0
        and star.entity_key not in excluded
    ]
    # 日均降序；日均相同再按绝对增量、最后按 key，保证输出稳定
    ranked.sort(
        key=lambda star: (
            -(star.delta_per_day or 0.0),
            -(star.delta or 0.0),
            star.entity_key,
        )
    )
    return ranked[: max(0, top_n)]


__all__ = [
    "MIN_VELOCITY_WINDOW_HOURS",
    "REPO_LOOKBACK_DAYS",
    "RepoStar",
    "SignalSeries",
    "build_signals_summary",
    "item_signal_key",
    "repo_star_snapshots",
    "trending_streak_days",
    "velocity_board",
    "velocity_for_item",
    "velocity_per_hour",
]
