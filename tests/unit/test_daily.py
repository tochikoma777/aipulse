"""每日流水线端到端单测（--no-collect + --skip-llm，零网络零花费）。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlmodel import Session

from aipulse.core.config import RunMode, load_settings
from aipulse.pipeline.daily import analyze_day, run_daily
from aipulse.store.db import init_db
from aipulse.store.models import Item


def _seed(db_path):
    engine = init_db(db_path)
    now = datetime.now(tz=UTC)
    with Session(engine) as s:
        s.add(
            Item(
                id="a",
                source="github_trending",
                external_id="org/a",
                title="vLLM 发布 v1 加速推理",
                url="https://github.com/org/a",
                summary="vLLM 高性能推理",
                collected_at=now,
                published_at=now,
                metrics={"stars_total": 1000, "stars_in_window": 100},
                seen_in=["github_trending"],
                content_hash="h-a",
                hot_score=0.0,
            )
        )
        s.add(
            Item(
                id="b",
                source="hackernews",
                external_id="2",
                title="OpenAI GPT-5 讨论",
                url="https://news.ycombinator.com/item?id=2",
                summary="GPT-5 discussion",
                collected_at=now,
                published_at=now,
                metrics={"points": 200, "num_comments": 50},
                seen_in=["hackernews"],
                content_hash="h-b",
                hot_score=0.0,
            )
        )
        s.commit()
    engine.dispose()


def test_analyze_day_scores_and_writes(monkeypatch, tmp_path):
    monkeypatch.setenv("AIPULSE_ROOT", str(tmp_path))
    load_settings.cache_clear()
    db = tmp_path / "t.db"
    _seed(db)
    from aipulse.store.db import engine_for

    engine = engine_for(db)
    from aipulse.core.timeutil import today_local

    with Session(engine) as s:
        stats = analyze_day(s, day=today_local())
    engine.dispose()
    assert stats["items"] == 2
    assert stats["scored"] == 2


def test_run_daily_off_mode_produces_reports(monkeypatch, tmp_path):
    """DoD ★：aipulse daily --skip-llm 端到端跑通并产出 daily.json（零 API 花费）。"""
    monkeypatch.setenv("AIPULSE_ROOT", str(tmp_path))
    load_settings.cache_clear()
    db = tmp_path / "t.db"
    _seed(db)

    result = asyncio.run(run_daily(no_collect=True, skip_llm=True, db_path=str(db)))

    assert result.mode == RunMode.OFF
    assert result.report_dir is not None
    assert (result.report_dir / "brief.md").exists()
    assert (result.report_dir / "daily.json").exists()
    assert (result.report_dir / "meta.json").exists()

    import json as _json

    daily = _json.loads((result.report_dir / "daily.json").read_text(encoding="utf-8"))
    assert daily["meta"]["mode"] == "off"
    assert len(daily["items"]) == 2
