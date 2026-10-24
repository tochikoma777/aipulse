"""`aipulse watchlist`：每日轻量核对（T9 / P0-3）。

覆盖两件事：命令本身（只核对不新建 / 写回 / 不写回），以及
`_state_files` 对两种 state_dir 布局的兼容（这是本轮修的真 bug）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aipulse.reasoning.selfcheck import _state_files


def _day(root: Path, day: str, item_ids: list[str]) -> None:
    target = root.joinpath(*day.split("-"))
    target.mkdir(parents=True, exist_ok=True)
    items = {
        item_id: {
            "title": f"item {item_id[-4:]}",
            "url": f"https://example.com/{item_id}",
            "source": "github_trending",
            "hot_score": 50.0,
        }
        for item_id in item_ids
    }
    (target / "daily.json").write_text(
        json.dumps({"date": day, "items": items, "sections": []}, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_watchlist(path: Path, entries: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")


def test_state_files_covers_both_layouts(tmp_path: Path) -> None:
    """trend 根目录当 state_dir 时也要能读到各期文件（parent glob 不到）。"""
    period = tmp_path / "trend" / "2026-10-22"
    _write_watchlist(period / "watchlist.json", [{"issue": "2026-10-22"}])
    root_state = tmp_path / "trend" / "watchlist.json"
    _write_watchlist(root_state, [{"issue": "consolidated"}])

    as_root = _state_files(tmp_path / "trend", "watchlist.json")
    assert root_state in as_root and (period / "watchlist.json") in as_root

    as_period = _state_files(period, "watchlist.json")
    assert (period / "watchlist.json") in as_period


def test_watchlist_cli_resolves_pending_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from aipulse.cli.commands import watchlist as wl_cmd
    from aipulse.cli.main import app
    from aipulse.core.config import Settings

    _day(tmp_path, "2026-10-23", ["it_aaaaaaaaaaaaaaaa"])
    _day(tmp_path, "2026-10-24", ["it_bbbbbbbbbbbbbbbb"])  # it_aaaa… 已不在榜
    _write_watchlist(
        tmp_path / "trend" / "2026-10-23" / "watchlist.json",
        [
            {
                "issue": "2026-10-23",
                "item_id": "it_aaaaaaaaaaaaaaaa",
                "check_on": "2026-10-24",
                "expectation": "下期是否仍在榜",
                "status": "pending",
            }
        ],
    )
    settings = Settings(app={"data_dir": str(tmp_path)}, mode="off")
    monkeypatch.setattr(wl_cmd, "load_settings", lambda *a, **k: settings)

    result = CliRunner().invoke(app, ["watchlist", "--reports-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "本轮核对 1 条 watchlist" in result.output
    assert "跌出 1" in result.output

    merged = json.loads((tmp_path / "trend" / "watchlist.json").read_text(encoding="utf-8"))
    entry = merged["entries"][0]
    assert entry["status"] == "dropped"
    assert entry["resolved_on"] == "2026-10-24"


def test_watchlist_cli_no_write_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from aipulse.cli.commands import watchlist as wl_cmd
    from aipulse.cli.main import app
    from aipulse.core.config import Settings

    _day(tmp_path, "2026-10-23", ["it_aaaaaaaaaaaaaaaa"])
    _day(tmp_path, "2026-10-24", [])
    period = tmp_path / "trend" / "2026-10-23"
    _write_watchlist(
        period / "watchlist.json",
        [
            {
                "issue": "2026-10-23",
                "item_id": "it_aaaaaaaaaaaaaaaa",
                "check_on": "2026-10-24",
                "expectation": "下期是否仍在榜",
                "status": "pending",
            }
        ],
    )
    settings = Settings(app={"data_dir": str(tmp_path)}, mode="off")
    monkeypatch.setattr(wl_cmd, "load_settings", lambda *a, **k: settings)

    result = CliRunner().invoke(
        app, ["watchlist", "--reports-dir", str(tmp_path), "--no-write-state"]
    )
    assert result.exit_code == 0, result.output
    # 只读：不写合并文件，也不改各期文件
    assert not (tmp_path / "trend" / "watchlist.json").exists()
    entries = json.loads((period / "watchlist.json").read_text(encoding="utf-8"))["entries"]
    assert entries[0]["status"] == "pending"


def test_watchlist_cli_requires_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from aipulse.cli.commands import watchlist as wl_cmd
    from aipulse.cli.main import app
    from aipulse.core.config import Settings

    settings = Settings(app={"data_dir": str(tmp_path)}, mode="off")
    monkeypatch.setattr(wl_cmd, "load_settings", lambda *a, **k: settings)
    result = CliRunner().invoke(app, ["watchlist", "--reports-dir", str(tmp_path)])
    assert result.exit_code == 2
    assert "没有找到任何日报" in result.output
