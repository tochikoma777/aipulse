"""`aipulse inbox` CLI 单测：add / add-file / list。

覆盖 v1.1 核心契约：**抓不到也要保留条目**（标题退化为 URL），
"本地唯一永不失效的兜底通道"不能因为网络问题丢内容。
"""

from __future__ import annotations

from pathlib import Path

import httpx
import respx
from sqlmodel import Session
from typer.testing import CliRunner

from aipulse.cli.main import app
from aipulse.store.db import engine_for
from aipulse.store.repo_items import items_by_source

runner = CliRunner()

_HTML = (
    '<html><head><title>示例文章</title><meta name="description" content="摘要内容"></head></html>'
)


def _query_inbox(db: Path) -> list:
    engine = engine_for(db)
    try:
        with Session(engine, expire_on_commit=False) as session:
            return items_by_source(session, source="inbox")
    finally:
        engine.dispose()


@respx.mock
def test_inbox_add_inserts_item(tmp_path: Path):
    respx.get("https://example.com/a").mock(return_value=httpx.Response(200, text=_HTML))
    db = tmp_path / "aipulse.db"
    result = runner.invoke(
        app,
        [
            "inbox",
            "add",
            "https://example.com/a",
            "--note",
            "值得追踪",
            "--db",
            str(db),
            "--no-cache",
        ],
    )
    assert result.exit_code == 0, result.output
    items = _query_inbox(db)
    assert len(items) == 1
    assert items[0].title == "示例文章"
    assert "已入库" in result.output


@respx.mock
def test_inbox_add_survives_fetch_failure(tmp_path: Path):
    """抓不到标题不能丢条目：标题退化为 URL，仍然入库。"""
    respx.get("https://broken.example/x").mock(side_effect=httpx.ConnectTimeout)
    db = tmp_path / "aipulse.db"
    result = runner.invoke(
        app,
        [
            "inbox",
            "add",
            "https://broken.example/x",
            "--note",
            "断网也留痕",
            "--db",
            str(db),
            "--no-cache",
        ],
    )
    assert result.exit_code == 0, result.output
    items = _query_inbox(db)
    assert len(items) == 1
    assert items[0].title == "https://broken.example/x"
    assert items[0].summary == "断网也留痕"
    assert "URL 代替" in result.output


def test_inbox_add_idempotent(tmp_path: Path):
    """同一 URL 重复投喂只入库一次（upsert 语义）。"""
    db = tmp_path / "aipulse.db"
    args = ["inbox", "add", "https://example.com/dup", "--db", str(db), "--no-cache"]
    with respx.mock:
        respx.get("https://example.com/dup").mock(return_value=httpx.Response(200, text=_HTML))
        assert runner.invoke(app, args).exit_code == 0
        result = runner.invoke(app, args)
    assert result.exit_code == 0
    assert "已存在" in result.output
    assert len(_query_inbox(db)) == 1


@respx.mock
def test_inbox_add_file_batch_import(tmp_path: Path):
    respx.get(url__regex=r"https://example\.com/").mock(
        return_value=httpx.Response(200, text=_HTML)
    )
    note_file = tmp_path / "notes.md"
    note_file.write_text(
        "# 我的观察\nhttps://example.com/a 第一条\nhttps://example.com/b 第二条\n",
        encoding="utf-8",
    )
    db = tmp_path / "aipulse.db"
    result = runner.invoke(
        app, ["inbox", "add-file", str(note_file), "--db", str(db), "--no-cache"]
    )
    assert result.exit_code == 0, result.output
    assert "导入 2 条" in result.output
    assert len(_query_inbox(db)) == 2


def test_inbox_add_file_without_url_is_noop(tmp_path: Path):
    note_file = tmp_path / "empty.md"
    note_file.write_text("# 只有注释没有 URL\n", encoding="utf-8")
    result = runner.invoke(app, ["inbox", "add-file", str(note_file)])
    assert result.exit_code == 0
    assert "没有可识别的 URL" in result.output


def test_inbox_list_empty_and_after_add(tmp_path: Path):
    db = tmp_path / "aipulse.db"
    result = runner.invoke(app, ["inbox", "list", "--db", str(db)])
    assert result.exit_code == 0
    assert "还没有投喂过条目" in result.output

    with respx.mock:
        respx.get("https://example.com/c").mock(return_value=httpx.Response(200, text=_HTML))
        assert (
            runner.invoke(
                app, ["inbox", "add", "https://example.com/c", "--db", str(db), "--no-cache"]
            ).exit_code
            == 0
        )
    result = runner.invoke(app, ["inbox", "list", "--db", str(db)])
    assert result.exit_code == 0
    assert "示例文章" in result.output


def test_inbox_help_shows_subcommands():
    result = runner.invoke(app, ["inbox", "--help"])
    assert result.exit_code == 0
    for sub in ("add", "add-file", "list"):
        assert sub in result.output
