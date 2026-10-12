"""daily 命令（占位）。

真实实现见 Roadmap；此处只注册命令树，保证 `aipulse --help` 完整可见。
"""

from __future__ import annotations

from aipulse.cli.commands._placeholder import placeholder_app

app = placeholder_app(
    "daily",
    "每日一条龙流水线（M2 实现）",
    {
        "run": "collect→normalize→analyze→brief→predict→verify→render",
    },
)
