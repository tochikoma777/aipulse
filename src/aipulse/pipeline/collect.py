"""采集编排（设计方案 §5.9）。

要点：
- `asyncio.gather` + 全局并发上限 6，**每源独立 try/except**：单源失败只写 `source_runs`，
  其余源照常完成，退出码不受影响；
- v1.4 环境分级：`actions_only` 的源在本地被**跳过**，写 `status='skipped_offline'`，
  **不计入失败统计**；
- 去重在写库前统一做一次（L1/L2/L3）。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlmodel import Session

from aipulse.collectors.registry import select
from aipulse.core.config import load_settings, load_sources
from aipulse.core.logging import get_logger
from aipulse.core.timeutil import utcnow, window_since
from aipulse.normalize.dedup import DedupStats, dedup_items
from aipulse.schema.items import RawItem
from aipulse.store.db import engine_for, ensure_schema
from aipulse.store.models import SourceRun
from aipulse.store.repo_items import upsert_items, write_signals
from aipulse.utils.http import HttpClient

log = get_logger(__name__)

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_FAILED = "failed"
STATUS_SKIPPED_OFFLINE = "skipped_offline"
STATUS_SKIPPED_DISABLED = "skipped_disabled"


@dataclass
class SourceResult:
    source: str
    display_name: str
    status: str
    item_count: int = 0
    error: str | None = None
    elapsed_s: float = 0.0
    note: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass
class CollectResult:
    since: datetime
    until: datetime
    results: list[SourceResult] = field(default_factory=list)
    items: list[RawItem] = field(default_factory=list)
    dedup: DedupStats | None = None
    persisted: dict[str, int] = field(default_factory=dict)

    @property
    def ok_sources(self) -> list[SourceResult]:
        return [r for r in self.results if r.status in (STATUS_OK, STATUS_DEGRADED)]

    @property
    def failed_sources(self) -> list[SourceResult]:
        return [r for r in self.results if r.status == STATUS_FAILED]

    @property
    def skipped(self) -> list[SourceResult]:
        return [r for r in self.results if r.status == STATUS_SKIPPED_OFFLINE]

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": {
                "since": self.since.isoformat(),
                "until": self.until.isoformat(),
            },
            "sources": [
                {
                    "source": r.source,
                    "display_name": r.display_name,
                    "status": r.status,
                    "item_count": r.item_count,
                    "error": r.error,
                    "elapsed_s": round(r.elapsed_s, 2),
                    "note": r.note,
                }
                for r in self.results
            ],
            "total_items": len(self.items),
            "dedup": self.dedup.__dict__ if self.dedup else None,
            "persisted": self.persisted,
        }


async def _run_one(
    collector: Any, since: datetime, until: datetime, semaphore: asyncio.Semaphore
) -> tuple[SourceResult, list[RawItem]]:
    name = collector.source.value
    display = collector.display_name or name
    started = time.monotonic()
    started_at = utcnow()
    async with semaphore:
        try:
            items = await collector.fetch(since, until)
        except Exception as exc:  # 单源异常隔离：绝不向上抛
            log.error("collect.source_failed", source=name, error=repr(exc))
            return (
                SourceResult(
                    source=name,
                    display_name=display,
                    status=STATUS_FAILED,
                    error=f"{type(exc).__name__}: {exc}",
                    elapsed_s=time.monotonic() - started,
                    started_at=started_at,
                    finished_at=utcnow(),
                ),
                [],
            )
    status = STATUS_OK
    note = ""
    collector_status = getattr(collector, "status", STATUS_OK)
    if items and collector_status == STATUS_DEGRADED:
        status = STATUS_DEGRADED
        note = "部分 feed 降级（optional 源不影响退出码）"
    elif not items:
        status = STATUS_DEGRADED
        note = "该源本次无条目"
    if getattr(collector, "degraded_to_search_api", False):
        note = (note + "；已降级到 GitHub Search API").strip("；")
    log.info("collect.source_done", source=name, items=len(items), status=status)
    return (
        SourceResult(
            source=name,
            display_name=display,
            status=status,
            item_count=len(items),
            elapsed_s=time.monotonic() - started,
            note=note,
            started_at=started_at,
            finished_at=utcnow(),
        ),
        items,
    )


async def run_collect(
    *,
    sources: list[str] | None = None,
    since: str = "24h",
    dry_run: bool = False,
    no_cache: bool = False,
    db_path: str | None = None,
    env: dict[str, str] | None = None,
) -> CollectResult:
    """执行一次采集。返回结构化结果（CLI 负责渲染与退出码）。"""
    settings = load_settings()
    sources_cfg = load_sources().sources
    since_dt, until_dt = window_since(since)
    result = CollectResult(since=since_dt, until=until_dt)

    cache_path = None if no_cache else settings.cache_path() / "http.sqlite"
    http = HttpClient(
        connect_timeout_s=settings.http.timeout_connect_s,
        read_timeout_s=settings.http.timeout_read_s,
        max_retries=settings.http.max_retries,
        max_concurrency=settings.http.max_concurrency,
        cache_enabled=not no_cache,
        cache_path=cache_path,
        cache_ttl_s=settings.http.cache_ttl_s,
        user_agent=settings.http.user_agent,
    )
    semaphore = asyncio.Semaphore(max(1, settings.http.max_concurrency))

    try:
        collectors, skipped = select(sources_cfg, http, wanted=sources, env=env)
        for name, reason in skipped:
            # v1.4：本地跳过 actions_only 源 —— 这是"环境不支持"，不是失败
            status = STATUS_SKIPPED_OFFLINE if "actions_only" in reason else STATUS_SKIPPED_DISABLED
            result.results.append(
                SourceResult(
                    source=name,
                    display_name=name,
                    status=status,
                    note=reason,
                )
            )

        tasks = [_run_one(c, since_dt, until_dt, semaphore) for c in collectors]
        outcomes = await asyncio.gather(*tasks)
        all_items: list[RawItem] = []
        for source_result, items in outcomes:
            result.results.append(source_result)
            all_items.extend(items)

        result.items, result.dedup = dedup_items(all_items)

        if dry_run:
            result.persisted = {"inserted": 0, "updated": 0, "signals": 0}
            return result

        target_db = db_path or settings.db_path()
        ensure_schema(target_db)
        engine = engine_for(target_db)
        with Session(engine) as session:
            for source_result in result.results:
                if source_result.status == STATUS_SKIPPED_OFFLINE:
                    continue
                session.add(
                    SourceRun(
                        source=source_result.source,
                        started_at=source_result.started_at or since_dt,
                        finished_at=source_result.finished_at,
                        status=source_result.status,
                        item_count=source_result.item_count,
                        error=source_result.error,
                    )
                )
            session.commit()
            inserted, updated = upsert_items(session, result.items)
            signals = write_signals(session, result.items)
        engine.dispose()
        result.persisted = {"inserted": inserted, "updated": updated, "signals": signals}
        log.info(
            "collect.done",
            sources_ok=len(result.ok_sources),
            failed=len(result.failed_sources),
            skipped=len(result.skipped),
            items=len(result.items),
        )
        return result
    finally:
        await http.aclose()
