"""trend 命令（占位）。

真实实现见 Roadmap；此处只注册命令树，保证 `aipulse --help` 完整可见。
"""

from __future__ import annotations

from aipulse.cli.commands._placeholder import placeholder_app

app = placeholder_app(
    "trend",
    "周期趋势长文（M5 实现）",
    {
        "run": "生成趋势长文：--range 7d|30d",
    },
)
