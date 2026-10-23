"""debate 命令（M5 S4）：多角色辩论。

`aipulse debate --topic "…"`             → 手动指定议题，跑四方辩论
`aipulse debate --topic "…" --json`      → 只吐指标 JSON（正文不刷屏）
`aipulse debate --topic "…" --out X.md`  → 指定落盘路径

产物落 `data/reports/debate/debate-<slug>.{md,json}`（与 `data/reports/trend/` 同构）：
**不入库**，只落盘。注意产物一旦被 commit，本地重跑产生 diff 会让
`scripts/cron_knowledge.sh` 的 `git diff --quiet` 判定为脏工作区而跳过 pull/export——
这与 `weekly.md` 的现状是同一级别，未做特殊处理。

TODO(auto)：从 `data/reports/trend/weekly.md` 的分歧度自动挑本周最大争议话题。
需要先把"分歧度"定义成可计算的量（候选：同一 item 在不同段被给出相反方向、
或 source_share 与 persistence 结论方向相反），本轮未开工。
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import typer

from aipulse.analysis.cross_period import load_cross_period
from aipulse.core.config import load_settings
from aipulse.core.logging import configure_logging
from aipulse.llm.base import build_client
from aipulse.reasoning.debate import run_debate

app = typer.Typer(
    name="debate",
    help="多角色辩论（M5 S4）：四方并行陈述 → 交叉质证 → 主持人收敛",
    invoke_without_command=True,
)

_UNSAFE_RE = re.compile(r"[^\w\u4e00-\u9fff-]+")


def _parse_range(value: str) -> int:
    text = value.strip().lower().rstrip("d")
    if not text.isdigit() or int(text) <= 0:
        raise typer.BadParameter("--range 只接受 `7d` 这类格式")
    return int(text)


def slugify(topic: str) -> str:
    """议题 → 文件名片段；中文保留，其余非文字符号压成单横线。"""
    slug = _UNSAFE_RE.sub("-", topic.strip()).strip("-")
    return slug[:40] or "untitled"


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    topic: str = typer.Option("", "--topic", help="辩论议题（auto 模式本轮未实现，必须显式给）"),
    range_: str = typer.Option("7d", "--range", help="取材窗口：7d"),
    json_output: bool = typer.Option(False, "--json", help="输出指标 JSON"),
    out: str | None = typer.Option(None, "--out", help="把 Markdown 写到指定文件"),
    max_tokens: int = typer.Option(
        0, "--max-tokens", help="每环节输出上限；0 = 用 llm.max_tokens_strong"
    ),
    reports_dir: str | None = typer.Option(
        None, "--reports-dir", help="报告目录（默认 data/reports）"
    ),
) -> None:
    """跑一场辩论；命中任一失败判据时退出码为 1。"""
    if ctx.invoked_subcommand is not None:  # 未来加子命令（如 auto）时的保护
        return

    settings = load_settings()
    configure_logging(settings.app.log_level, console_stderr=True)

    if settings.effective_mode().value == "off":
        typer.echo(
            "当前为 off 档：未配置 AIPULSE_LLM__API_KEY。"
            "debate 需要真实模型（hybrid/full），桩测试不能替代。",
            err=True,
        )
        raise typer.Exit(code=2)

    if not topic.strip():
        typer.echo(
            "必须给 --topic；auto 模式（从 trend 输出挑本周最大争议话题）本轮未实现。",
            err=True,
        )
        raise typer.Exit(code=2)

    root = Path(reports_dir) if reports_dir else (Path(settings.app.data_dir) / "reports")
    index = load_cross_period(root)
    if not index.days:
        typer.echo(f"没有找到任何日报：{root}", err=True)
        raise typer.Exit(code=2)

    window_days = _parse_range(range_)
    client = build_client(settings)  # engine=None：不写主库
    budget_tokens = max_tokens or settings.llm.max_tokens_strong
    report = asyncio.run(
        run_debate(
            index,
            client,
            topic=topic.strip(),
            max_tokens=budget_tokens,
            price_strong_cny_per_1m=settings.budget.price_strong_cny_per_1m,
            window_days=window_days,
        )
    )

    markdown = report.to_markdown()
    default_dir = (Path(settings.app.data_dir) / "reports") / "debate"
    target = Path(out) if out else default_dir / f"debate-{slugify(topic)}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    target.with_suffix(".json").write_text(
        json.dumps(report.summary(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if json_output:
        typer.echo(json.dumps(report.summary(), ensure_ascii=False, indent=2))
    else:
        typer.echo(markdown)

    typer.echo(
        f"[debate] 窗口 {report.window_start}→{report.window_end}"
        f" 证据 {len(report.evidence_lines)} 条"
        f" 调用 {report.llm_calls}/{report.attempts} 次成功"
        f" 截断 {len(report.truncated)} 处"
        f" tokens {report.prompt_tokens}+{report.completion_tokens}"
        f" 成本 ¥{report.cost_cny:.4f}",
        err=True,
    )
    typer.echo(f"[debate] 落盘 {target}", err=True)
    for stmt in report.statements:
        status = (
            f"无效：{stmt.invalid_reason}"
            if not stmt.valid
            else f"{stmt.char_count} 字 锚定 {len(stmt.cited_item_ids)} id"
            f" 证伪违规 {len(stmt.falsification.violations)}"
        )
        typer.echo(f"[debate] R1 {stmt.persona_label or stmt.persona:6} {status}", err=True)
    typer.echo(
        f"[debate] 收敛：共识 {len(report.moderator.consensus)}"
        f" 分歧 {len(report.moderator.key_disagreements)}"
        f" 可执行 {len(report.moderator.actionable_conclusions)}"
        f" 置信度 {report.moderator.overall_confidence:.2f}"
        f" 可用证伪 {report.falsification_usable}/{report.falsification_total}",
        err=True,
    )

    if not report.ok:
        for item in report.failures:
            typer.echo(f"[debate] ⛔ {item}", err=True)
        raise typer.Exit(code=1)
