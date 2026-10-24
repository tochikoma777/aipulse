"""selfcheck 命令（M5 S3）：对已生成的周报跑 L1-L4 自验证。

`aipulse selfcheck`                     → 打默认周报的自验证报告
`aipulse selfcheck --json`              → 四层结论的 JSON
`aipulse selfcheck --no-write-state`    → 只读检查，不更新 watchlist/calibration

纯离线：不调 LLM，不碰主库。
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from aipulse.analysis.cross_period import load_cross_period
from aipulse.core.config import load_settings
from aipulse.reasoning.selfcheck import FAIL, build_admission, run_selfcheck

app = typer.Typer(
    name="selfcheck",
    help="周报自验证（M5 S3）：L1 硬判据 / L2 信息增量 / L3 跨期回检 / L4 校准",
    invoke_without_command=True,
)


def _parse_window(value: str) -> int:
    text = value.strip().lower().rstrip("d")
    if not text.isdigit() or int(text) <= 0:
        raise typer.BadParameter("--window 只接受 `7d` 这类格式")
    return int(text)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    file: str = typer.Option(
        "",
        "--file",
        help=(
            "待验证的周报（默认 data/reports/trend/<窗口末日>/weekly.json，机器层）。"
            "S5 起 L1-L4 读机器层：7 节正文与裸 ID 都在那里，人类层 weekly.md 只给结论"
        ),
    ),
    reports_dir: str | None = typer.Option(
        None, "--reports-dir", help="日报目录（默认 data/reports）"
    ),
    window: str = typer.Option("7d", "--window", help="生成该周报时的取数窗口"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
    out: str | None = typer.Option(None, "--out", help="把自验证报告写到文件"),
    write_state: bool = typer.Option(
        True, "--write-state/--no-write-state", help="是否更新 watchlist / calibration 状态"
    ),
) -> None:
    """离线跑四层自检；任一层 fail 时退出码为 1。"""
    if ctx.invoked_subcommand is not None:  # 未来加子命令时的保护
        return

    settings = load_settings()
    root = Path(reports_dir) if reports_dir else (Path(settings.app.data_dir) / "reports")
    index = load_cross_period(root)
    if not index.days:
        typer.echo(f"没有找到任何日报：{root}", err=True)
        raise typer.Exit(code=2)

    # 产物按窗口末日分目录：weekly/selfcheck/watchlist/calibration 都跟着走
    issue = index.days[-1]
    issue_dir = root / "trend" / issue
    target = Path(file) if file else issue_dir / "weekly.json"
    if not file and not target.exists():
        # 日报每天都有、周报按周产：最新一天通常还没有 trend 产物，
        # 这时应回退到最近一期**存在**的周报，而不是直接判死。
        candidates = sorted(p.parent for p in root.glob("trend/*/weekly.json"))
        if candidates:
            issue_dir = candidates[-1]
            target = issue_dir / "weekly.json"
            typer.echo(f"[selfcheck] {issue} 没有周报，回退到 {issue_dir.name} 的产物", err=True)
    if not target.exists():
        typer.echo(
            f"找不到周报：{target}（先跑 `aipulse trend`；或 --file 指定机器层 weekly.json）",
            err=True,
        )
        raise typer.Exit(code=2)

    source: str | dict[str, object]
    if target.suffix == ".json":
        try:
            source = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            typer.echo(f"机器层 JSON 解析失败：{exc}", err=True)
            raise typer.Exit(code=2) from exc
    else:
        source = target.read_text(encoding="utf-8")

    report = run_selfcheck(
        source,
        index,
        state_dir=issue_dir,
        window_days=_parse_window(window),
        write_state=write_state,
    )

    markdown = report.to_markdown()
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    # selfcheck 报告与状态都落在窗口末日目录下
    issue_dir.mkdir(parents=True, exist_ok=True)
    (issue_dir / "selfcheck.md").write_text(markdown, encoding="utf-8")
    (issue_dir / "selfcheck.json").write_text(payload, encoding="utf-8")
    # L4 → 下期准入（反馈闭环）：trend 下次启动时读最近一期 admission.json
    admission = build_admission(index, state_dir=issue_dir)
    (issue_dir / "admission.json").write_text(
        json.dumps(admission, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # --out 与 stdout 保持同一种格式：--json 时写 JSON，否则写 Markdown
        out_path.write_text(payload if json_output else markdown, encoding="utf-8")

    typer.echo(payload if json_output else markdown)

    for layer in report.layers:
        typer.echo(f"[selfcheck] {layer.layer} {layer.name}: {layer.verdict}", err=True)
    typer.echo(f"[selfcheck] 落盘 {issue_dir}/selfcheck.{{md,json}}", err=True)
    limit = admission["max_structure_claims"]
    typer.echo(
        f"[selfcheck] 下期准入 {admission['level']}（上限 {limit} 条）：{admission['reason']}",
        err=True,
    )

    if any(layer.verdict == FAIL for layer in report.layers):
        raise typer.Exit(code=1)
