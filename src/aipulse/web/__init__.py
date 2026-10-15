"""Web 看板（M4）：FastAPI + Jinja2 + HTMX 的只读界面。

对外只暴露 `create_app()`；CLI 入口见 `aipulse.cli.commands.serve`。
本包**不包含任何写操作**（详见 `web/data.py` 的只读引擎说明）。
"""

from __future__ import annotations

from aipulse.web.app import create_app

__all__ = ["create_app"]
