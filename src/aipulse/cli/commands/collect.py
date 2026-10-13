"""`aipulse collect`：采集全部（或指定）数据源。

- 单源异常隔离：一个源挂了不影响其他源，退出码仍为 0；
- v1.4：`actions_only` 的源在本地跳过（`skipped_offline`，不计失败）；
- 支持 `--json`，便于脚本消费。
"""

from __future__ import annotations

import asyncio
import json

import typer
from rich.console import Console
from rich.table import Table

from aipulse.core.config import is_actions_env
from aipulse.core.logging import configure_logging
from aipulse.pipeline.collect import (
    STATUS_FAILED,
    STATUS_OK,
    STATUS_SKIPPED_OFFLINE,
    run_collect,
)

app = typer.Typer(
    name="collect",
    help="采集数据源：--sources / --since / --dry-run / --no-cache",
    invoke_without_command=True,
)

_MARKS = {
    STATUS_OK: "[green]✅[/green]",
    "degraded": "[yellow]⚠️[/yellow]",
    STATUS_FAILED: "[red]❌[/red]",
    STATUS_SKIPPED_OFFLINE: "[blue]⏸[/blue]",
    "skipped_disabled": "[dim]⏸[/dim]",
}


@app.callback(invoke_without_command=True)
def run(
    sources: str = typer.Option(None, "--sources", help="逗号分隔的源名，默认全部启用的源"),
    since: str = typer.Option("24h", "--since", help="时间窗：24h / 7d / 30m"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只采集不写库"),
    no_cache: bool = typer.Option(False, "--no-cache", help="禁用 SQLite 响应缓存"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
    db: str = typer.Option(None, "--db", help="覆盖数据库路径"),
) -> None:
    """执行采集。"""
    if json_output:
        # stdout 必须只有 JSON：日志改走 stderr，脚本才能安全地管道消费
        configure_logging(console_stderr=True)

    console = Console()
    wanted = [s.strip() for s in sources.split(",")] if sources else None
    result = asyncio.run(
        run_collect(sources=wanted, since=since, dry_run=dry_run, no_cache=no_cache, db_path=db)
    )

    if json_output:
        console.print_json(json.dumps(result.to_dict(), ensure_ascii=False, default=str))
        raise typer.Exit(code=0)

    console.print(
        f"[bold]采集窗口[/bold]: 最近 {since}"
        f"（{'Actions 环境' if is_actions_env() else '本地环境'}）"
    )
    table = Table(title="采集结果", header_style="bold cyan")
    table.add_column("源")
    table.add_column("状态", justify="center")
    table.add_column("条数", justify="right")
    table.add_column("耗时s", justify="right")
    table.add_column("说明")
    for r in result.results:
        table.add_row(
            r.display_name or r.source,
            _MARKS.get(r.status, r.status),
            str(r.item_count),
            f"{r.elapsed_s:.1f}",
            r.note or r.error or "",
        )
    console.print(table)

    dedup = result.dedup
    console.print(
        f"[bold]合计[/bold] 去重后 {len(result.items)} 条"
        + (
            f"（L1 丢弃 {dedup.l1_dropped} / L2 合并 {dedup.l2_merged}"
            f" / L3 合并 {dedup.l3_merged}）"
            if dedup
            else ""
        )
    )
    if result.persisted:
        console.print(f"[dim]落库：{result.persisted}[/dim]")
    if result.failed_sources:
        console.print(
            f"[yellow]{len(result.failed_sources)} 个源失败，其余源已完成（退出码 0）[/yellow]"
        )
    # 单源失败绝不改变退出码：这是"故障隔离"对外契约的一部分
    raise typer.Exit(code=0)
