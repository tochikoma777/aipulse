"""预言记分板 Markdown 渲染（设计方案 §10.2.3，可直接贴进 README）。

产物是一段自包含的 Markdown：总览 + 校准表 + 分组统计。空态给优雅提示
（手册坑 18：记分板 0 样本时页面不得报错/难看）。
"""

from __future__ import annotations

from aipulse.analysis.stats import PredictionStats

_GROUP_TITLES = {
    "category": "按类别（category）",
    "horizon_days": "按周期（horizon_days）",
    "origin": "按来源（human / llm）",
    "model": "按模型",
    "prompt_version": "按 prompt 版本",
}


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _num(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _brier_label(brier: float | None) -> str:
    if brier is None:
        return ""
    if brier < 0.20:
        return " ✅ 优秀"
    if brier < 0.25:
        return " （优于随机基线）"
    return " ⚠️ 接近或差于随机基线"


def render_scoreboard_markdown(stats: PredictionStats) -> str:
    """渲染记分板。样本为 0 时输出优雅空态。"""
    out: list[str] = ["## 🎯 预言记分板", ""]

    if not stats.has_results:
        out += [
            f"> 系统已累计 **{stats.total}** 条预言，尚无到期判定结果。",
            "> 具体成绩将在首批预言到期并验证后展示——**让时间说话**。",
            "",
        ]
        if stats.pending:
            out.append(f"- 待验证（pending）：{stats.pending}")
        if stats.unverifiable:
            out.append(f"- 无法验证（unverifiable）：{stats.unverifiable}")
        out.append("")
        return "\n".join(out)

    out.append(
        f"> 已验证 **{stats.verified}** 条（另有 {stats.pending} 条待验证、"
        f"{stats.unverifiable} 条无法验证，均不计入分母）"
    )
    out += [
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 命中率（hit 占比） | **{_pct(stats.hit_rate)}**（{stats.hits}/{stats.verified}） |",
        f"| 加权分（verdict_score 均值） | {_num(stats.weighted_score)} |",
        f"| Brier Score（越低越好） | {_num(stats.brier)}{_brier_label(stats.brier)} |",
        f"| 命中 / 部分 / 落空 | {stats.hits} / {stats.partials} / {stats.misses} |",
        "",
        "### 置信度校准",
        "",
        "| 置信度区间 | 样本 | 平均置信度 | 实际命中率 |",
        "|---|---|---|---|",
    ]
    for bucket in stats.calibration:
        out.append(
            f"| {bucket.label} | {bucket.n} | {_num(bucket.mean_confidence)} "
            f"| {_pct(bucket.hit_rate)} |"
        )
    out.append("")

    for field_name, rows in stats.groups.items():
        if not rows:
            continue
        out += [
            f"### {_GROUP_TITLES.get(field_name, field_name)}",
            "",
            "| 取值 | 样本 | 命中率 | 加权分 |",
            "|---|---|---|---|",
        ]
        for row in rows:
            out.append(
                f"| {row.label} | {row.n} | {_pct(row.hit_rate)} | {_num(row.weighted_score)} |"
            )
        out.append("")

    out += ["---", "", f"_生成时间：{stats.generated_at}_", ""]
    return "\n".join(out)


__all__ = ["render_scoreboard_markdown"]
