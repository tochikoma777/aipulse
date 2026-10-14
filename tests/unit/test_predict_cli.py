"""predict CLI 单测：手写预言（非交互 + 交互向导）+ 列表 + 自动生成 off 档。

交互向导通过 monkeypatch 掉 typer.prompt / rich Prompt.ask / typer.confirm，
确定性回放向导流程（内容 → 置信度 → 到期天数 → 判据模板 → 参数 → 确认）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import typer
from sqlmodel import Session, select
from typer.testing import CliRunner

from aipulse.cli.commands import predict
from aipulse.store.db import init_db
from aipulse.store.models import Prediction

runner = CliRunner()


def _read_predictions(db: str) -> list[Prediction]:
    # 拒绝路径在写库前就退出，可能未建库；这里用 init_db 兜底建表
    engine = init_db(db)
    with Session(engine, expire_on_commit=False) as session:
        rows = list(session.exec(select(Prediction)).all())
    engine.dispose()
    return rows


# ── 非交互路径（全参数 + --yes）──────────────────────────────────────


def test_add_non_interactive(tmp_path: Path):
    db = str(tmp_path / "t.db")
    with pytest.raises(typer.Exit) as exc:
        predict.add(
            statement="Qwen3 将在 30 天内开源",
            confidence=0.75,
            horizon_days=30,
            criteria=None,
            falsifiable="GitHub 出现 Qwen3 官方仓库即命中",
            param=None,
            note="通义实验室密集预热",
            yes=True,
            db=db,
        )
    assert exc.value.exit_code == 0
    rows = _read_predictions(db)
    assert len(rows) == 1
    assert rows[0].origin == "human"
    assert rows[0].confidence == 0.75
    assert rows[0].horizon_days == 30
    assert rows[0].falsifiable_criteria == "GitHub 出现 Qwen3 官方仓库即命中"


def test_add_with_criteria_template_non_interactive(tmp_path: Path):
    db = str(tmp_path / "t.db")
    with pytest.raises(typer.Exit):
        predict.add(
            statement="vllm 仓库 star 将达到 90000",
            confidence=0.8,
            horizon_days=30,
            criteria="github_stars_reach",
            falsifiable=None,
            param=["repo=vllm-project/vllm", "threshold=90000"],
            note=None,
            yes=True,
            db=db,
        )
    rows = _read_predictions(db)
    assert len(rows) == 1
    assert rows[0].criteria == "github_stars_reach"
    assert rows[0].criteria_params == {"repo": "vllm-project/vllm", "threshold": 90000}
    assert "github_stars_reach" in rows[0].falsifiable_criteria


def test_add_rejects_missing_falsifiable(tmp_path: Path):
    db = str(tmp_path / "t.db")
    with pytest.raises(typer.Exit) as exc:
        predict.add(
            statement="X 将在 30 天内发布",
            confidence=0.6,
            horizon_days=30,
            criteria=None,
            falsifiable="",
            param=None,
            note=None,
            yes=True,
            db=db,
        )
    assert exc.value.exit_code == 1
    assert _read_predictions(db) == []


def test_add_rejects_vague_statement(tmp_path: Path):
    db = str(tmp_path / "t.db")
    with pytest.raises(typer.Exit) as exc:
        predict.add(
            statement="X 未来可能会发布",
            confidence=0.6,
            horizon_days=30,
            criteria=None,
            falsifiable="发布即命中",
            param=None,
            note=None,
            yes=True,
            db=db,
        )
    assert exc.value.exit_code == 1
    assert _read_predictions(db) == []


# ── 交互式向导路径（monkeypatch 回放）────────────────────────────────


def test_add_interactive_wizard(tmp_path: Path, monkeypatch):
    db = str(tmp_path / "t.db")
    # statement / confidence 走 typer.prompt
    text_prompts = iter(["Qwen3 将在 30 天内开源", "0.75"])
    monkeypatch.setattr(predict.typer, "prompt", lambda *a, **k: next(text_prompts))
    # horizon / 判据模板 / 判据参数 走 Prompt.ask
    ask_answers = iter(["30", "github_stars_reach", "vllm-project/vllm", "80000"])
    monkeypatch.setattr(predict.Prompt, "ask", lambda *a, **k: next(ask_answers))
    monkeypatch.setattr(predict.typer, "confirm", lambda *a, **k: True)

    with pytest.raises(typer.Exit) as exc:
        predict.add(
            statement=None,
            confidence=None,
            horizon_days=None,
            criteria=None,
            falsifiable=None,
            param=None,
            note=None,
            yes=False,
            db=db,
        )
    assert exc.value.exit_code == 0
    rows = _read_predictions(db)
    assert len(rows) == 1
    row = rows[0]
    assert row.statement == "Qwen3 将在 30 天内开源"
    assert row.confidence == 0.75
    assert row.horizon_days == 30
    assert row.criteria == "github_stars_reach"
    assert row.criteria_params == {"repo": "vllm-project/vllm", "threshold": 80000}


def test_add_interactive_wizard_no_criteria(tmp_path: Path, monkeypatch):
    db = str(tmp_path / "t.db")
    # statement / confidence / falsifiable（不设定判据时追问）
    text_prompts = iter(["某框架将登顶", "0.6", "Benchmark 榜首即命中"])
    monkeypatch.setattr(predict.typer, "prompt", lambda *a, **k: next(text_prompts))
    # horizon=30，判据模板=不设定
    ask_answers = iter(["30", "不设定"])
    monkeypatch.setattr(predict.Prompt, "ask", lambda *a, **k: next(ask_answers))
    monkeypatch.setattr(predict.typer, "confirm", lambda *a, **k: True)

    with pytest.raises(typer.Exit):
        predict.add(
            statement=None,
            confidence=None,
            horizon_days=None,
            criteria=None,
            falsifiable=None,
            param=None,
            note=None,
            yes=False,
            db=db,
        )
    rows = _read_predictions(db)
    assert len(rows) == 1
    assert rows[0].criteria is None
    assert rows[0].falsifiable_criteria == "Benchmark 榜首即命中"


# ── 列表 + 自动生成 off 档 ───────────────────────────────────────────


def test_list_json_empty(tmp_path: Path):
    db = str(tmp_path / "t.db")
    result = runner.invoke(predict.app, ["list", "--json", "--db", db])
    assert result.exit_code == 0
    assert result.stdout.strip() == "[]"


def test_list_json_after_add(tmp_path: Path):
    db = str(tmp_path / "t.db")
    with pytest.raises(typer.Exit):
        predict.add(
            statement="Qwen3 将在 30 天内开源",
            confidence=0.7,
            horizon_days=30,
            criteria=None,
            falsifiable="官方发布即命中",
            param=None,
            note=None,
            yes=True,
            db=db,
        )
    result = runner.invoke(predict.app, ["list", "--json", "--origin", "human", "--db", db])
    assert result.exit_code == 0
    assert "Qwen3" in result.stdout


def test_predict_off_mode_outputs_json(tmp_path: Path):
    db = str(tmp_path / "t.db")
    result = runner.invoke(predict.app, ["--skip-llm", "--json", "--db", db])
    assert result.exit_code == 0
    assert '"generated": 0' in result.stdout
