"""预言仓库层（设计方案 §7.5）。

- `prediction_id`：稳定 id——同一天 + 同一 statement + 同 origin 的预言复用同一行，
  让"重复跑 `aipulse predict`"天然幂等，不会每天刷出重复预言。
- `insert_predictions`：批量写入，已存在的 id 跳过（不覆盖人工已 review 的记录）。
- `list_predictions`：按状态 / 来源 / 日期过滤。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, cast

from sqlmodel import Session, select

from aipulse.core.hashing import short_hash
from aipulse.core.timeutil import utcnow
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


def list_pending_due(session: Session, today: date) -> list[Prediction]:
    """到期待验证队列：`status=pending AND due_date <= today`（设计方案 §10.2.2 步骤 1）。"""
    stmt = (
        select(Prediction)
        .where(Prediction.status == "pending", Prediction.due_date <= today)
        .order_by(Prediction.due_date.asc(), Prediction.statement)  # type: ignore[attr-defined]
    )
    return list(session.exec(stmt).all())


def list_verified_since(session: Session, since: datetime) -> list[Prediction]:
    """取本次运行以来产生判定结果的预言（`verdicts.md` 用，§11.1）。"""
    # verified_at 可空，类属性注解是 `datetime | None`，mypy 下无法直接用列方法
    verified_at = cast(Any, Prediction.verified_at)
    stmt = (
        select(Prediction)
        .where(verified_at.is_not(None), verified_at >= since)
        .order_by(verified_at.asc())
    )
    return list(session.exec(stmt).all())


def save_verdict(
    session: Session,
    prediction: Prediction,
    *,
    status: str,
    verdict: str | None,
    verdict_score: float | None,
    note: str,
    evidence_ids: Sequence[str] | None,
    verified_by: str,
) -> Prediction:
    """写入判定结果并提交。

    - `status`：`verified`（有 verdict）或 `unverifiable`（无 verdict）。
    - `verified_by`：`auto`（验证器）/ `human`（人工 review 覆盖）。
    """
    prediction.status = status
    prediction.verdict = verdict
    prediction.verdict_score = verdict_score
    prediction.verdict_note = note
    prediction.verdict_evidence_ids = list(evidence_ids) if evidence_ids is not None else None
    prediction.verified_at = utcnow()
    prediction.verified_by = verified_by
    session.add(prediction)
    session.commit()
    return prediction


__all__ = [
    "insert_predictions",
    "list_pending_due",
    "list_predictions",
    "list_verified_since",
    "prediction_id",
    "save_verdict",
]
