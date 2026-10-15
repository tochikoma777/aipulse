"""CLI 单测：`predict verify` / `predict review` / `stats --predictions`（off 档，零网络）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlmodel import Session
from typer.testing import CliRunner

from aipulse.cli.commands import predict, stats
from aipulse.core.timeutil import today_local
from aipulse.store.db import engine_for, init_db
from aipulse.store.models import Prediction, Signal

runner = CliRunner()


def _seed_due(db: str) -> None:
    """造一条「带量化判据且已到期」的预言 + 一条窗口内 signal。"""
    today = today_local()
    engine = init_db(db)
    with Session(engine, expire_on_commit=False) as s:
        s.add(
            Prediction(
                id="pred_q",
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
                value=10,
                ts=datetime.now(tz=UTC) - timedelta(days=10),
            )
        )
        s.commit()
    engine.dispose()


def _get(db: str, pid: str) -> Prediction:
    engine = engine_for(db)
    with Session(engine, expire_on_commit=False) as s:
        row = s.get(Prediction, pid)
    engine.dispose()
    assert row is not None
    return row


def test_verify_quantified_off_mode(tmp_path):
    db = str(tmp_path / "t.db")
    _seed_due(db)
    result = runner.invoke(predict.app, ["verify", "--skip-llm", "--json", "--db", db])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["verified"] == 1
    assert payload["llm_calls"] == 0
    assert _get(db, "pred_q").status == "verified"
    assert _get(db, "pred_q").verdict == "hit"


def test_verify_then_list_verified(tmp_path):
    db = str(tmp_path / "t.db")
    _seed_due(db)
    runner.invoke(predict.app, ["verify", "--skip-llm", "--db", db])
    result = runner.invoke(predict.app, ["list", "--status", "verified", "--json", "--db", db])
    assert result.exit_code == 0
    assert "pred_q" in result.stdout


def test_review_human_overrides_and_counts(tmp_path):
    db = str(tmp_path / "t.db")
    _seed_due(db)
    runner.invoke(predict.app, ["verify", "--skip-llm", "--db", db])  # auto 先判 hit
    result = runner.invoke(
        predict.app,
        [
            "review",
            "pred_q",
            "--verdict",
            "miss",
            "--note",
            "人工复核：未发生",
            "--json",
            "--db",
            db,
        ],
    )
    assert result.exit_code == 0
    row = _get(db, "pred_q")
    assert row.verdict == "miss"
    assert row.verdict_score == 0.0
    assert row.verified_by == "human"


def test_review_rejects_bad_verdict(tmp_path):
    db = str(tmp_path / "t.db")
    _seed_due(db)
    result = runner.invoke(predict.app, ["review", "pred_q", "--verdict", "maybe", "--db", db])
    assert result.exit_code == 1


def test_review_unknown_id(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).dispose()
    result = runner.invoke(predict.app, ["review", "nope", "--verdict", "hit", "--db", db])
    assert result.exit_code == 1


def test_stats_json_has_brier(tmp_path):
    db = str(tmp_path / "t.db")
    _seed_due(db)
    runner.invoke(predict.app, ["verify", "--skip-llm", "--db", db])
    result = runner.invoke(stats.app, ["--predictions", "--json", "--db", db])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["verified"] == 1
    assert payload["brier"] is not None
    assert len(payload["calibration"]) == 5


def test_stats_markdown(tmp_path):
    db = str(tmp_path / "t.db")
    _seed_due(db)
    runner.invoke(predict.app, ["verify", "--skip-llm", "--db", db])
    result = runner.invoke(stats.app, ["--predictions", "--markdown", "--db", db])
    assert result.exit_code == 0
    assert "预言记分板" in result.stdout


def test_stats_empty_state(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).dispose()
    result = runner.invoke(stats.app, ["--predictions", "--markdown", "--db", db])
    assert result.exit_code == 0
    assert "尚无到期判定结果" in result.stdout
