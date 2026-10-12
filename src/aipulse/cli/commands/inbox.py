"""inbox 命令（占位）。

真实实现见 Roadmap；此处只注册命令树，保证 `aipulse --help` 完整可见。
"""

from __future__ import annotations

from aipulse.cli.commands._placeholder import placeholder_app

app = placeholder_app(
    "inbox",
    "手动投喂（M1 实现）",
    {
        "add": "添加 URL",
        "add-file": "从本地文件批量导入",
    },
)
