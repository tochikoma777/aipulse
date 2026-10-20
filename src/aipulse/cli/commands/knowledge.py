"""`aipulse knowledge`：用户知识库笔记 CLI。

- `mark [item_id] [--url URL|--query 关键词] --status read|unread|skipped`
- `note [item_id] [--url URL|--query 关键词] --note "..."`；`--note ""` 清空
- `items [--query 关键词] [--day YYYY-MM-DD] [--limit N]`
- `list [--status X] [--with-notes] [--limit N]`
- `export [--out DIR] [--include-skipped]`

**item_id / --url / --query 三选一**；item_id 会查 daily_index 校验，
查不到默认报错（`--allow-unknown` 才允许写入孤儿笔记）。绝不用主库校验。
所有写操作只走 `user_session_for()`（user_data.db）。
"""

from __future__ import annotations

from datetime import date as date_type
from pathlib import Path
from typing import NoReturn

import typer
from rich.console import Console
from rich.table import Table

from aipulse.core.config import Settings, load_settings
from aipulse.knowledge.daily_index import (
    DailyIndex,
    IndexedItem,
    build_daily_index,
    find_by_url,
    search_by_query,
)
from aipulse.knowledge.export import export_knowledge
from aipulse.knowledge.models import KNOWLEDGE_STATUSES
from aipulse.knowledge.store import KnowledgeStore

app = typer.Typer(
    name="knowledge",
    help="用户知识库：给条目写笔记、标记阅读状态",
    no_args_is_help=True,
)
console = Console()

_NOTE_PREVIEW_LEN = 60


def _store(settings: Settings | None = None) -> KnowledgeStore:
    """默认用户库固定在 data/user_data.db（S1 已锁死路径）。"""
    return KnowledgeStore((settings or load_settings()).user_db_path())


def _reports_dir(settings: Settings) -> str:
    """与 pipeline/daily.py::report_dir_for() 保持一致：data/reports。"""
    return str(settings.data_dir() / "reports")


def _load_index(settings: Settings) -> DailyIndex:
    return build_daily_index(_reports_dir(settings))


def _fail(message: str) -> NoReturn:
    console.print(f"[red]✗ {message}[/red]")
    raise typer.Exit(code=2)


def _require_item_id(item_id: str) -> str:
    value = item_id.strip()
    if not value:
        _fail("item_id 不能为空")
    return value


def _require_status(status: str) -> str:
    if status not in KNOWLEDGE_STATUSES:
        allowed = " / ".join(KNOWLEDGE_STATUSES)
        _fail(f"非法状态：{status!r}；允许值：{allowed}")
    return status


def _require_one_selector(
    item_id: str | None,
    url: str | None,
    query: str | None,
) -> None:
    count = sum(value is not None for value in (item_id, url, query))
    if count == 0:
        _fail("必须提供 item_id、--url 或 --query 之一")
    if count > 1:
        _fail("item_id / --url / --query 只能三选一")


def _print_candidates(matches: list[IndexedItem]) -> None:
    table = Table(title=f"匹配到 {len(matches)} 条，未自动选择")
    table.add_column("item_id", no_wrap=True)
    table.add_column("标题", overflow="fold")
    table.add_column("URL", overflow="fold")
    table.add_column("日期", no_wrap=True)
    for item in matches:
        table.add_row(item.item_id, item.title or "—", item.url or "—", item.date or "—")
    console.print(table)


def _resolve_item_id(
    settings: Settings,
    item_id: str | None,
    url: str | None,
    query: str | None,
    *,
    allow_unknown: bool = False,
) -> str:
    """把用户可见的 URL/关键词解析成 item_id；多条候选绝不自动挑第一条。"""
    _require_one_selector(item_id, url, query)

    if item_id is not None:
        target = _require_item_id(item_id)
        if allow_unknown:
            return target
        index = _load_index(settings)
        if target not in index.items:
            _fail(f"未找到 item_id：{target}（如确认要写入未收录条目，加 --allow-unknown）")
        return target

    index = _load_index(settings)

    if url is not None:
        target = url.strip()
        if not target:
            _fail("--url 不能为空")
        found = find_by_url(index, target)
        if found is None:
            _fail(f"未找到 URL：{target}")
        return found.item_id

    needle = (query or "").strip()
    if not needle:
        _fail("--query 不能为空")
    matches = search_by_query(index, needle)
    if not matches:
        _fail(f"没有匹配条目：{needle!r}")
    if len(matches) > 1:
        _print_candidates(matches)
        _fail("命中多条，请用 item_id 或 --url 精确指定（未自动选择）")
    return matches[0].item_id


def _note_preview(note: str) -> str:
    text = note.replace("\n", " ").strip()
    if not text:
        return "—"
    if len(text) > _NOTE_PREVIEW_LEN:
        return text[: _NOTE_PREVIEW_LEN - 1] + "…"
    return text


@app.command("mark")
def mark_cmd(
    item_id: str | None = typer.Argument(None, help="条目 ID，例如 it_db643b160f4cefa8"),
    url: str | None = typer.Option(None, "--url", help="用日报里的原文 URL 定位条目"),
    query: str | None = typer.Option(None, "--query", help="用标题关键词定位条目"),
    status: str = typer.Option(..., "--status", help="read / unread / skipped"),
    allow_unknown: bool = typer.Option(
        False, "--allow-unknown", help="允许 item_id 不在 daily_index 中"
    ),
) -> None:
    """标记条目的阅读状态。"""
    target_status = _require_status(status)
    settings = load_settings()
    target_id = _resolve_item_id(settings, item_id, url, query, allow_unknown=allow_unknown)
    store = _store(settings)
    try:
        row = store.set_status(target_id, target_status)
    finally:
        store.close()
    console.print(f"✅ {row.item_id} → {row.status}")


@app.command("note")
def note_cmd(
    item_id: str | None = typer.Argument(None, help="条目 ID，例如 it_db643b160f4cefa8"),
    url: str | None = typer.Option(None, "--url", help="用日报里的原文 URL 定位条目"),
    query: str | None = typer.Option(None, "--query", help="用标题关键词定位条目"),
    note: str | None = typer.Option(
        None,
        "--note",
        help='笔记内容；传空字符串 "" 表示清空',
    ),
    allow_unknown: bool = typer.Option(
        False, "--allow-unknown", help="允许 item_id 不在 daily_index 中"
    ),
) -> None:
    """写入 / 覆盖条目笔记；空字符串清空。"""
    _require_one_selector(item_id, url, query)
    settings = load_settings()
    target_id = _resolve_item_id(settings, item_id, url, query, allow_unknown=allow_unknown)
    if note is None:
        console.print('[yellow]暂未实现，请用 --note "..." 直接写入[/yellow]')
        raise typer.Exit(code=1)

    if note == "":
        console.print("[yellow]提示：note 为空，将清空该条目的笔记[/yellow]")

    store = _store(settings)
    try:
        row = store.set_note(target_id, note)
    finally:
        store.close()

    if note == "":
        console.print(f"✅ 已清空笔记：{row.item_id}")
    else:
        console.print(f"✅ 已保存笔记：{row.item_id}")


@app.command("items")
def items_cmd(
    query: str | None = typer.Option(None, "--query", help="按标题关键词过滤"),
    day: str | None = typer.Option(None, "--day", help="只看某天：YYYY-MM-DD"),
    limit: int = typer.Option(20, "--limit", help="最多显示条数"),
) -> None:
    """列出可记笔记的条目：item_id / 标题 / URL / 板块 / 日期。"""
    if limit < 1:
        _fail("--limit 必须 ≥ 1")
    if day is not None:
        try:
            date_type.fromisoformat(day)
        except ValueError:
            _fail("--day 必须是 YYYY-MM-DD")

    settings = load_settings()
    index = _load_index(settings)

    if query is not None:
        needle = query.strip()
        if not needle:
            _fail("--query 不能为空")
        rows = search_by_query(index, needle)
        if not rows:
            _fail(f"没有匹配条目：{needle!r}")
    else:
        rows = sorted(
            index.items.values(),
            key=lambda item: (item.date, item.hot_score, item.title, item.item_id),
            reverse=True,
        )

    if day is not None:
        rows = [item for item in rows if item.date == day]

    if not rows:
        if query is not None:
            _fail("没有匹配条目")
        console.print("[dim]还没有可列出的条目。[/dim]")
        raise typer.Exit(code=0)

    rows = rows[:limit]
    table = Table(title=f"可记笔记的条目（{len(rows)} 条）")
    table.add_column("item_id", no_wrap=True)
    table.add_column("标题", overflow="fold")
    table.add_column("URL", overflow="fold")
    table.add_column("板块", no_wrap=True)
    table.add_column("日期", no_wrap=True)
    for item in rows:
        table.add_row(
            item.item_id,
            item.title or "—",
            item.url or "—",
            item.section or "—",
            item.date or "—",
        )
    console.print(table)


@app.command("list")
def list_cmd(
    status: str | None = typer.Option(None, "--status", help="按状态过滤"),
    with_notes: bool = typer.Option(False, "--with-notes", help="只显示有笔记的条目"),
    limit: int = typer.Option(20, "--limit", help="最多显示条数"),
) -> None:
    """按 updated_at 倒序查看笔记。"""
    if status is not None:
        _require_status(status)
    if limit < 1:
        _fail("--limit 必须 ≥ 1")

    settings = load_settings()
    store = _store(settings)
    try:
        rows = store.list(status=status, with_notes=with_notes, limit=limit)
    finally:
        store.close()

    if not rows:
        console.print("[dim]还没有符合条件的笔记。[/dim]")
        raise typer.Exit(code=0)

    index = _load_index(settings)
    table = Table(title=f"知识库笔记（{len(rows)} 条）")
    table.add_column("item_id", no_wrap=True)
    table.add_column("标题", overflow="fold")
    table.add_column("状态")
    table.add_column("笔记", overflow="fold")
    for row in rows:
        indexed = index.items.get(row.item_id)
        title = (indexed.title if indexed and indexed.title else "") or "(标题未知)"
        table.add_row(row.item_id, title, row.status, _note_preview(row.note))
    console.print(table)


@app.command("export")
def export_cmd(
    out: str | None = typer.Option(None, "--out", help="输出目录（默认 data/knowledge）"),
    include_skipped: bool = typer.Option(
        False, "--include-skipped", help="包含 status=skipped 的条目"
    ),
) -> None:
    """导出 Markdown 知识库：index.md / my-notes.md / topics/*.md。"""
    settings = load_settings()
    index = _load_index(settings)
    store = _store(settings)
    try:
        rows = store.all()
    finally:
        store.close()

    target = Path(out) if out else settings.data_dir() / "knowledge"
    result = export_knowledge(index, rows, target, include_skipped=include_skipped)

    console.print(
        f"✅ 导出完成：{result.total_items} 条"
        f"（带 why {result.with_why} / 带笔记 {result.with_notes}）"
    )
    console.print(f"输出：{result.out_dir}")
    for file in result.files:
        console.print(f"  - {file.path} · {file.item_count} 条 · {file.size_bytes} B")


__all__ = ["app"]
