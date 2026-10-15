"""每日流水线端到端单测（--no-collect + --skip-llm，零网络零花费）。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from aipulse.core.config import RunMode, load_settings
from aipulse.core.timeutil import today_local
from aipulse.pipeline.daily import analyze_day, run_daily
from aipulse.store.db import init_db
from aipulse.store.models import Item, Prediction, Signal


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


def test_run_daily_writes_scoreboard_and_signals(monkeypatch, tmp_path):
    """M4：记分板（v1.10）与 signals 快照必须随报告落盘，且进 meta 摘要。"""
    monkeypatch.setenv("AIPULSE_ROOT", str(tmp_path))
    load_settings.cache_clear()
    db = tmp_path / "t.db"
    _seed(db)
    today = today_local()
    engine = init_db(db)
    with Session(engine, expire_on_commit=False) as s:
        # 两次快照 → 可算 star 增速（跨天在 Actions 中由 cache 恢复得到）
        s.add(
            Signal(
                entity_type="repo",
                entity_key="org/a",
                metric="stars",
                value=1000,
                ts=datetime.now(tz=UTC) - timedelta(hours=24),
            )
        )
        s.add(
            Signal(
                entity_type="repo",
                entity_key="org/a",
                metric="stars",
                value=1200,
                ts=datetime.now(tz=UTC) - timedelta(hours=1),
            )
        )
        s.add(
            Prediction(
                id="pred_ok",
                date=today - timedelta(days=30),
                statement="acme 将出现新仓库",
                category="community",
                confidence=0.8,
                horizon_days=30,
                due_date=today - timedelta(days=1),
                falsifiable_criteria="窗口内 acme 出现新仓库即命中",
                status="pending",
                criteria="github_new_repo",
                criteria_params={"owner": "acme"},
            )
        )
        s.add(
            Signal(
                entity_type="repo",
                entity_key="acme/new",
                metric="stars",
                value=1,
                ts=datetime.now(tz=UTC) - timedelta(days=10),
            )
        )
        s.commit()
    engine.dispose()

    result = asyncio.run(run_daily(no_collect=True, skip_llm=True, db_path=str(db)))

    import json as _json

    assert (result.report_dir / "scoreboard.md").exists()
    assert (result.report_dir / "signals.json").exists()
    assert (result.report_dir / "verdicts.md").exists()

    signals = _json.loads((result.report_dir / "signals.json").read_text(encoding="utf-8"))
    assert signals["date"] == result.day.isoformat()
    assert signals["with_velocity"] >= 1
    hot = next(s for s in signals["series"] if s["entity_key"] == "org/a")
    assert hot["points"] == 2
    assert hot["delta"] == 200.0
    assert hot["velocity_per_hour"] is not None

    # meta.json 里要有可直接比对的关键摘要
    assert result.meta["signals"]["with_velocity"] >= 1
    assert result.meta["predictions"]["verified"] == 1

    assert "🎯 预言记分板" in (result.report_dir / "scoreboard.md").read_text(encoding="utf-8")
    assert "命中" in (result.report_dir / "verdicts.md").read_text(encoding="utf-8")


def test_run_daily_auto_verify_off_mode(monkeypatch, tmp_path):
    """`daily` 在 off 档自动验证量化判据预言（零 LLM），并写进 meta。"""
    monkeypatch.setenv("AIPULSE_ROOT", str(tmp_path))
    load_settings.cache_clear()
    db = tmp_path / "t.db"
    _seed(db)
    today = today_local()
    engine = init_db(db)
    with Session(engine, expire_on_commit=False) as s:
        s.add(
            Prediction(
                id="pred_due",
                date=today - timedelta(days=30),
                statement="acme 将出现新仓库",
                category="community",
                confidence=0.7,
                horizon_days=30,
                due_date=today - timedelta(days=1),
                falsifiable_criteria="窗口内 acme 出现新仓库即命中",
                status="pending",
                criteria="github_new_repo",
                criteria_params={"owner": "acme"},
            )
        )
        s.add(
            Signal(
                entity_type="repo",
                entity_key="acme/new",
                metric="stars",
                value=1,
                ts=datetime.now(tz=UTC) - timedelta(days=10),
            )
        )
        s.commit()
    engine.dispose()

    result = asyncio.run(run_daily(no_collect=True, skip_llm=True, db_path=str(db)))

    assert result.meta["verify"]["verified"] == 1
    assert result.meta["verify"]["llm_calls"] == 0
