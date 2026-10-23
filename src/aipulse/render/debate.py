"""debate 的人类层渲染（M5 S5）。

**只改容器，内容必须保住。** 四方交锋里的真判断（如"用被质疑的指标去验真 = 没验"）
是本功能最有价值的部分，改造只是把它们从长篇散文搬进结论卡片、交锋矩阵与证伪表格。

与 `render/weekly.py` 同一套规则：正文零裸 ID（改 `[标题](url)`）、
免责与过程进 `<details>`、ID 收进文末「数据溯源」。
"""

from __future__ import annotations

from aipulse.analysis.cross_period import CrossPeriodIndex
from aipulse.render.weekly import cut, esc, item_of, link_of, linkify
from aipulse.schema.debate import DebateReport, Falsification


def _links(index: CrossPeriodIndex | None, ids: list[str], limit: int = 3) -> str:
    if index is None:
        return ""
    out = [link_of(index, item_id) for item_id in ids[:limit]]
    return "、".join(out)


def _persona_name(report: DebateReport, persona: str) -> str:
    for stmt in report.statements:
        if stmt.persona == persona:
            return stmt.persona_label or persona
    return persona


def _falsification_table(
    rows: list[tuple[str, Falsification]], index: CrossPeriodIndex | None
) -> list[str]:
    if not rows:
        return []
    lines = [
        "| 断言 | 观测什么 | 成立 → | 不成立 → |",
        "|---|---|---|---|",
    ]
    for source, f in rows:
        claim = esc(cut(f.claim, 40)) or source
        lines.append(
            f"| {claim} | {esc(cut(f.observable, 46))} "
            f"| {esc(cut(f.if_observed, 30))} | {esc(cut(f.if_not_observed, 30))} |"
        )
    lines.append("")
    if index is not None:
        cited: dict[str, str] = {}
        for _, f in rows:
            for item_id in f.target_item_ids:
                found = item_of(index, item_id)
                cited[item_id] = found.title if found else "（不在窗口内）"
        if cited:
            lines.append("依据：" + "、".join(link_of(index, i) for i in sorted(cited)))
            lines.append("")
    return lines


def render_debate(report: DebateReport, index: CrossPeriodIndex | None = None) -> str:
    """人类版辩论产物。`index` 用于把 item_id 渲染成 `[标题](url)`。"""
    mod = report.moderator
    lines: list[str] = [f"# AI 脉搏 · 多角色辩论：{report.topic}", ""]
    lines.append(
        f"> 取数窗口 {report.window_start} → {report.window_end}（{report.window_days} 天）"
        f"　证据 {len(report.evidence_lines)} 条　调用 {report.llm_calls}/{report.attempts}"
        f"　成本 ¥{report.cost_cny:.4f}　可用证伪 {report.falsification_usable}"
        f"/{report.falsification_total}"
    )
    lines.append("")

    if report.failures:
        lines.append("## ⛔ 本次辩论判失败")
        lines.append("")
        for item in report.failures:
            lines.append(f"- {item}")
        lines.append("")

    # ── 结论卡片（置信度显眼：低置信度是诚实，不是缺陷）────────────
    lines.append("## 🧭 结论卡片")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 整体置信度 | **{mod.overall_confidence:.2f}** |")
    lines.append(f"| 已达成共识 | {len(mod.consensus)} 条 |")
    lines.append(f"| 关键分歧 | {len(mod.key_disagreements)} 条 |")
    lines.append(f"| 可用证伪 | {report.falsification_usable}/{report.falsification_total} |")
    lines.append("")

    if mod.consensus:
        lines.append("### ✅ 共识")
        lines.append("")
        for item in mod.consensus:
            shown = linkify(index, item.strip()) if index is not None else item.strip()
            lines.append(f"- {shown}")
        lines.append("")
    if mod.key_disagreements:
        lines.append("### ⚔️ 关键分歧")
        lines.append("")
        for item in mod.key_disagreements:
            lines.append(f"- {item.strip()}")
        lines.append("")

    # ── 四方立场：一句话 + 3 条论据 + 折叠全文 ──────────────────────
    lines.append("## 🗣️ 四方立场")
    lines.append("")
    for stmt in report.statements:
        name = stmt.persona_label or stmt.persona
        lines.append(f"### {name}")
        lines.append("")
        if stmt.invalid_reason:
            lines.append(f"> 本方陈述无效：{stmt.invalid_reason}")
            lines.append("")
            continue
        lines.append(f"**立场**：{stmt.stance.strip()}")
        lines.append("")
        if stmt.key_points:
            for point in stmt.key_points[:3]:
                lines.append(f"- {point.strip()}")
            lines.append("")
        links = _links(index, stmt.cited_item_ids)
        if links:
            lines.append(f"依据：{links}")
            lines.append("")
        if stmt.reasoning.strip():
            lines.append("<details>")
            lines.append(f"<summary>展开 {name} 全文</summary>")
            lines.append("")
            lines.append(
                linkify(index, stmt.reasoning.strip())
                if index is not None
                else stmt.reasoning.strip()
            )
            lines.append("")
            lines.append("</details>")
            lines.append("")

    # ── 交锋矩阵：Round 2 的精华换容器 ──────────────────────────────
    matrix: list[str] = []
    for resp in report.cross:
        if not resp.valid:
            continue
        for ch in resp.challenges:
            if not (ch.point or ch.target):
                continue
            target = _persona_name(report, ch.target) if ch.target else "（未点名）"
            point = esc(cut(ch.point, 60))
            outcome = ch.outcome.strip() or "—"
            who = resp.persona_label or resp.persona
            matrix.append(f"| {who} → {esc(target)} | {point} | {esc(outcome)} |")
    if matrix:
        lines.append("## ⚔️ 交锋矩阵（Round 2）")
        lines.append("")
        lines.append("| 质疑方 → 被质疑方 | 核心一击 | 结果 |")
        lines.append("|---|---|---|")
        lines.extend(matrix)
        lines.append("")
    concessions = [
        (resp, c) for resp in report.cross if resp.valid for c in resp.concessions if c.strip()
    ]
    if concessions:
        lines.append("<details>")
        lines.append("<summary>让步与修正后立场（点击展开）</summary>")
        lines.append("")
        for resp, text in concessions:
            who = resp.persona_label or resp.persona
            shown = linkify(index, text.strip()) if index is not None else text.strip()
            lines.append(f"- **{who}** 让步：{shown}")
        for resp in report.cross:
            if resp.valid and resp.revised_stance.strip():
                who = resp.persona_label or resp.persona
                shown = (
                    linkify(index, resp.revised_stance.strip())
                    if index is not None
                    else resp.revised_stance.strip()
                )
                lines.append(f"- **{who}** 修正后：{shown}")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # ── 证伪条件：表格 ──────────────────────────────────────────────
    rows: list[tuple[str, Falsification]] = []
    for stmt in report.statements:
        if stmt.valid and stmt.falsification.observable:
            rows.append((stmt.persona_label or stmt.persona, stmt.falsification))
    for f in mod.falsifications:
        if f.observable:
            rows.append(("主持人", f))
    if rows:
        lines.append("## 🎯 什么证据会让我改变判断")
        lines.append("")
        lines.extend(_falsification_table(rows, index))

    if mod.actionable_conclusions:
        lines.append("## ✅ 可执行结论")
        lines.append("")
        for item in mod.actionable_conclusions:
            shown = linkify(index, item.strip()) if index is not None else item.strip()
            lines.append(f"- {shown}")
        lines.append("")

    # ── 机器层细节：折叠 ────────────────────────────────────────────
    bad = [
        (stmt.persona_label or stmt.persona, stmt.falsification)
        for stmt in report.statements
        if stmt.falsification.violations
    ] + [("主持人", f) for f in mod.falsifications if f.violations]
    if bad or report.truncated:
        lines.append("<details>")
        lines.append("<summary>⚠️ 不可用证伪条件与运行异常（点击展开）</summary>")
        lines.append("")
        for name, f in bad:
            lines.append(f"- **{name}**：{esc(cut(f.observable, 40))}")
            for v in f.violations:
                lines.append(f"  - {v}")
        for item in report.truncated:
            lines.append(f"- 截断：{item}")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # ── 数据溯源（裸 ID 只在这里）───────────────────────────────────
    cited: dict[str, str] = {}
    if index is not None:
        for stmt in report.statements:
            for item_id in stmt.cited_item_ids:
                found = item_of(index, item_id)
                cited[item_id] = found.title if found else "（不在窗口内）"
        for resp in report.cross:
            for item_id in resp.cited_item_ids:
                found = item_of(index, item_id)
                cited[item_id] = found.title if found else "（不在窗口内）"
    if cited:
        lines.append("---")
        lines.append("")
        lines.append("## 数据溯源")
        lines.append("")
        lines.append("| item_id | 标题 |")
        lines.append("|---|---|")
        for item_id in sorted(cited):
            lines.append(f"| `{item_id}` | {esc(cut(cited[item_id], 60))} |")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


__all__ = ["render_debate"]
