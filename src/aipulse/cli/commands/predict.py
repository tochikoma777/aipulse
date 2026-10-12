"""predict 命令（占位）。

真实实现见 Roadmap；此处只注册命令树，保证 `aipulse --help` 完整可见。
"""

from __future__ import annotations

from aipulse.cli.commands._placeholder import placeholder_app

app = placeholder_app(
    "predict",
    "★ 预言系统（M3 实现）",
    {
        "run": "自动生成当日预言",
        "add": "手写预言（不带参数进入交互式向导）",
        "list": "列出预言",
        "verify": "到期验证（量化判据自动判定）",
        "review": "人工判定闭环",
    },
)
