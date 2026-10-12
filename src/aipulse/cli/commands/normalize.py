"""normalize 命令（占位）。

真实实现见 Roadmap；此处只注册命令树，保证 `aipulse --help` 完整可见。
"""

from __future__ import annotations

from aipulse.cli.commands._placeholder import placeholder_app

app = placeholder_app(
    "normalize",
    "归一化与去重（M1 实现）",
    {
        "run": "URL 规范化 + 三级去重",
    },
)
