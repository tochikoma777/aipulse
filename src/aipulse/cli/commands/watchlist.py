"""`aipulse watchlist`：每日轻量核对 watchlist（T9 / P0-3）。

为什么单独一个命令：trend 现在是**月度**触发，而 watchlist 条目
`check_on = 窗口末日次日`——按月核对等于"提出一个月后才验"，那时
"次日是否在榜"早已无意义。条目层的核对必须短尺度、可每日跑。

本命令**只核对、不新建**：新建条目需要 trend 产物的「下期观察」段文本，
那是月度产物的事。传空 sections 给 `check_l3` 即只走核对分支。

零 LLM、零网络：只读 `data/reports/**/daily.json` 与各期 `watchlist.json`。
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from aipulse.analysis.cross_period import load_cross_period
from aipulse.core.config import load_settings
from aipulse.core.logging import configure_logging
from aipulse.reasoning.selfcheck import check_l3

app = typer.Typer(
    name="watchlist",
    help="每日核对 watchlist 条目是否仍在榜（离线，0 成本；只核对不新建）",
    invoke_without_command=True,
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    reports_dir: str | None = typer.Option(
        None, "--reports-dir", help="报告目录（默认 data/reports）"
    ),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
    write_state: bool = typer.Option(
        True, "--write-state/--no-write-state", help="是否写回核对结果"
    ),
) -> None:
    """核对到期 watchlist；退出码 0=正常，2=没有日报。"""
    if ctx.invoked_subcommand is not None:
        return

    settings = load_settings()
    configure_logging(settings.app.log_level, console_stderr=json_output)
    root = Path(reports_dir) if reports_dir else (Path(settings.app.data_dir) / "reports")
    index = load_cross_period(root)
    if not index.days:
        typer.echo(f"没有找到任何日报：{root}", err=True)
        raise typer.Exit(code=2)

    # 状态目录用 trend/ 本身：_load_state 会合并 trend/*/watchlist.json 的各期历史，
    # 写回的也是这个合并后的文件（各期目录保持只读，避免同日重跑写串）。
    state_dir = root / "trend"
    result = check_l3({}, index, state_dir=state_dir, write_state=write_state)

    payload = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
    if json_output:
        typer.echo(payload)
    else:
        mark = {"pass": "✅", "warn": "⚠️", "fail": "❌"}.get(result.verdict, "·")
        typer.echo(f"{mark} {result.layer} {result.name}: {result.summary}")

    typer.echo(
        f"[watchlist] {result.summary}",
        err=True,
    )
    for finding in result.findings:
        typer.echo(f"[watchlist] {finding}", err=True)
    typer.echo(f"[watchlist] 状态文件 {state_dir / 'watchlist.json'}", err=True)
