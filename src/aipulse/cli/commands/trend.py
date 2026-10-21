"""trend 命令（M5）：周度趋势长文。

`aipulse trend --range 7d`  → Markdown 到 stdout
`aipulse trend --range 7d --json` → 分段指标（字数/锚定 id/套话/违规）到 stdout

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
from aipulse.llm.base import build_client
from aipulse.reasoning.trend import SEGMENTS, generate_trend

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
    range_: str = typer.Option("7d", "--range", help="窗口：7d（本轮只做周级）"),
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
    window_days = _parse_range(range_)

    if settings.effective_mode().value == "off":
        typer.echo(
            "当前为 off 档：未配置 AIPULSE_LLM__API_KEY。"
            "trend 需要真实模型（hybrid/full），桩测试不能替代。",
            err=True,
        )
        raise typer.Exit(code=2)

    root = Path(reports_dir) if reports_dir else (Path(settings.app.data_dir) / "reports")
    index = load_cross_period(root)
    if not index.days:
        typer.echo(f"没有找到任何日报：{root}", err=True)
        raise typer.Exit(code=2)

    keys = tuple(s.strip() for s in segments.split(",") if s.strip()) if segments else None
    valid = {key for key, _, _ in SEGMENTS}
    unknown = [key for key in (keys or ()) if key not in valid]
    if unknown:
        typer.echo(f"未知的段：{unknown}；可选 {sorted(valid)}", err=True)
        raise typer.Exit(code=2)

    client = build_client(settings)  # engine=None：不写主库
    # 每段 300-600 字，但 strong 档的思维链也吃 completion 额度；
    # 2000 会让 reasoner 在写出正文前就撞长度（实测 7/7 段被截断）。
    budget_tokens = max_tokens or settings.llm.max_tokens_strong
    report = asyncio.run(
        generate_trend(
            index,
            client,
            window_days=window_days,
            max_tokens=budget_tokens,
            price_strong_cny_per_1m=settings.budget.price_strong_cny_per_1m,
            segment_keys=keys,
        )
    )

    markdown = report.to_markdown()
    if out:
        target = Path(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")

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
    for segment in report.segments:
        status = "skip" if segment.skipped_reason else f"{segment.char_count} 字"
        typer.echo(
            f"[trend] {segment.key:18} {status:>8}  锚定 {len(segment.cited_item_ids)} id"
            f"  套话 {len(segment.boilerplate_hits)}  违规 {len(segment.violations)}",
            err=True,
        )

    if not any(segment.body for segment in report.segments):
        raise typer.Exit(code=1)
