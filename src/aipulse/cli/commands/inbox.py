"""`aipulse inbox`：手动投喂（v1.1 起微信 / X 内容的唯一合规入口）。

- `add <url> [--note ...]`：抓取标题 + 摘要入库（source=inbox）；抓不到也保留条目，
  标题退化为 URL——"本地唯一永不失效的兜底通道，外网全断时仍能走完整条链路"；
- `add-file <path>`：从本地 markdown / 纯文本批量导入（每行一条 URL，
  同一行 URL 之后的内容视为备注，`#` 开头为注释行）；
- `list`：查看已投喂条目。

采集器本体在 `collectors/inbox.py`；`data/inbox/*.md` 目录投喂由常规采集
（`aipulse collect --sources inbox`）自动扫描，与这里走同一条入库链路。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import Session

from aipulse.collectors.inbox import InboxCollector, parse_inbox_markdown
from aipulse.core.config import Settings, SourceConfig, load_settings, load_sources
from aipulse.schema.items import RawItem
from aipulse.store.db import engine_for, ensure_schema
from aipulse.store.repo_items import items_by_source, upsert_items
from aipulse.utils.http import HttpClient

app = typer.Typer(name="inbox", help="手动投喂：微信 / X 内容的唯一合规入口")
console = Console()

# 与 configs/sources.yaml 的 inbox 条目保持一致；配置缺失时用同值兜底
_DEFAULT_CFG = SourceConfig(weight=0.5, rate_limit="10/1s")


def _inbox_cfg() -> SourceConfig:
    return load_sources().sources.get("inbox") or _DEFAULT_CFG


def _make_http(settings: Settings, *, no_cache: bool) -> HttpClient:
    return HttpClient(
        connect_timeout_s=settings.http.timeout_connect_s,
        read_timeout_s=settings.http.timeout_read_s,
        max_retries=settings.http.max_retries,
        max_concurrency=settings.http.max_concurrency,
        cache_enabled=not no_cache,
        cache_path=None if no_cache else settings.cache_path() / "http.sqlite",
        cache_ttl_s=settings.http.cache_ttl_s,
        user_agent=settings.http.user_agent,
    )


def _persist(items: list[RawItem], db: str | None, settings: Settings) -> tuple[int, int]:
    target_db = Path(db) if db else settings.db_path()
    ensure_schema(target_db)
    engine = engine_for(target_db)
    try:
        with Session(engine, expire_on_commit=False) as session:
            return upsert_items(session, items)
    finally:
        engine.dispose()


@app.command("add")
def add_cmd(
    url: str = typer.Argument(..., help="要投喂的 URL"),
    note: str = typer.Option("", "--note", help="备注：你自己的观察，进入简报上下文"),
    db: str = typer.Option(None, "--db", help="数据库路径（默认 data/aipulse.db）"),
    no_cache: bool = typer.Option(False, "--no-cache", help="禁用 SQLite 响应缓存"),
) -> None:
    """投喂一条 URL：抓标题 + 摘要入库（source=inbox）。"""

    async def _run() -> tuple[int, int, str]:
        http = _make_http(load_settings(), no_cache=no_cache)
        try:
            item = await InboxCollector(_inbox_cfg(), http).item_from_url(url, note=note)
            if item is None:  # pragma: no cover - item_from_url 目前不会返回 None
                raise typer.Exit(code=1)
            inserted, _ = _persist([item], db, load_settings())
            return inserted, 0, item.title
        finally:
            await http.aclose()

    inserted, _, title = asyncio.run(_run())
    state = "新增" if inserted else "已存在"
    console.print(f"✅ 已入库（{state}）：{title}")
    if title == url:
        console.print("[yellow]⚠ 未能抓到标题，已用 URL 代替——条目不会丢[/yellow]")
    raise typer.Exit(code=0)


@app.command("add-file")
def add_file_cmd(
    path: str = typer.Argument(..., help="本地 markdown / 纯文本，每行一条 URL"),
    db: str = typer.Option(None, "--db", help="数据库路径（默认 data/aipulse.db）"),
    no_cache: bool = typer.Option(False, "--no-cache", help="禁用 SQLite 响应缓存"),
) -> None:
    """从本地文件批量导入（每行一条 URL，行内其余内容为备注）。"""
    note_path = Path(path)
    if not note_path.is_file():
        console.print(f"[red]✗ 文件不存在：{note_path}[/red]")
        raise typer.Exit(code=1)
    entries = parse_inbox_markdown(note_path.read_text(encoding="utf-8", errors="ignore"))
    if not entries:
        console.print("[yellow]文件里没有可识别的 URL（每行一条，# 开头为注释）[/yellow]")
        raise typer.Exit(code=0)

    async def _run() -> tuple[int, int]:
        http = _make_http(load_settings(), no_cache=no_cache)
        try:
            collector = InboxCollector(_inbox_cfg(), http)
            items = []
            for entry in entries:
                item = await collector.item_from_url(entry["url"], note=entry["note"])
                if item is not None:
                    items.append(item)
            return _persist(items, db, load_settings())
        finally:
            await http.aclose()

    inserted, updated = asyncio.run(_run())
    console.print(f"✅ 导入 {len(entries)} 条（新增 {inserted} / 已存在 {updated}）")
    raise typer.Exit(code=0)


@app.command("list")
def list_cmd(
    limit: int = typer.Option(20, "--limit", help="最多显示条数"),
    db: str = typer.Option(None, "--db", help="数据库路径（默认 data/aipulse.db）"),
) -> None:
    """查看已投喂条目。"""
    settings = load_settings()
    target_db = Path(db) if db else settings.db_path()
    ensure_schema(target_db)
    engine = engine_for(target_db)
    try:
        with Session(engine, expire_on_commit=False) as session:
            items = items_by_source(session, source="inbox", limit=limit)
    finally:
        engine.dispose()

    if not items:
        console.print('[dim]还没有投喂过条目。用法：aipulse inbox add <url> --note "..."[/dim]')
        raise typer.Exit(code=0)
    table = Table(title=f"已投喂 {len(items)} 条（source=inbox）")
    table.add_column("时间")
    table.add_column("标题")
    table.add_column("URL", overflow="fold")
    for item in items:
        table.add_row(item.published_at.strftime("%m-%d %H:%M"), item.title, item.url)
    console.print(table)
    raise typer.Exit(code=0)
