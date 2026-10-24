"""`aipulse doctor` 的数据源健康检查（C1）。

口径：只看**截至最新一期**的连续整源 0 条；中间有一天正常就封口；
`inbox` 是手动通道不算故障；`--no-collect` 的日报整份跳过。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aipulse.cli.commands.doctor import _source_health_check


def _write(root: Path, day: str, rows: list[dict[str, object]], *, collected: bool = True) -> None:
    target = root.joinpath(*day.split("-"))
    target.mkdir(parents=True, exist_ok=True)
    (target / "source_runs.json").write_text(
        json.dumps({"date": day, "collected": collected, "sources": rows}, ensure_ascii=False),
        encoding="utf-8",
    )


def _row(source: str, status: str, count: int) -> dict[str, object]:
    return {"source": source, "status": status, "item_count": count}


def test_health_ok_when_all_sources_fresh(tmp_path: Path) -> None:
    _write(tmp_path, "2026-10-23", [_row("arxiv", "ok", 60), _row("rss", "ok", 30)])
    _write(tmp_path, "2026-10-24", [_row("arxiv", "ok", 60), _row("rss", "ok", 30)])
    state, detail = _source_health_check(tmp_path)
    assert state == "ok"
    assert "无整源 0 条" in detail


def test_health_warns_at_two_days_and_fails_at_three(tmp_path: Path) -> None:
    for day in ("2026-10-22", "2026-10-23"):
        _write(tmp_path, day, [_row("arxiv", "failed", 0), _row("rss", "ok", 30)])
    state, detail = _source_health_check(tmp_path)
    assert state == "warn"
    assert "arxiv 连续 2 天" in detail

    _write(tmp_path, "2026-10-24", [_row("arxiv", "failed", 0), _row("rss", "ok", 30)])
    state, detail = _source_health_check(tmp_path)
    assert state == "fail"
    assert "arxiv 连续 3 天" in detail


def test_health_streak_stops_at_last_healthy_day(tmp_path: Path) -> None:
    """10-19/20 挂、10-21 正常、10-22 又挂 → 只算 1 天，不能累加成 3。"""
    _write(tmp_path, "2026-10-19", [_row("arxiv", "failed", 0)])
    _write(tmp_path, "2026-10-20", [_row("arxiv", "failed", 0)])
    _write(tmp_path, "2026-10-21", [_row("arxiv", "ok", 60)])
    _write(tmp_path, "2026-10-22", [_row("arxiv", "failed", 0)])
    state, detail = _source_health_check(tmp_path)
    assert state == "ok"
    assert "arxiv 连续 1 天" in detail


def test_health_ignores_inbox_and_no_collect(tmp_path: Path) -> None:
    _write(tmp_path, "2026-10-23", [_row("inbox", "degraded", 0), _row("arxiv", "ok", 60)])
    _write(
        tmp_path,
        "2026-10-24",
        [_row("arxiv", "failed", 0)],
        collected=False,  # --no-collect：整份跳过，不算 arxiv 连败
    )
    state, detail = _source_health_check(tmp_path)
    assert state == "ok"
    assert "inbox" not in detail


def test_health_reports_missing_history(tmp_path: Path) -> None:
    state, detail = _source_health_check(tmp_path)
    assert state == "warn"
    assert "没有 source_runs.json" in detail


def test_health_all_no_collect_is_unknown(tmp_path: Path) -> None:
    _write(tmp_path, "2026-10-24", [_row("arxiv", "failed", 0)], collected=False)
    state, detail = _source_health_check(tmp_path)
    assert state == "warn"
    assert "无法判断" in detail


@pytest.mark.parametrize("bad_day", ["2026-10-24"])
def test_health_tolerates_corrupt_json(tmp_path: Path, bad_day: str) -> None:
    target = tmp_path.joinpath(*bad_day.split("-"))
    target.mkdir(parents=True)
    (target / "source_runs.json").write_text("{ not json", encoding="utf-8")
    state, detail = _source_health_check(tmp_path)
    assert state == "warn"
    assert "无法判断" in detail
