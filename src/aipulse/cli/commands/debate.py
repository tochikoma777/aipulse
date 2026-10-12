"""debate 命令（占位）。

真实实现见 Roadmap；此处只注册命令树，保证 `aipulse --help` 完整可见。
"""

from __future__ import annotations

from aipulse.cli.commands._placeholder import placeholder_app

app = placeholder_app(
    "debate",
    "多角色辩论（M5 实现）",
    {
        "run": "就一个话题发起辩论：--topic / --rounds",
    },
)
