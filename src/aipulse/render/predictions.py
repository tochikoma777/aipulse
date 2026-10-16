"""当日新生成预言渲染（设计方案 §11：`predictions.md`）。

只呈现"系统今天说了什么"，判定结果在 `verdicts.md`（到期后）。
被校验器拒收的条目**也写进来**——拒收理由是预言质量的直接证据，
藏起来会让人误以为"每天都能稳定产出 5 条"。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from aipulse.store.models import Item, Prediction


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_predictions_markdown(
    rows: Sequence[Prediction],
    *,
    dropped: Sequence[dict[str, Any]] | None = None,
    generated_at: datetime | None = None,
    items: Mapping[str, Item] | None = None,
) -> str:
    """渲染当日新生成的预言；0 条时给出明确原因而不是空白。

    `items` 用于把 `evidence_item_ids` 翻成标题**写进报告**——证据留在库里就没法审，
    报告里看不到"这条预言到底依据了哪几条"，也就无从发现编造的 id。
    """
    out: list[str] = ["## 🔮 今日新生成的预言", ""]
    dropped = list(dropped or [])

    if not rows:
        out += [
            "本次运行没有新增预言。",
            "",
            "- `off` 档不会自动生成预言（手写才是 off 档核心：`aipulse predict add`）；",
            "- `hybrid` / `full` 档若本日条目不足或全部被可证伪校验拒收，也会是 0 条——"
            "宁可少，不可放水（设计方案 §19.5）。",
            "",
        ]
    else:
        out += [
            f"本次共生成 **{len(rows)}** 条可证伪预言：",
            "",
            "| 预言 | 类别 | 置信度 | 周期 | 到期日 | 判据 | 证据 id |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in rows:
            out.append(
                f"| {_escape(row.statement)} | {row.category} | {row.confidence:.2f} "
                f"| {row.horizon_days} 天 | {row.due_date.isoformat()} "
                f"| {_escape(row.falsifiable_criteria)} "
                f"| {' '.join(f'`{i}`' for i in row.evidence_item_ids)} |"
            )
        out.append("")

        if items:
            out += ["### 证据条目对照（人工核验用）", ""]
            for row in rows:
                for eid in row.evidence_item_ids:
                    item = items.get(eid)
                    title = _escape(item.title) if item is not None else "⚠️ 库里查不到该条目"
                    out.append(f"- `{eid}` → {title}")
            out.append("")
        out.append("> 这些预言的判定结果会在到期后自动出现在当天的 `verdicts.md`，并计入记分板。")
        out.append("")

    if dropped:
        out += [
            f"### 被可证伪校验拒收（{len(dropped)} 条）",
            "",
            "| 草案 | 拒收原因 |",
            "|---|---|",
        ]
        for entry in dropped:
            problems = entry.get("problems") or []
            joined = "；".join(str(p) for p in problems)
            out.append(f"| {_escape(str(entry.get('statement', '')))} | {_escape(joined)} |")
        out.append("")

    if generated_at is not None:
        out += ["---", "", f"_生成时间：{generated_at.isoformat()}_", ""]
    return "\n".join(out)


__all__ = ["render_predictions_markdown"]
