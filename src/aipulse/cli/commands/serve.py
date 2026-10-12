"""serve 命令（占位）。

真实实现见 Roadmap；此处只注册命令树，保证 `aipulse --help` 完整可见。
"""

from __future__ import annotations

from aipulse.cli.commands._placeholder import placeholder_app

app = placeholder_app(
    "serve",
    "Web 看板（M4 实现，只读）",
    {
        "run": "启动本地服务：--port",
    },
)
