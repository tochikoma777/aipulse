"""collect 命令（占位）。

真实实现见 Roadmap；此处只注册命令树，保证 `aipulse --help` 完整可见。
"""

from __future__ import annotations

from aipulse.cli.commands._placeholder import placeholder_app

app = placeholder_app(
    "collect",
    "采集各数据源（M1 实现）",
    {
        "run": "执行采集：--sources / --since / --dry-run / --no-cache",
    },
)
