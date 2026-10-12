"""sources 命令（占位）。

真实实现见 Roadmap；此处只注册命令树，保证 `aipulse --help` 完整可见。
"""

from __future__ import annotations

from aipulse.cli.commands._placeholder import placeholder_app

app = placeholder_app(
    "sources",
    "数据源管理（M1 实现）",
    {
        "list": "列出数据源",
        "enable": "启用",
        "disable": "禁用",
    },
)
