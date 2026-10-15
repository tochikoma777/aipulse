"""CLI 入口（`aipulse`）。

已实现：`init` / `doctor` / `serve`，以及 `collect` / `analyze` / `brief` / `daily` /
`predict` / `stats`（各自的 app 在 commands/ 内实现）。
未实现的子命令由 `placeholder_app()` 占位——调用时显式抛 `NotImplementedError`，
但 `--help` 中可见（刻意的，不是漏实现）。
"""

from __future__ import annotations

import typer

from aipulse.cli.commands import (
    analyze,
    brief,
    collect,
    daily,
    debate,
    inbox,
    normalize,
    predict,
    search,
    sources,
    stats,
    topics,
    trend,
)
from aipulse.cli.commands.doctor import doctor_command
from aipulse.cli.commands.init import init_command
from aipulse.cli.commands.serve import app as serve_app

app = typer.Typer(
    name="aipulse",
    help="AI 脉搏：每日采集 AI 领域热点，给出可回测的推演与预言。",
    no_args_is_help=True,
    add_completion=False,
)

# 已实现
app.command("init", help="初始化：建库 + 生成配置骨架 + 创建目录")(init_command)
app.command("doctor", help="环境体检：Python / LLM key / 代理 / 磁盘 / 数据库 / 各源连通性")(
    doctor_command
)
# Web 看板（M4，只读）：`aipulse serve --port 8000`
app.add_typer(serve_app)

# 待实现（占位，--help 可见）
for _sub in (
    collect,
    normalize,
    analyze,
    brief,
    predict,
    debate,
    trend,
    daily,
    stats,
    topics,
    search,
    inbox,
    sources,
):
    app.add_typer(_sub.app)


if __name__ == "__main__":  # pragma: no cover
    app()
