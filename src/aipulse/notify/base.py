"""通知抽象（v1.2：只实现 file 渠道，其余渠道仅预留）。

pipeline 只依赖 :class:`Notifier` 这个 Protocol，将来加邮件 / Telegram / 飞书
只需新增实现类并追加到 `notify.channels`，**编排代码零改动**。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class RenderedReport:
    """一次渲染的产物：文件名 → 文本内容。"""

    date: str
    files: dict[str, str] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class NotifyResult:
    """发送结果。"""

    channel: str
    ok: bool
    detail: str = ""


@runtime_checkable
class Notifier(Protocol):
    """通知渠道协议。"""

    name: str

    async def send(self, report: RenderedReport) -> NotifyResult:
        """发送报告；失败时返回 ok=False，由调用方记录（不得中断流水线）。"""
        ...


def get_notifier(name: str) -> Notifier:
    """按名字取通知器。当前只有 `file`（M0 已实现），其余明确抛错而不是静默。"""
    if name == "file":
        from aipulse.notify.file import FileNotifier

        return FileNotifier()
    raise NotImplementedError(
        f"通知渠道 {name!r} 尚未实现（v1.2 决策：只做 file，预留 email/telegram/feishu/desktop）"
    )
