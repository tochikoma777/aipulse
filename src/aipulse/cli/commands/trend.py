"""trend 命令（M5）：周度趋势长文。

`aipulse trend --range 7d`  → 人类版 Markdown 到 stdout
`aipulse trend --range 7d --json` → 分段指标（字数/锚定 id/套话/违规）到 stdout

产物按**窗口结束日**建目录，不再用固定名覆盖（跨期历史是 L3/L4 的输入）：

    data/reports/trend/<window_end>/weekly.md    人类层（三句话 + 表格 + 折叠免责）
    data/reports/trend/<window_end>/weekly.json  机器层（7 节正文 + id + 免责，供 L1-L4）

只读 `data/reports/**`；LLM 用量走内存记账（engine=None），**不写主库**，
所以跑一次 trend 不会改变 `data/aipulse.db` 的 sha256。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from aipulse.analysis.cross_period import load_cross_period
from aipulse.core.config import load_settings
from aipulse.core.logging import configure_logging
from aipulse.core.schedule import (
    TRIGGER_DISABLED,
    describe_interval,
    parse_interval,
    window_for,
)
from aipulse.core.timeutil import today_local
from aipulse.llm.base import build_client
from aipulse.reasoning.selfcheck import admission_rule_for, load_admission
from aipulse.reasoning.trend import (
    SEGMENTS,
    calendar_days,
    generate_trend,
    window_shortfall_note,
)
from aipulse.render.weekly import render_weekly

app = typer.Typer(
    name="trend",
    help="周期趋势长文（M5）：按周分段生成",
    invoke_without_command=True,
)


def _parse_range(value: str) -> int:
    text = value.strip().lower().rstrip("d")
    if not text.isdigit() or int(text) <= 0:
        raise typer.BadParameter("--range 只接受 `7d` / `30d` 这类格式")
    return int(text)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    range_: str = typer.Option(
        "",
        "--range",
        help=(
            "取材窗口，如 7d / 30d；**显式给出时优先于配置**。"
            "省略时按 pipeline.trend.interval（默认 1m=上一个完整自然月）推导——"
            "interval 既是触发间隔也是分析范围"
        ),
    ),
    json_output: bool = typer.Option(False, "--json", help="输出分段指标 JSON"),
    out: str | None = typer.Option(None, "--out", help="把 Markdown 写到指定文件"),
    max_tokens: int = typer.Option(
        0, "--max-tokens", help="每段输出上限；0 = 用 llm.max_tokens_strong"
    ),
    segments: str | None = typer.Option(None, "--segments", help="只跑指定段，逗号分隔（调试用）"),
    reports_dir: str | None = typer.Option(
        None, "--reports-dir", help="报告目录（默认 data/reports）"
    ),
) -> None:
    """按 7 节分段生成趋势长文；任一段失败只跳过该段。"""
    if ctx.invoked_subcommand is not None:  # 未来加子命令时的保护
        return

    settings = load_settings()
    configure_logging(settings.app.log_level, console_stderr=json_output)

    if settings.effective_mode().value == "off":
        typer.echo(
            "当前为 off 档：未配置 AIPULSE_LLM__API_KEY。"
            "trend 需要真实模型（hybrid/full），桩测试不能替代。",
            err=True,
        )
        raise typer.Exit(code=2)

    trigger = settings.pipeline.trend
    window_range: tuple[str, str] | None = None

    if range_.strip():
        # 显式 CLI 优先于配置
        window_days = _parse_range(range_)
    elif trigger.trigger_mode == TRIGGER_DISABLED:
        typer.echo(
            "pipeline.trend.trigger_mode=disabled：该阶段已停用。"
            "如确需手动跑一次，请显式给 --range（如 --range 7d）。",
            err=True,
        )
        raise typer.Exit(code=2)
    else:
        # 省略 --range → 按 interval 推导分析范围（日历月：上一个完整自然月）
        interval = parse_interval(trigger.interval)
        start, end = window_for(interval, today_local(), complete_only=True)
        window_range = (start.isoformat(), end.isoformat())
        window_days = calendar_days(start.isoformat(), end.isoformat())
        typer.echo(
            f"[trend] 未给 --range → 按 pipeline.trend.interval={trigger.interval}"
            f"（{describe_interval(trigger.interval)}）取 {start.isoformat()} → {end.isoformat()}"
            f"（{window_days} 天）",
            err=True,
        )

    keys = tuple(s.strip() for s in segments.split(",") if s.strip()) if segments else None
    valid = {key for key, _, _ in SEGMENTS}
    unknown = [key for key in (keys or ()) if key not in valid]
    if unknown:
        typer.echo(f"未知的段：{unknown}；可选 {sorted(valid)}", err=True)
        raise typer.Exit(code=2)

    root = Path(reports_dir) if reports_dir else (Path(settings.app.data_dir) / "reports")
    index = load_cross_period(root)
    if not index.days:
        typer.echo(f"没有找到任何日报：{root}", err=True)
        raise typer.Exit(code=2)
    if window_range is not None and not any(
        window_range[0] <= day <= window_range[1] for day in index.days
    ):
        # ★ interval 推导出的范围一篇日报都没有 → **exit 0 + 说明**，不是错误。
        #   月度自动触发时，"上个月还没有这个项目"完全正常（本项目 10-15 才有数据，
        #   9 月整月空白）。若这里 exit 2，首次触发前任何人点一下都红 = 狼来了。
        #   只有**真错误**（off 档 / 无日报目录 / 未知段）才 exit 2。
        typer.echo(
            f"[trend] 跳过本期：分析范围 {window_range[0]} → {window_range[1]} 内没有日报"
            f"（现有 {index.days[0]} → {index.days[-1]}）。",
            err=True,
        )
        typer.echo(
            "[trend] 数据不足不是错误：等这个周期有日报后再触发，"
            "或显式给 --range 指定一个有数据的窗口。",
            err=True,
        )
        raise typer.Exit(code=0)

    # 数据不足时明确说"还差几天"，不静默把 30 天当 10 天跑
    shortfall = window_shortfall_note(window_days, index.days)
    if shortfall:
        typer.echo(f"[trend] ⚠ {shortfall}", err=True)

    client = build_client(settings)  # engine=None：不写主库
    # 每段 300-600 字，但 strong 档的思维链也吃 completion 额度；
    # 2000 会让 reasoner 在写出正文前就撞长度（实测 7/7 段被截断）。
    budget_tokens = max_tokens or settings.llm.max_tokens_strong
    # L4 反馈闭环：上一期自检若判了过度声称，本期就收紧结构判断的准入
    trend_dir = root / "trend"
    admission = load_admission(trend_dir)
    rule = admission_rule_for(admission)
    report = asyncio.run(
        generate_trend(
            index,
            client,
            window_days=window_days,
            max_tokens=budget_tokens,
            price_strong_cny_per_1m=settings.budget.price_strong_cny_per_1m,
            segment_keys=keys,
            admission_rule=rule,
            requested_days=window_days,
            window_range=window_range,
        )
    )

    # 人类层：三句话 + 表格 + 折叠免责；机器层：7 节正文 + id + 免责（供 L1-L4）
    markdown = render_weekly(report, index)
    machine = report.to_machine_json()
    issue = report.window_end or "unknown"
    default_dir = (Path(settings.app.data_dir) / "reports") / "trend" / issue
    md_path = Path(out) if out else default_dir / "weekly.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8")
    md_path.with_suffix(".json").write_text(
        json.dumps(machine, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if json_output:
        typer.echo(json.dumps(report.summary(), ensure_ascii=False, indent=2))
    else:
        typer.echo(markdown)

    # 指标走 stderr，保证 stdout 只有 Markdown
    typer.echo(
        f"[trend] 窗口 {report.window_start}→{report.window_end}（{report.window_days} 天）"
        f" 调用 {report.llm_calls}/{report.attempts} 次成功，"
        f"截断 {len(report.truncated_segments)} 段，"
        f"tokens {report.prompt_tokens}+{report.completion_tokens}，"
        f"成本 ¥{report.cost_cny:.4f}",
        err=True,
    )
    typer.echo(
        f"[trend] 落盘 {md_path}（人类层）+ {md_path.with_suffix('.json')}（机器层）",
        err=True,
    )
    if rule:
        typer.echo(f"[trend] 准入收紧：{admission.get('reason', '')}", err=True)
    for segment in report.segments:
        status = "skip" if segment.skipped_reason else f"{segment.char_count} 字"
        typer.echo(
            f"[trend] {segment.key:18} {status:>8}  锚定 {len(segment.cited_item_ids)} id"
            f"  套话 {len(segment.boilerplate_hits)}  违规 {len(segment.violations)}",
            err=True,
        )

    if not any(segment.body for segment in report.segments):
        raise typer.Exit(code=1)
