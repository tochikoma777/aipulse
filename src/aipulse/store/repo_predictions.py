"""预言仓库层（设计方案 §7.5）。

- `prediction_id`：稳定 id——同一天 + 同一 statement + 同 origin 的预言复用同一行，
  让"重复跑 `aipulse predict`"天然幂等，不会每天刷出重复预言。
- `insert_predictions`：批量写入，已存在的 id 跳过（不覆盖人工已 review 的记录）。
- `list_predictions`：按状态 / 来源 / 日期过滤。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlmodel import Session, select

from aipulse.core.hashing import short_hash
from aipulse.store.models import Prediction

_PREFIX = "pred_"


def prediction_id(day: date, statement: str, origin: str) -> str:
    """稳定预言 id。"""
    return _PREFIX + short_hash(f"{day.isoformat()}:{statement}:{origin}", length=12)


def insert_predictions(session: Session, predictions: Sequence[Prediction]) -> int:
    """批量写入。返回实际新增条数（已存在的 id 跳过）。"""
    inserted = 0
    for pred in predictions:
        if session.get(Prediction, pred.id) is not None:
            continue
        session.add(pred)
        inserted += 1
    session.commit()
    return inserted


def list_predictions(
    session: Session,
    *,
    status: str | None = None,
    origin: str | None = None,
    day: date | None = None,
) -> list[Prediction]:
    """按条件列出预言（按 date 倒序、statement 顺序稳定）。"""
    stmt = select(Prediction)
    if status is not None:
        stmt = stmt.where(Prediction.status == status)
    if origin is not None:
        stmt = stmt.where(Prediction.origin == origin)
    if day is not None:
        stmt = stmt.where(Prediction.date == day)
    stmt = stmt.order_by(Prediction.date.desc(), Prediction.statement)  # type: ignore[attr-defined]
    return list(session.exec(stmt).all())


__all__ = ["insert_predictions", "list_predictions", "prediction_id"]
