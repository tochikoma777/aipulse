"""Web 看板的只读数据层（设计方案 §11.1 / §14：数据来自 SQLite 与 daily.json）。

**红线 22：Web 页面严禁任何写操作。** 这里不是"约定不写"，而是物理上写不进去：

- SQLite 用 `mode=ro` URI 打开（`sqlite:///file:...?mode=ro&uri=true`）——任何 INSERT/UPDATE
  会直接抛 `attempt to write a readonly database`；
- 数据库文件不存在时**不创建**，页面走优雅空态；
- 报告只读 `data/reports/YYYY/MM/DD/*.json`，从不写入。

因此 `serve` 与 `daily` 可以并存：看板永远不可能污染流水线的数据。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, or_
from sqlmodel import Session, select

from aipulse.analysis.stats import PredictionStats, compute_prediction_stats
from aipulse.core.logging import get_logger
from aipulse.core.timeutil import DEFAULT_TZ, day_window, today_local
from aipulse.store.models import Entity, Item, Prediction, Topic

log = get_logger(__name__)

ITEM_LIMIT = 200  # 单页条目上限：看板只做"看"，不做全量导出
SEARCH_LIMIT = 100


def _readonly_url(db_path: Path) -> str:
    """只读 SQLite URL（`uri=true` 与 `mode=ro` 缺一不可）。"""
    return f"sqlite:///file:{db_path.as_posix()}?mode=ro&uri=true"


def _item_dict(item: Item) -> dict[str, Any]:
    return {
        "id": item.id,
        "source": item.source,
        "title": item.title or "(无标题)",
        "url": item.url,
        "summary": item.summary,
        "hot_score": round(float(item.hot_score or 0.0), 1),
        "seen_in": item.seen_in or [item.source],
        "topic_id": item.topic_id,
        "published_at": item.published_at.isoformat() if item.published_at else "",
    }


class ReadOnlyStore:
    """SQLite 只读视图。库不存在时所有查询返回空，页面走空态。"""

    def __init__(self, db_path: str | Path, *, tz_name: str = DEFAULT_TZ) -> None:
        self.db_path = Path(db_path)
        self.tz_name = tz_name
        self._engine: Engine | None = None

    @property
    def available(self) -> bool:
        return self.db_path.exists()

    def _get_engine(self) -> Engine | None:
        if not self.available:
            return None
        if self._engine is None:
            self._engine = create_engine(
                _readonly_url(self.db_path),
                connect_args={"check_same_thread": False},
            )
        return self._engine

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def _session(self) -> Session | None:
        engine = self._get_engine()
        return None if engine is None else Session(engine, expire_on_commit=False)

    # ── 条目 / 主题 / 实体 ──────────────────────────────────────────

    def items_for_day(self, day: date, *, limit: int = ITEM_LIMIT) -> list[dict[str, Any]]:
        """某本地日采集到的条目（按热度倒序）。"""
        session = self._session()
        if session is None:
            return []
        try:
            start, end = day_window(day, self.tz_name)
            stmt = (
                select(Item)
                .where(Item.collected_at >= start, Item.collected_at < end)
                .order_by(Item.hot_score.desc())  # type: ignore[attr-defined]
                .limit(limit)
            )
            return [_item_dict(row) for row in session.exec(stmt).all()]
        finally:
            session.close()

    def topics_for_day(self, day: date, *, limit: int = 40) -> list[dict[str, Any]]:
        session = self._session()
        if session is None:
            return []
        try:
            stmt = (
                select(Topic)
                .where(Topic.date == day)
                .order_by(Topic.item_count.desc())  # type: ignore[attr-defined]
                .limit(limit)
            )
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "keywords": row.keywords or [],
                    "item_count": row.item_count,
                    "avg_hot_score": round(float(row.avg_hot_score or 0.0), 1),
                    "summary": row.summary,
                    "date": row.date.isoformat(),
                }
                for row in session.exec(stmt).all()
            ]
        finally:
            session.close()

    def topic_history(self, *, days: int = 14, limit: int = 40) -> list[dict[str, Any]]:
        """主题跨日演化：同名主题在最近 N 天各出现几次（"热了几天"比单日热点更有信息量）。"""
        session = self._session()
        if session is None:
            return []
        try:
            rows = session.exec(
                select(Topic).order_by(Topic.date.desc()).limit(2000)  # type: ignore[attr-defined]
            ).all()
            by_name: dict[str, dict[str, Any]] = {}
            for row in rows:
                entry = by_name.setdefault(
                    row.name, {"name": row.name, "days": {}, "total": 0, "keywords": row.keywords}
                )
                entry["days"][row.date.isoformat()] = row.item_count
                entry["total"] += row.item_count
            ranked = sorted(
                by_name.values(),
                key=lambda e: (len(e["days"]), e["total"]),
                reverse=True,
            )[:limit]
            for entry in ranked:
                entry["day_count"] = len(entry["days"])
                marks = []
                for offset in range(days - 1, -1, -1):
                    count = entry["days"].get(_days_ago(offset, self.tz_name), 0)
                    marks.append("█" if count >= 3 else "▄" if count > 0 else "·")
                entry["spark"] = "".join(marks)
            return ranked
        finally:
            session.close()

    def entities_for_day(self, day: date, *, limit: int = 30) -> list[dict[str, Any]]:
        session = self._session()
        if session is None:
            return []
        try:
            rows = session.exec(select(Entity).where(Entity.date == day)).all()
            counts: dict[tuple[str, str], float] = {}
            for row in rows:
                key = (row.name, row.type)
                counts[key] = counts.get(key, 0.0) + float(row.weight or 1.0)
            ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
            return [
                {"name": name, "type": kind, "mentions": round(weight, 1)}
                for (name, kind), weight in ranked
            ]
        finally:
            session.close()

    def search_items(self, query: str, *, limit: int = SEARCH_LIMIT) -> list[dict[str, Any]]:
        """标题 / 摘要关键词检索（只读 LIKE，不建索引也不改库结构）。"""
        term = query.strip()
        if not term:
            return []
        session = self._session()
        if session is None:
            return []
        try:
            pattern = f"%{term}%"
            stmt = (
                select(Item)
                .where(or_(Item.title.like(pattern), Item.summary.like(pattern)))  # type: ignore[attr-defined]
                .order_by(Item.collected_at.desc())  # type: ignore[attr-defined]
                .limit(limit)
            )
            return [_item_dict(row) for row in session.exec(stmt).all()]
        finally:
            session.close()

    def recent_items(self, *, limit: int = ITEM_LIMIT) -> list[dict[str, Any]]:
        """最近采集的条目（首页在报告缺失时的兜底视图）。"""
        session = self._session()
        if session is None:
            return []
        try:
            stmt = select(Item).order_by(Item.collected_at.desc()).limit(limit)  # type: ignore[attr-defined]
            return [_item_dict(row) for row in session.exec(stmt).all()]
        finally:
            session.close()

    # ── 预言与统计（★ 门面）────────────────────────────────────────

    def predictions(self, *, status: str | None = None) -> list[Prediction]:
        session = self._session()
        if session is None:
            return []
        try:
            stmt = select(Prediction)
            if status is not None:
                stmt = stmt.where(Prediction.status == status)
            stmt = stmt.order_by(Prediction.date.desc(), Prediction.statement)  # type: ignore[attr-defined]
            return list(session.exec(stmt).all())
        finally:
            session.close()

    def prediction_stats(self) -> PredictionStats:
        return compute_prediction_stats(self.predictions())

    def runtime_days(self) -> int:
        """系统已运行天数：最早一条数据的日期到今天（本地时区）。"""
        session = self._session()
        if session is None:
            return 0
        try:
            earliest = self._earliest_day(session)
            if earliest is None:
                return 0
            return max(0, (today_local(self.tz_name) - earliest).days)
        finally:
            session.close()

    @staticmethod
    def _earliest_day(session: Session) -> date | None:
        """最早的数据日期（预言 → 实体 → 条目，取第一个有值的）。"""
        predictions = session.exec(
            select(Prediction).order_by(Prediction.date.asc()).limit(1)  # type: ignore[attr-defined]
        ).all()
        if predictions:
            return predictions[0].date
        entities = session.exec(
            select(Entity).order_by(Entity.date.asc()).limit(1)  # type: ignore[attr-defined]
        ).all()
        if entities:
            return entities[0].date
        items = session.exec(
            select(Item).order_by(Item.collected_at.asc()).limit(1)  # type: ignore[attr-defined]
        ).all()
        collected = items[0].collected_at if items else None
        return collected.date() if collected is not None else None

    def first_due_date(self) -> date | None:
        """最早的待验证到期日（0 样本空态要告诉用户"首批预言将于 X 日到期"）。"""
        session = self._session()
        if session is None:
            return None
        try:
            stmt = (
                select(Prediction)
                .where(Prediction.status == "pending")
                .order_by(Prediction.due_date.asc())  # type: ignore[attr-defined]
                .limit(1)
            )
            rows = session.exec(stmt).all()
            return rows[0].due_date if rows else None
        finally:
            session.close()


def _days_ago(offset: int, tz_name: str = DEFAULT_TZ) -> str:
    """最近第 offset 天（0 = 今天）的 ISO 日期串。"""
    return (today_local(tz_name) - timedelta(days=offset)).isoformat()


class ReportIndex:
    """`data/reports/YYYY/MM/DD/` 的只读索引（报告即数据库，§14.1）。"""

    def __init__(self, reports_dir: str | Path) -> None:
        self.reports_dir = Path(reports_dir)

    def days(self) -> list[str]:
        """已产出的报告日期（倒序，ISO 串）。"""
        if not self.reports_dir.exists():
            return []
        out: list[str] = []
        for path in self.reports_dir.glob("*/*/*/daily.json"):
            parts = path.parts[-4:-1]
            if len(parts) == 3:
                out.append(f"{parts[0]}-{parts[1]}-{parts[2]}")
        return sorted(out, reverse=True)

    def latest(self) -> str | None:
        days = self.days()
        return days[0] if days else None

    def dir_for(self, day: str) -> Path:
        year, month, day_part = day.split("-")
        return self.reports_dir / year / month / day_part

    def load_json(self, day: str, filename: str) -> dict[str, Any] | None:
        path = self.dir_for(day) / filename
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("web.report.unreadable", path=str(path), error=repr(exc))
            return None
        return data if isinstance(data, dict) else None

    def load_daily(self, day: str) -> dict[str, Any] | None:
        return self.load_json(day, "daily.json")

    def load_meta(self, day: str) -> dict[str, Any]:
        return self.load_json(day, "meta.json") or {}

    def load_signals(self, day: str) -> dict[str, Any]:
        return self.load_json(day, "signals.json") or {}

    def load_markdown(self, day: str, filename: str) -> str:
        path = self.dir_for(day) / filename
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover - 权限/编码异常
            log.warning("web.report.unreadable", path=str(path), error=repr(exc))
            return ""


__all__ = ["ITEM_LIMIT", "SEARCH_LIMIT", "ReadOnlyStore", "ReportIndex"]
