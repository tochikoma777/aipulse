"""`aipulse analyze`：热度打分 + 聚类 + 实体统计（M2，纯算法，零成本）。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from sqlmodel import Session

from aipulse.core.config import Settings, load_settings
from aipulse.core.logging import configure_logging
from aipulse.core.timeutil import today_local
from aipulse.pipeline.daily import analyze_day
from aipulse.store.db import engine_for, ensure_schema

app = typer.Typer(name="analyze", help="热度打分 / 聚类 / 实体统计", invoke_without_command=True)


def _parse_day(value: str | None, settings: Settings) -> date:
    if not value or value == "today":
        return today_local(settings.app.timezone)
    return date.fromisoformat(value)


@app.callback(invoke_without_command=True)
def run(
    date_str: str = typer.Option(None, "--date", help="日期 YYYY-MM-DD，默认今天"),
    db: str = typer.Option(None, "--db", help="数据库路径（默认 data/aipulse.db）"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """对当日（或指定日）采集的条目打分、聚类并统计实体。"""
    if json_output:
        configure_logging(console_stderr=True)
    settings = load_settings()
    day = _parse_day(date_str, settings)
    target_db = Path(db) if db else settings.db_path()
    ensure_schema(target_db)
    engine = engine_for(target_db)
    with Session(engine) as session:
        stats = analyze_day(session, day=day)
    engine.dispose()

    console = Console()
    if json_output:
        console.print_json(__import__("json").dumps({"day": day.isoformat(), **stats}))
        raise typer.Exit(code=0)
    console.print(f"[bold]分析完成[/bold] {day.isoformat()}：")
    console.print(
        f"条目 {stats['items']} · 已打分 {stats['scored']} · "
        f"主题 {stats['topics']} · 实体 {stats['entities']}"
    )
    raise typer.Exit(code=0)
