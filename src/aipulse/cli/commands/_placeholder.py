"""未实现命令的占位应用。

目的：让 `aipulse --help` 与各子命令 `--help` 从 M0 起就能看到完整命令树，
真正调用时才明确抛出 NotImplementedError（而不是静默什么都不做）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import typer


def placeholder_app(name: str, help_text: str, commands: Mapping[str, str]) -> typer.Typer:
    """生成一个占位子应用，`commands` 为 {子命令名: 帮助文本}。"""
    app = typer.Typer(name=name, help=help_text, no_args_is_help=True)

    for command_name, command_help in commands.items():

        def _make(cmd: str = command_name) -> Callable[..., Any]:
            def _run() -> None:
                raise NotImplementedError(
                    f"`aipulse {name} {cmd}` 尚未实现（当前进度：M0 骨架与数据探测）"
                )

            return _run

        app.command(command_name, help=command_help)(_make())

    return app
