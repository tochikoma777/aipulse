"""stats 命令（占位）。

真实实现见 Roadmap；此处只注册命令树，保证 `aipulse --help` 完整可见。
"""

from __future__ import annotations

from aipulse.cli.commands._placeholder import placeholder_app

app = placeholder_app(
    "stats",
    "统计与记分板（M3 实现）",
    {
        "run": "命中率 / Brier / 校准曲线",
        "predictions": "预言统计",
    },
)
