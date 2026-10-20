"""M6c S2：knowledge CLI（mark / note / list）。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlmodel import Session
from typer.testing import CliRunner

from aipulse.cli.commands import knowledge as knowledge_cli
from aipulse.cli.main import app
from aipulse.core.config import AppSettings, Settings
from aipulse.core.timeutil import ensure_utc
from aipulse.knowledge.store import KnowledgeStore
from aipulse.store.db import init_db
from aipulse.store.models import Item

runner = CliRunner()


def _settings(tmp_path: Path) -> Settings:
    return Settings(app=AppSettings(data_dir=str(tmp_path / "data")))


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    args: list[str],
):
    settings = _settings(tmp_path)
    monkeypatch.setattr(knowledge_cli, "load_settings", lambda: settings)
    return runner.invoke(app, ["knowledge", *args])


def _user_db(tmp_path: Path) -> Path:
    return tmp_path / "data" / "user_data.db"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_main_db(path: Path) -> None:
    engine = init_db(path)
    try:
        with Session(engine) as session:
            session.add(
                Item(
                    id="it_main_1",
                    source="rss",
                    title="主库条目",
                    url="https://example.com/main",
                    content_hash="main-hash-1",
                )
            )
            session.commit()
    finally:
        engine.dispose()


def _write_daily(
    tmp_path: Path,
    day: str,
    *,
    items: dict[str, object],
    comments: list[dict[str, object]] | None = None,
    sections: list[dict[str, object]] | None = None,
) -> Path:
    year, month, day_num = day.split("-")
    path = tmp_path / "data" / "reports" / year / month / day_num / "daily.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": day,
        "items": items,
        "comments": comments or [],
        "sections": sections or [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _daily_item(title: str, url: str) -> dict[str, object]:
    return {"title": title, "url": url, "hot_score": 10.0}


def test_knowledge_help_lists_subcommands() -> None:
    result = runner.invoke(app, ["knowledge", "--help"])
    assert result.exit_code == 0, result.output
    for sub in ("mark", "note", "items", "list", "export"):
        assert sub in result.output


def test_mark_rejects_invalid_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _invoke(
        monkeypatch,
        tmp_path,
        ["mark", "it_x", "--status", "done"],
    )
    assert result.exit_code != 0
    assert "非法状态" in result.output
    assert not _user_db(tmp_path).exists()


def test_note_overwrites_and_preserves_created_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t1 = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)
    t2 = t1 + timedelta(minutes=5)
    times = iter([t1, t2])
    monkeypatch.setattr("aipulse.knowledge.store.utcnow", lambda: next(times))

    first = _invoke(monkeypatch, tmp_path, ["note", "it_1", "--note", "第一版", "--allow-unknown"])
    assert first.exit_code == 0, first.output
    second = _invoke(monkeypatch, tmp_path, ["note", "it_1", "--note", "第二版", "--allow-unknown"])
    assert second.exit_code == 0, second.output

    store = KnowledgeStore(_user_db(tmp_path))
    try:
        row = store.get("it_1")
        assert row is not None
        assert row.note == "第二版"
        assert ensure_utc(row.created_at) == t1
        assert ensure_utc(row.updated_at) == t2
    finally:
        store.close()


def test_note_empty_string_clears_and_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (
        _invoke(
            monkeypatch, tmp_path, ["note", "it_1", "--note", "有内容", "--allow-unknown"]
        ).exit_code
        == 0
    )
    result = _invoke(monkeypatch, tmp_path, ["note", "it_1", "--note", "", "--allow-unknown"])
    assert result.exit_code == 0, result.output
    assert "清空" in result.output

    store = KnowledgeStore(_user_db(tmp_path))
    try:
        row = store.get("it_1")
        assert row is not None
        assert row.note == ""
    finally:
        store.close()


def test_note_without_option_is_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _invoke(monkeypatch, tmp_path, ["note", "it_1", "--allow-unknown"])
    assert result.exit_code == 1
    assert "暂未实现，请用 --note" in result.output
    assert not _user_db(tmp_path).exists()


def test_mark_updates_status_without_clobbering_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (
        _invoke(
            monkeypatch, tmp_path, ["note", "it_1", "--note", "保留我", "--allow-unknown"]
        ).exit_code
        == 0
    )
    result = _invoke(monkeypatch, tmp_path, ["mark", "it_1", "--status", "read", "--allow-unknown"])
    assert result.exit_code == 0, result.output
    assert "read" in result.output

    store = KnowledgeStore(_user_db(tmp_path))
    try:
        row = store.get("it_1")
        assert row is not None
        assert row.status == "read"
        assert row.note == "保留我"
    finally:
        store.close()


def test_list_filters_status_with_notes_and_previews(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    long_note = "长" * 100
    assert (
        _invoke(
            monkeypatch, tmp_path, ["note", "it_read", "--note", long_note, "--allow-unknown"]
        ).exit_code
        == 0
    )
    assert (
        _invoke(
            monkeypatch, tmp_path, ["mark", "it_read", "--status", "read", "--allow-unknown"]
        ).exit_code
        == 0
    )
    assert (
        _invoke(
            monkeypatch, tmp_path, ["mark", "it_unread", "--status", "unread", "--allow-unknown"]
        ).exit_code
        == 0
    )

    result = _invoke(monkeypatch, tmp_path, ["list", "--status", "read"])
    assert result.exit_code == 0, result.output
    assert "it_read" in result.output
    assert "it_unread" not in result.output
    assert "…" in result.output
    assert long_note not in result.output

    with_notes = _invoke(monkeypatch, tmp_path, ["list", "--with-notes"])
    assert with_notes.exit_code == 0, with_notes.output
    assert "it_read" in with_notes.output
    assert "it_unread" not in with_notes.output


def test_list_rejects_invalid_status_and_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad_status = _invoke(monkeypatch, tmp_path, ["list", "--status", "done"])
    assert bad_status.exit_code != 0
    assert "非法状态" in bad_status.output

    bad_limit = _invoke(monkeypatch, tmp_path, ["list", "--limit", "0"])
    assert bad_limit.exit_code != 0
    assert "limit" in bad_limit.output.lower()


def test_allow_unknown_writes_without_main_db_validation_and_keeps_it_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main_db = tmp_path / "data" / "aipulse.db"
    _seed_main_db(main_db)
    before_size = main_db.stat().st_size
    before_mtime_ns = main_db.stat().st_mtime_ns
    before_hash = _sha256(main_db)

    # it_not_in_main 不在主库、也不在 daily_index；显式 --allow-unknown 才写入
    result = _invoke(
        monkeypatch, tmp_path, ["note", "it_not_in_main", "--note", "跨库笔记", "--allow-unknown"]
    )
    assert result.exit_code == 0, result.output

    store = KnowledgeStore(_user_db(tmp_path))
    try:
        assert store.get("it_not_in_main") is not None
    finally:
        store.close()

    assert main_db.stat().st_size == before_size
    assert main_db.stat().st_mtime_ns == before_mtime_ns
    assert _sha256(main_db) == before_hash


def test_note_by_url_resolves_and_keeps_main_db_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_daily(
        tmp_path,
        "2026-10-18",
        items={"it_url": _daily_item("URL 条目", "https://example.com/url-item")},
    )
    main_db = tmp_path / "data" / "aipulse.db"
    _seed_main_db(main_db)
    before_size = main_db.stat().st_size
    before_mtime_ns = main_db.stat().st_mtime_ns
    before_hash = _sha256(main_db)

    result = _invoke(
        monkeypatch,
        tmp_path,
        ["note", "--url", "https://example.com/url-item", "--note", "URL 笔记"],
    )
    assert result.exit_code == 0, result.output
    assert "it_url" in result.output

    store = KnowledgeStore(_user_db(tmp_path))
    try:
        row = store.get("it_url")
        assert row is not None
        assert row.note == "URL 笔记"
    finally:
        store.close()

    assert main_db.stat().st_size == before_size
    assert main_db.stat().st_mtime_ns == before_mtime_ns
    assert _sha256(main_db) == before_hash


def test_mark_by_url_resolves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_daily(
        tmp_path,
        "2026-10-18",
        items={"it_url": _daily_item("URL 条目", "https://example.com/url-item")},
    )
    result = _invoke(
        monkeypatch,
        tmp_path,
        ["mark", "--url", "https://example.com/url-item", "--status", "read"],
    )
    assert result.exit_code == 0, result.output
    assert "it_url" in result.output

    store = KnowledgeStore(_user_db(tmp_path))
    try:
        row = store.get("it_url")
        assert row is not None
        assert row.status == "read"
    finally:
        store.close()


def test_note_by_query_single_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_daily(
        tmp_path,
        "2026-10-18",
        items={"it_query": _daily_item("Unique Agent Framework", "https://e/query")},
    )
    result = _invoke(
        monkeypatch,
        tmp_path,
        ["note", "--query", "unique agent", "--note", "关键词笔记"],
    )
    assert result.exit_code == 0, result.output
    assert "it_query" in result.output

    store = KnowledgeStore(_user_db(tmp_path))
    try:
        row = store.get("it_query")
        assert row is not None
        assert row.note == "关键词笔记"
    finally:
        store.close()


def test_query_multiple_lists_candidates_and_does_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_daily(
        tmp_path,
        "2026-10-18",
        items={
            "it_a": _daily_item("Agent Alpha", "https://e/a"),
            "it_b": _daily_item("Agent Beta", "https://e/b"),
        },
    )
    result = _invoke(
        monkeypatch,
        tmp_path,
        ["note", "--query", "agent", "--note", "不应写入"],
    )
    assert result.exit_code != 0
    assert "it_a" in result.output
    assert "it_b" in result.output
    assert "未自动选择" in result.output
    assert not _user_db(tmp_path).exists()


def test_query_zero_matches_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_daily(
        tmp_path,
        "2026-10-18",
        items={"it_a": _daily_item("Agent Alpha", "https://e/a")},
    )
    result = _invoke(
        monkeypatch,
        tmp_path,
        ["note", "--query", "zzz", "--note", "不应写入"],
    )
    assert result.exit_code != 0
    assert "没有匹配条目" in result.output
    assert not _user_db(tmp_path).exists()


def test_selector_mutual_exclusion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _invoke(
        monkeypatch,
        tmp_path,
        ["note", "it_1", "--url", "https://e/1", "--note", "x"],
    )
    assert result.exit_code != 0
    assert "三选一" in result.output
    assert not _user_db(tmp_path).exists()


def test_items_lists_and_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_daily(
        tmp_path,
        "2026-10-18",
        items={
            "it_a": _daily_item("Agent Alpha", "https://e/a"),
            "it_b": _daily_item("Beta Tool", "https://e/b"),
        },
        sections=[{"name": "开源项目", "item_ids": ["it_a", "it_b"]}],
    )
    _write_daily(
        tmp_path,
        "2026-10-17",
        items={"it_old": _daily_item("Old Item", "https://e/old")},
        sections=[{"name": "社区舆论", "item_ids": ["it_old"]}],
    )

    result = _invoke(monkeypatch, tmp_path, ["items"])
    assert result.exit_code == 0, result.output
    for value in ("it_a", "Agent Alpha", "https://e/a", "开源项目", "2026-10-18"):
        assert value in result.output

    filtered = _invoke(monkeypatch, tmp_path, ["items", "--query", "beta"])
    assert filtered.exit_code == 0, filtered.output
    assert "it_b" in filtered.output
    assert "it_a" not in filtered.output

    by_day = _invoke(monkeypatch, tmp_path, ["items", "--day", "2026-10-17"])
    assert by_day.exit_code == 0, by_day.output
    assert "it_old" in by_day.output
    assert "it_a" not in by_day.output


def test_items_rejects_bad_day_and_zero_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_daily(
        tmp_path,
        "2026-10-18",
        items={"it_a": _daily_item("Agent Alpha", "https://e/a")},
    )
    bad_day = _invoke(monkeypatch, tmp_path, ["items", "--day", "2026/10/18"])
    assert bad_day.exit_code != 0
    assert "YYYY-MM-DD" in bad_day.output

    no_match = _invoke(monkeypatch, tmp_path, ["items", "--query", "zzz"])
    assert no_match.exit_code != 0
    assert "没有匹配条目" in no_match.output


def test_list_shows_title_and_unknown_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_daily(
        tmp_path,
        "2026-10-18",
        items={"it_known": _daily_item("Known Title", "https://e/known")},
    )
    assert _invoke(monkeypatch, tmp_path, ["note", "it_known", "--note", "已收录"]).exit_code == 0
    assert (
        _invoke(
            monkeypatch, tmp_path, ["note", "it_unknown", "--note", "未收录", "--allow-unknown"]
        ).exit_code
        == 0
    )

    result = _invoke(monkeypatch, tmp_path, ["list"])
    assert result.exit_code == 0, result.output
    assert "Known Title" in result.output
    assert "(标题未知)" in result.output


def test_unknown_item_id_is_rejected_without_allow_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _invoke(monkeypatch, tmp_path, ["note", "it_missing", "--note", "孤儿"])
    assert result.exit_code != 0
    assert "未找到 item_id" in result.output
    assert "--allow-unknown" in result.output
    assert not _user_db(tmp_path).exists()


def test_known_item_id_from_index_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_daily(
        tmp_path,
        "2026-10-18",
        items={"it_known": _daily_item("Known", "https://e/known")},
    )
    result = _invoke(monkeypatch, tmp_path, ["note", "it_known", "--note", "正常笔记"])
    assert result.exit_code == 0, result.output

    store = KnowledgeStore(_user_db(tmp_path))
    try:
        row = store.get("it_known")
        assert row is not None
        assert row.note == "正常笔记"
    finally:
        store.close()


def test_mark_unknown_item_id_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _invoke(monkeypatch, tmp_path, ["mark", "it_missing", "--status", "read"])
    assert result.exit_code != 0
    assert "未找到 item_id" in result.output
    assert not _user_db(tmp_path).exists()


def test_export_command_writes_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_daily(
        tmp_path,
        "2026-10-18",
        items={
            "it_a": _daily_item("Agent Alpha", "https://e/a"),
            "it_b": _daily_item("Beta Tool", "https://e/b"),
        },
        comments=[{"item_id": "it_a", "why": "因为重要"}],
        sections=[{"name": "开源项目", "item_ids": ["it_a", "it_b"]}],
    )
    assert _invoke(monkeypatch, tmp_path, ["note", "it_a", "--note", "导出笔记"]).exit_code == 0

    out = tmp_path / "out"
    result = _invoke(monkeypatch, tmp_path, ["export", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "导出完成" in result.output
    assert (out / "index.md").is_file()
    assert (out / "my-notes.md").is_file()
    assert (out / "topics" / "open-source-2026-10.md").is_file()
    assert "导出笔记" in (out / "my-notes.md").read_text(encoding="utf-8")
