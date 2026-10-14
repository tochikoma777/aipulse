"""`aipulse predict`：★ 预言系统（M3a：自动生成 + 手写 + 列表）。

- 自动生成：`aipulse predict --date today`（hybrid/full 档；off 档不产生预言）。
- 手写预言 `predict add`（全档位核心，v1.3）：**参数 + 缺参自动降级为交互式向导**——
  同一套参数定义，`None` 时 `typer.prompt()` / `rich.prompt.Prompt.ask()` 追问。
- `predict list`：按来源 / 状态列出。

M3b 会补 `verify` / `review`（本文件先留占位）。
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.prompt import Prompt
from sqlmodel import Session

from aipulse.analysis.entities import count_entities
from aipulse.core.config import RunMode, Settings, load_settings
from aipulse.core.logging import configure_logging
from aipulse.core.timeutil import day_window, today_local
from aipulse.llm.base import build_client
from aipulse.reasoning.criteria import (
    coerce_param,
    criteria_names,
    criteria_params,
    parse_param_assignments,
    render_criteria,
)
from aipulse.reasoning.predictor import generate_predictions
from aipulse.schema.prediction import HORIZONS, Prediction, validate_prediction
from aipulse.store.db import engine_for, ensure_schema
from aipulse.store.repo_items import list_entities, list_items_collected, list_topics
from aipulse.store.repo_predictions import insert_predictions, list_predictions

app = typer.Typer(
    name="predict", help="★ 预言系统（M3a：生成 / 手写 / 列表）", invoke_without_command=True
)

console = Console()


def _parse_day(value: str | None, settings: Settings) -> date:
    if not value or value == "today":
        return today_local(settings.app.timezone)
    return date.fromisoformat(value)


def _target_db(db: str | None, settings: Settings) -> Path:
    return Path(db) if db else settings.db_path()


# ── 自动生成（默认动作）─────────────────────────────────────────────


@app.callback(invoke_without_command=True)
def run(
    ctx: typer.Context,
    date_str: str = typer.Option(None, "--date", help="日期 YYYY-MM-DD，默认今天"),
    skip_llm: bool = typer.Option(False, "--skip-llm", help="跳过 LLM（off 档不产生预言）"),
    no_llm: bool = typer.Option(False, "--no-llm", help="同 --skip-llm"),
    db: str = typer.Option(None, "--db", help="数据库路径（默认 data/aipulse.db）"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出摘要"),
) -> None:
    """从当日 Top 条目自动生成可证伪预言并入库（hybrid/full 档）。

    无子命令时作为默认动作执行；带子命令（add/list/verify/review）时跳过。
    """
    if ctx.invoked_subcommand is not None:
        return
    if json_output:
        configure_logging(console_stderr=True)
    settings = load_settings()
    day = _parse_day(date_str, settings)
    skip = skip_llm or no_llm
    mode = RunMode.OFF if skip else settings.effective_mode()
    target_db = _target_db(db, settings)
    ensure_schema(target_db)
    engine = engine_for(target_db)

    with Session(engine, expire_on_commit=False) as session:
        start, end = day_window(day)
        items = list_items_collected(session, since=start, until=end)
        topics = list_topics(session, day)
        entity_counts = count_entities(list_entities(session, day))
        client = build_client(settings, engine=engine)
        output = asyncio.run(
            generate_predictions(
                client=client,
                settings=settings,
                items=items,
                topics=topics,
                entity_counts=entity_counts,
                day=day,
                mode=mode,
                skip_llm=skip,
            )
        )
        inserted = insert_predictions(session, output.predictions)
    engine.dispose()

    if json_output:
        console.print_json(
            json.dumps(
                {
                    "day": day.isoformat(),
                    "mode": mode.value,
                    "generated": len(output.predictions),
                    "inserted": inserted,
                    "dropped": output.meta.get("dropped", []),
                    "llm_calls": output.meta.get("llm_calls", 0),
                },
                ensure_ascii=False,
            )
        )
        raise typer.Exit(code=0)

    if mode == RunMode.OFF:
        console.print("[dim]off 档不产生 LLM 预言；请用 `aipulse predict add` 手写预言。[/dim]")
        raise typer.Exit(code=0)
    console.print(f"[bold]预言生成完成[/bold] {day.isoformat()}：入库 {inserted} 条")
    for pred in output.predictions:
        console.print(f"  · {pred.statement}  （置信度 {pred.confidence}，{pred.horizon_days} 天）")
    for dropped in output.meta.get("dropped", []):
        console.print(
            f"  [red]✗ 丢弃[/red] {dropped['statement']}：{'; '.join(dropped['problems'])}"
        )
    raise typer.Exit(code=0)


# ── 手写预言（全档位核心，v1.3 双模交互）────────────────────────────


@app.command("add")
def add(
    statement: str = typer.Argument(None, help="预言内容（一句话，可证伪）"),
    confidence: float = typer.Option(None, "--confidence", help="0.05-0.95，步长 0.05"),
    horizon_days: int = typer.Option(None, "--horizon-days", help="到期天数 7/30/90/180"),
    criteria: str = typer.Option(
        None, "--criteria", help="量化判据模板名（见 configs/criteria.yaml）"
    ),
    falsifiable: str = typer.Option(None, "--falsifiable-criteria", help="可证伪标准（一句话）"),
    param: list[str] = typer.Option(  # noqa: B008 - Typer 可重复选项的标准写法
        None, "--param", help="判据参数 key=value，可重复"
    ),
    note: str = typer.Option(None, "--note", help="推理依据 / 备注"),
    yes: bool = typer.Option(False, "--yes", help="跳过确认预览（脚本用）"),
    db: str = typer.Option(None, "--db", help="数据库路径（默认 data/aipulse.db）"),
) -> None:
    """手写预言：带全参数非交互执行；不带参数进入交互式向导。"""
    settings = load_settings()
    day = today_local(settings.app.timezone)

    # ── 内容 ──
    text = statement or typer.prompt("预言内容（一句话，要可证伪）")
    # ── 置信度 ──
    conf = (
        confidence
        if confidence is not None
        else float(typer.prompt("置信度 (0.05-0.95，步长0.05)"))
    )
    # ── 到期天数 ──
    horizon = horizon_days
    if horizon is None:
        choice = Prompt.ask("到期天数", choices=[str(h) for h in HORIZONS], default="30")
        horizon = int(choice)
    # ── 判据模板 ──
    template = criteria
    if criteria is None and not yes:
        template = Prompt.ask(
            "判据类型（决定到期如何自动验证）",
            choices=[*criteria_names(), "不设定"],
            default="不设定",
        )
        template = None if template == "不设定" else template

    params: dict[str, Any] = {}
    falsifiable_text = falsifiable
    if template:
        # 模板参数：先吃 --param，再追问缺失的必填参数
        params = parse_param_assignments(param or [], template)
        for p in criteria_params(template):
            if p.get("required") and p["name"] not in params:
                raw = Prompt.ask(f"{template} 参数 {p['name']}（{p.get('type', 'str')}）")
                params[p["name"]] = coerce_param(p["name"], raw, str(p.get("type", "str")))
        falsifiable_text = falsifiable_text or render_criteria(template, params)
    elif falsifiable_text is None and not yes:
        falsifiable_text = typer.prompt("可证伪标准（一句话，满足什么算命中）")

    pred = Prediction(
        statement=text,
        confidence=conf,
        horizon_days=horizon,
        falsifiable_criteria=falsifiable_text or "",
        rationale=(note or "").strip(),
        origin="human",
        criteria=template,
        criteria_params=params or None,
    )
    problems = validate_prediction(pred, require_evidence=False)
    if problems:
        for problem in problems:
            console.print(f"[red]✗ {problem}[/red]")
        raise typer.Exit(code=1)

    # ── 预览卡片确认 ──
    if not yes:
        console.print("")
        console.print("── 预览 ────────────────────────────────", style="bold")
        console.print(f"  内容: {pred.statement}")
        console.print(
            f"  置信度: {pred.confidence}   到期: {pred.due_date(day)} ({pred.horizon_days} 天)"
        )
        if pred.criteria:
            console.print(f"  判据: {pred.falsifiable_criteria}")
        if pred.rationale:
            console.print(f"  依据: {pred.rationale}")
        console.print("────────────────────────────────────────")
        if not typer.confirm("确认写入?"):
            console.print("[dim]已取消[/dim]")
            raise typer.Exit(code=0)

    target_db = _target_db(db, settings)
    ensure_schema(target_db)
    engine = engine_for(target_db)
    from aipulse.store.models import Prediction as PredictionRow
    from aipulse.store.repo_predictions import prediction_id

    row = PredictionRow(
        id=prediction_id(day, pred.statement, "human"),
        date=day,
        statement=pred.statement,
        category=pred.category,
        confidence=pred.confidence,
        horizon_days=pred.horizon_days,
        due_date=pred.due_date(day),
        falsifiable_criteria=pred.falsifiable_criteria,
        rationale=pred.rationale,
        evidence_item_ids=[],
        model="",
        prompt_version="",
        status="pending",
        origin="human",
        criteria=pred.criteria,
        criteria_params=pred.criteria_params,
    )
    with Session(engine, expire_on_commit=False) as session:
        inserted = insert_predictions(session, [row])
    engine.dispose()
    console.print(
        f"✅ 已写入，id={row.id}，到期日 {row.due_date}"
        if inserted
        else f"[dim]已存在：{row.id}[/dim]"
    )
    raise typer.Exit(code=0)


# ── 列表 ─────────────────────────────────────────────────────────────


@app.command("list")
def list_cmd(
    origin: str = typer.Option(None, "--origin", help="human | llm"),
    status: str = typer.Option(None, "--status", help="pending | verified | unverifiable"),
    db: str = typer.Option(None, "--db", help="数据库路径（默认 data/aipulse.db）"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """列出预言。"""
    if json_output:
        configure_logging(console_stderr=True)
    settings = load_settings()
    target_db = _target_db(db, settings)
    ensure_schema(target_db)
    engine = engine_for(target_db)
    with Session(engine, expire_on_commit=False) as session:
        rows = list_predictions(session, status=status, origin=origin)
    engine.dispose()

    payload = [
        {
            "id": r.id,
            "date": r.date.isoformat(),
            "statement": r.statement,
            "category": r.category,
            "confidence": r.confidence,
            "horizon_days": r.horizon_days,
            "due_date": r.due_date.isoformat(),
            "status": r.status,
            "origin": r.origin,
            "falsifiable_criteria": r.falsifiable_criteria,
        }
        for r in rows
    ]
    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        raise typer.Exit(code=0)
    if not rows:
        console.print("[dim]暂无预言[/dim]")
        raise typer.Exit(code=0)
    for r in rows:
        console.print(f"[bold]{r.id}[/bold] [{r.origin}] {r.statement}")
        console.print(f"    {r.confidence} · {r.horizon_days} 天 · 到期 {r.due_date} · {r.status}")
    raise typer.Exit(code=0)


# ── M3b 占位 ─────────────────────────────────────────────────────────


@app.command("verify")
def verify() -> None:
    """到期验证（M3b 实现）。"""
    raise NotImplementedError("`aipulse predict verify` 尚未实现（M3b 验证与统计）")


@app.command("review")
def review() -> None:
    """人工判定闭环（M3b 实现）。"""
    raise NotImplementedError("`aipulse predict review` 尚未实现（M3b 验证与统计）")
