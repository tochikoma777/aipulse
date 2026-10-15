"""`aipulse stats`：预言统计与记分板（设计方案 §10.2.3，M3b）。

- `aipulse stats --predictions`：命中率 / 加权分 / Brier / 校准表 / 分组统计。
- `--json` 输出机器可读结果；`--markdown` 打印记分板 Markdown；`--out <path>` 落盘。
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import Session

from aipulse.analysis.stats import PredictionStats, compute_prediction_stats
from aipulse.core.config import load_settings
from aipulse.core.logging import configure_logging
from aipulse.render.scoreboard import render_scoreboard_markdown
from aipulse.store.db import engine_for, ensure_schema
from aipulse.store.repo_predictions import list_predictions

app = typer.Typer(name="stats", help="统计与记分板", invoke_without_command=True)
console = Console()


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _num(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _stats_to_dict(stats: PredictionStats) -> dict[str, object]:
    return {
        "total": stats.total,
        "verified": stats.verified,
        "unverifiable": stats.unverifiable,
        "pending": stats.pending,
        "hits": stats.hits,
        "partials": stats.partials,
        "misses": stats.misses,
        "hit_rate": stats.hit_rate,
        "weighted_score": stats.weighted_score,
        "brier": stats.brier,
        "calibration": [
            {
                "bucket": b.label,
                "n": b.n,
                "mean_confidence": b.mean_confidence,
                "hit_rate": b.hit_rate,
            }
            for b in stats.calibration
        ],
        "groups": {
            name: [
                {
                    "label": g.label,
                    "n": g.n,
                    "hit_rate": g.hit_rate,
                    "weighted_score": g.weighted_score,
                }
                for g in rows
            ]
            for name, rows in stats.groups.items()
        },
        "generated_at": stats.generated_at,
    }


def _print_summary(stats: PredictionStats) -> None:
    console.print("[bold]🎯 预言记分板[/bold]")
    console.print(
        f"总数 {stats.total} · 已验证 {stats.verified} · 无法验证 {stats.unverifiable} · "
        f"待验证 {stats.pending}（后两者不计入分母）"
    )
    table = Table(show_header=True, header_style="bold")
    table.add_column("指标")
    table.add_column("值", justify="right")
    table.add_row("命中率", f"{_pct(stats.hit_rate)}（{stats.hits}/{stats.verified}）")
    table.add_row("加权分", _num(stats.weighted_score))
    table.add_row("Brier Score", _num(stats.brier))
    table.add_row("命中/部分/落空", f"{stats.hits} / {stats.partials} / {stats.misses}")
    console.print(table)

    cal = Table(title="置信度校准", show_header=True, header_style="bold")
    for col in ("置信度区间", "样本", "平均置信度", "实际命中率"):
        cal.add_column(col, justify="right" if col != "置信度区间" else "left")
    for bucket in stats.calibration:
        cal.add_row(
            bucket.label,
            str(bucket.n),
            _num(bucket.mean_confidence),
            _pct(bucket.hit_rate),
        )
    console.print(cal)

    for name, rows in stats.groups.items():
        if not rows:
            continue
        gt = Table(title=f"分组：{name}", show_header=True, header_style="bold")
        for col in ("取值", "样本", "命中率", "加权分"):
            gt.add_column(col, justify="right" if col != "取值" else "left")
        for row in rows:
            gt.add_row(row.label, str(row.n), _pct(row.hit_rate), _num(row.weighted_score))
        console.print(gt)


@app.callback(invoke_without_command=True)
def run(
    ctx: typer.Context,
    predictions: bool = typer.Option(False, "--predictions", help="预言统计与记分板"),
    db: str = typer.Option(None, "--db", help="数据库路径（默认 data/aipulse.db）"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
    markdown: bool = typer.Option(False, "--markdown", help="打印记分板 Markdown"),
    out: str = typer.Option(None, "--out", help="把记分板 Markdown 写到指定文件"),
) -> None:
    """输出预言命中率 / 加权分 / Brier Score / 校准表。"""
    if ctx.invoked_subcommand is not None:
        return
    if json_output or markdown:
        configure_logging(console_stderr=True)
    settings = load_settings()
    target_db = Path(db) if db else settings.db_path()
    ensure_schema(target_db)
    engine = engine_for(target_db)
    with Session(engine, expire_on_commit=False) as session:
        rows = list_predictions(session)
    engine.dispose()

    stats = compute_prediction_stats(rows)

    markdown_text = render_scoreboard_markdown(stats)
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown_text, encoding="utf-8")
        console.print(f"记分板已写入：{out_path}")
        raise typer.Exit(code=0)
    if markdown:
        console.print(markdown_text)
        raise typer.Exit(code=0)
    if json_output:
        console.print_json(json.dumps(_stats_to_dict(stats), ensure_ascii=False))
        raise typer.Exit(code=0)

    _print_summary(stats)
    raise typer.Exit(code=0)


__all__ = ["app"]
