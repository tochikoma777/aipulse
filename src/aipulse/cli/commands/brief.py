"""`aipulse brief`：生成每日简报（读库，不做采集/分析；M2）。"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from sqlmodel import Session

from aipulse.analysis.entities import count_entities
from aipulse.analysis.signals import repo_star_snapshots
from aipulse.core.config import RunMode, Settings, load_settings
from aipulse.core.logging import configure_logging
from aipulse.core.timeutil import day_window, today_local
from aipulse.llm.base import build_client
from aipulse.pipeline.daily import report_dir_for
from aipulse.reasoning.brief import generate_brief
from aipulse.render.json_out import render_json
from aipulse.render.markdown import render_markdown
from aipulse.store.db import engine_for, ensure_schema
from aipulse.store.repo_items import (
    list_entities,
    list_items_collected,
    list_signals,
    list_topics,
)

app = typer.Typer(name="brief", help="生成每日简报", invoke_without_command=True)


def _parse_day(value: str | None, settings: Settings) -> date:
    if not value or value == "today":
        return today_local(settings.app.timezone)
    return date.fromisoformat(value)


@app.callback(invoke_without_command=True)
def run(
    date_str: str = typer.Option(None, "--date", help="日期 YYYY-MM-DD，默认今天"),
    top_n: int = typer.Option(None, "--top-n", help="简报条目数（默认读配置 daily_top_n）"),
    skip_llm: bool = typer.Option(False, "--skip-llm", help="跳过 LLM，产出数据版简报"),
    no_llm: bool = typer.Option(False, "--no-llm", help="同 --skip-llm（纯算法模式）"),
    db: str = typer.Option(None, "--db", help="数据库路径（默认 data/aipulse.db）"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出 daily.json 到 stdout"),
) -> None:
    """从库中读取当日数据生成简报，并落盘 brief.md / daily.json / meta.json。"""
    if json_output:
        configure_logging(console_stderr=True)
    settings = load_settings()
    day = _parse_day(date_str, settings)
    skip = skip_llm or no_llm
    mode = RunMode.OFF if skip else settings.effective_mode()
    target_db = Path(db) if db else settings.db_path()
    ensure_schema(target_db)
    engine = engine_for(target_db)

    with Session(engine, expire_on_commit=False) as session:
        start, end = day_window(day)
        items = list_items_collected(session, since=start, until=end)
        topics = list_topics(session, day)
        entity_counts = count_entities(list_entities(session, day))
        repo_stars = repo_star_snapshots(
            list_signals(session),
            min_window_hours=settings.signals.min_velocity_window_hours,
            lookback_days=settings.signals.repo_lookback_days,
        )
        client = build_client(settings, engine=engine)
        output = asyncio.run(
            generate_brief(
                client=client,
                settings=settings,
                items=items,
                topics=topics,
                entity_counts=entity_counts,
                day=day,
                mode=mode,
                skip_llm=skip,
                top_n=top_n,
            )
        )
    engine.dispose()

    meta = {"mode": mode.value, "day": day.isoformat(), **output.meta}
    report_dir = report_dir_for(settings, day)
    report_dir.mkdir(parents=True, exist_ok=True)
    brief_md = render_markdown(
        output.brief,
        output.items,
        meta,
        max_items_per_section=settings.brief.max_items_per_section,
        repo_stars=repo_stars,
        velocity_board_enabled=settings.brief.velocity_board_enabled,
        velocity_board_top_n=settings.brief.velocity_board_top_n,
    )
    (report_dir / "brief.md").write_text(brief_md, encoding="utf-8")
    (report_dir / "daily.json").write_text(
        render_json(output.brief, output.items, meta), encoding="utf-8"
    )
    (report_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    console = Console()
    if json_output:
        console.print_json(render_json(output.brief, output.items, meta))
        raise typer.Exit(code=0)
    console.print(f"[bold]简报已生成[/bold] {day.isoformat()} → {report_dir}")
    console.print(brief_md)
    raise typer.Exit(code=0)
