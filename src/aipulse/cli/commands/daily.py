"""`aipulse daily`：每日一条龙（collect → analyze → brief → render；M2）。"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

import typer
from rich.console import Console

from aipulse.core.config import load_settings
from aipulse.core.logging import configure_logging
from aipulse.core.timeutil import today_local
from aipulse.pipeline.daily import run_daily

app = typer.Typer(name="daily", help="每日一条龙流水线", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def run(
    date_str: str = typer.Option(None, "--date", help="日期 YYYY-MM-DD，默认今天"),
    since: str = typer.Option("24h", "--since", help="采集时间窗：24h / 7d / 30m"),
    skip_llm: bool = typer.Option(False, "--skip-llm", help="跳过 LLM（零花费）"),
    no_llm: bool = typer.Option(False, "--no-llm", help="同 --skip-llm（纯算法模式）"),
    no_collect: bool = typer.Option(False, "--no-collect", help="跳过采集，只做分析+简报"),
    db: str = typer.Option(None, "--db", help="数据库路径（默认 data/aipulse.db）"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出运行摘要"),
) -> None:
    """采集 → 打分/聚类/实体 → 简报 → 渲染落盘。"""
    if json_output:
        configure_logging(console_stderr=True)
    settings = load_settings()
    if date_str and date_str != "today":
        day = date.fromisoformat(date_str)
    else:
        day = today_local(settings.app.timezone)

    result = asyncio.run(
        run_daily(
            since=since,
            day=day,
            skip_llm=skip_llm or no_llm,
            no_collect=no_collect,
            db_path=Path(db) if db else None,
        )
    )

    console = Console()
    if json_output:
        console.print_json(json.dumps(result.meta, ensure_ascii=False))
        raise typer.Exit(code=0)
    console.print(
        f"[bold]日报完成[/bold] {result.day.isoformat()} · 模式 {result.mode.value}"
        f" · 条目 {result.analysis.get('items', 0)} · 主题 {result.analysis.get('topics', 0)}"
    )
    console.print(f"报告目录：[cyan]{result.report_dir}[/cyan]")
    console.print(f"文件：{', '.join(result.files)}")
    raise typer.Exit(code=0)
