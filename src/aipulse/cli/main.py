"""CLI 入口（`aipulse`）。

M0：注册全部子命令，未实现的用 `NotImplementedError` 占位（但 `--help` 中可见）；
已实现 `init` 与 `doctor`。
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
    serve,
    sources,
    stats,
    topics,
    trend,
)
from aipulse.cli.commands.doctor import doctor_command
from aipulse.cli.commands.init import init_command

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
    serve,
):
    app.add_typer(_sub.app)


if __name__ == "__main__":  # pragma: no cover
    app()
