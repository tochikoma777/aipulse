"""到期验证结果渲染（设计方案 §11：`verdicts.md`，当日到期的验证结果）。

只呈现事实，不做任何判断——判定逻辑在 `reasoning/verifier.py`，
这里保证「报告即数据库」：验证结果随报告一起 commit 回仓库，可离线追溯。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from aipulse.store.models import Prediction

_VERDICT_MARKS = {"hit": "✅ 命中", "partial": "🟡 部分", "miss": "❌ 落空"}
_STATUS_MARKS = {"unverifiable": "⏭ 无法验证", "pending": "⏳ 待验证"}


def _mark(prediction: Prediction) -> str:
    if prediction.verdict:
        return _VERDICT_MARKS.get(prediction.verdict, prediction.verdict)
    return _STATUS_MARKS.get(prediction.status, prediction.status)


def _who(prediction: Prediction) -> str:
    return "人工" if prediction.verified_by == "human" else "系统"


def render_verdicts_markdown(
    rows: Sequence[Prediction], *, generated_at: datetime | None = None
) -> str:
    """渲染本次运行的验证结果；无到期预言时给一行说明而不是空文件。"""
    out: list[str] = ["## 🧭 到期验证结果", ""]
    if not rows:
        out += ["本次运行没有到期的预言需要验证。", ""]
        return "\n".join(out)

    out += [
        f"本次共处理 **{len(rows)}** 条到期预言。",
        "",
        "| 预言 | 判定 | 置信度 | 来源 | 判定方 | 依据 |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        statement = (row.statement or "").replace("|", "\\|")
        note = (row.verdict_note or "").replace("|", "\\|").replace("\n", " ")
        if len(note) > 120:
            note = note[:120] + "…"
        out.append(
            f"| {statement} | {_mark(row)} | {row.confidence:.2f} | {row.origin} "
            f"| {_who(row)} | {note or '—'} |"
        )
    out.append("")
    if generated_at is not None:
        out += ["---", "", f"_生成时间：{generated_at.isoformat()}_", ""]
    return "\n".join(out)


__all__ = ["render_verdicts_markdown"]
