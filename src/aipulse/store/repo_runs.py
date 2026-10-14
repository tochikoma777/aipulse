"""运行记录仓库：pipeline_runs（设计方案 §7.6）。

每次 `aipulse daily` 写一条流水线运行记录，stats 字段（JSON）用于事后审计：
耗时、各源条数、LLM 调用次数/花费、降级情况。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlmodel import Session

from aipulse.core.timeutil import utcnow
from aipulse.store.models import PipelineRun


def record_pipeline_run(
    session: Session,
    *,
    day: date,
    stage: str,
    status: str,
    stats: dict[str, Any] | None = None,
    started_at: datetime | None = None,
) -> PipelineRun:
    run = PipelineRun(
        date=day,
        stage=stage,
        status=status,
        started_at=started_at or utcnow(),
        finished_at=utcnow(),
        stats=dict(stats or {}),
    )
    session.add(run)
    session.commit()
    return run


__all__ = ["record_pipeline_run"]
