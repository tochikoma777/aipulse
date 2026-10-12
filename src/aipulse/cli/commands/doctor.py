"""`aipulse doctor`：环境体检。

检查项：Python 版本 / LLM key / 代理 / 磁盘 / 数据库 / 各数据源连通性探针。
原则：**未配置的东西要给出明确提示与后果说明，而不是静默通过。**
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from aipulse.core.config import load_settings, load_sources, project_root
from aipulse.core.timeutil import now_local, utcnow
from aipulse.store.db import table_names
from aipulse.utils.http import HttpClient, resolve_proxy

# 各源的探针 URL（最小请求，不解析内容，只看连通性与状态码）
DEFAULT_PROBES: dict[str, str] = {
    "github_trending": "https://github.com/trending?since=daily",
    "arxiv": "https://export.arxiv.org/api/query?search_query=cat:cs.LG&max_results=1",
    "hf_papers": "https://huggingface.co/api/daily_papers",
    "hackernews": "https://hn.algolia.com/api/v1/search?query=AI&hitsPerPage=1",
    "reddit": "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day",
}


def probe_targets() -> dict[str, str]:
    """探针目标：优先用 sources.yaml 里的真实配置（如 RSS 首个主干源）。"""
    targets = dict(DEFAULT_PROBES)
    try:
        sources = load_sources().sources
    except Exception:  # 配置缺失不影响体检
        sources = {}

    rss_cfg = sources.get("rss")
    if rss_cfg:
        core_feed = next((f for f in rss_cfg.feeds if f.tier == "core"), None)
        if core_feed:
            targets["rss"] = core_feed.url

    reddit_cfg = sources.get("reddit")
    subreddits = getattr(reddit_cfg, "subreddits", None) or [] if reddit_cfg else []
    if subreddits:
        targets["reddit"] = f"https://www.reddit.com/r/{subreddits[0]}/top/.rss?t=day"

    return targets


async def _probe_one(http: HttpClient, source: str, url: str) -> tuple[str, str]:
    try:
        response = await http.get(url, source=source, cache=False, max_retries=1)
        status = response.status_code
        if 200 <= status < 300:
            return "ok", f"HTTP {status} · {len(response.content)}B"
        return "warn", f"HTTP {status} · {len(response.content)}B"
    except Exception as exc:
        # 明确记录错误类型与信息：DNS 污染、连接超时、TLS 失败都要看得出来
        return "fail", f"{type(exc).__name__}: {exc}"


async def _probe_all(timeout_read_s: float) -> dict[str, dict[str, str]]:
    targets = probe_targets()
    results: dict[str, dict[str, str]] = {}
    async with HttpClient(
        connect_timeout_s=5.0,
        read_timeout_s=timeout_read_s,
        max_retries=1,
        cache_enabled=False,
    ) as http:
        for source, url in targets.items():
            state, detail = await _probe_one(http, source, url)
            results[source] = {"state": state, "detail": detail, "url": url}
    return results


def _python_check() -> tuple[str, str]:
    version = sys.version_info
    ok = (version.major, version.minor) >= (3, 11)
    text = f"Python {version.major}.{version.minor}.{version.micro}（要求 ≥3.11）"
    return ("ok" if ok else "fail"), text


def _llm_key_check() -> tuple[str, str]:
    key = os.getenv("AIPULSE_LLM__API_KEY", "").strip()
    if not key:
        try:
            key = load_settings().llm.api_key.strip()
        except Exception:
            key = ""
    if key:
        masked = f"{key[:3]}***{key[-2:]}" if len(key) > 8 else "***"
        return "ok", f"已配置 {masked}"
    return "warn", "未配置 → 自动按 off 档运行（零 API 花费，功能受限）"


def _proxy_check() -> tuple[str, str]:
    proxy = resolve_proxy()
    if proxy:
        return "ok", f"{proxy}"
    return "warn", "未配置代理（直连）。若源探测超时，请设置 HTTPS_PROXY"


def _disk_check(path: Path) -> tuple[str, str]:
    usage = shutil.disk_usage(path)
    free_gb = usage.free / (1024**3)
    state = "ok" if free_gb >= 2 else "warn"
    return state, f"可用 {free_gb:.1f} GB / 共 {usage.total / (1024**3):.1f} GB"


def _db_check(db_path: Path) -> tuple[str, str]:
    if not db_path.exists():
        return "warn", f"{db_path} 不存在 → 先跑 `aipulse init`"
    try:
        names = table_names(db_path)
    except Exception as exc:
        return "fail", f"无法读取：{exc}"
    expected = {
        "items",
        "signals",
        "topics",
        "entities",
        "predictions",
        "source_runs",
        "pipeline_runs",
        "llm_usage",
        "llm_cache",
    }
    missing = expected - names
    if missing:
        return "fail", f"缺表：{sorted(missing)}"
    return "ok", f"{len(names)} 张表齐全"


def run_doctor(
    *, json_output: bool = False, timeout_read_s: float = 8.0, skip_network: bool = False
) -> int:
    """执行体检，返回退出码（0=无致命问题，1=存在 ❌）。"""
    console = Console()
    settings = load_settings()
    root = project_root()

    rows: list[tuple[str, str, str, str]] = []

    def add(category: str, name: str, state: str, detail: str) -> None:
        rows.append((category, name, state, detail))

    state, detail = _python_check()
    add("环境", "Python 版本", state, detail)
    state, detail = _llm_key_check()
    add("环境", "LLM API key", state, detail)
    state, detail = _proxy_check()
    add("环境", "代理", state, detail)
    state, detail = _disk_check(root)
    add("环境", "磁盘空间", state, detail)
    add(
        "环境",
        "时区",
        "ok",
        f"展示时区 {settings.app.timezone} · 本地 {now_local(settings.app.timezone):%F %T}"
        f" · UTC {utcnow():%F %T}",
    )
    state, detail = _db_check(settings.db_path())
    add("存储", "数据库", state, detail)

    if skip_network:
        add("数据源", "网络探针", "warn", "已跳过（--no-network）")
    else:
        probes = asyncio.run(_probe_all(timeout_read_s))
        for source in sorted(probes):
            info = probes[source]
            add(f"数据源[{source}]", info["url"], info["state"], info["detail"])

    if json_output:
        payload = {
            "checked_at": utcnow().isoformat(),
            "checks": [{"category": c, "name": n, "state": s, "detail": d} for c, n, s, d in rows],
        }
        console.print_json(json.dumps(payload, ensure_ascii=False))
    else:
        table = Table(title="aipulse doctor · 环境体检", header_style="bold cyan")
        table.add_column("类别", style="dim")
        table.add_column("检查项")
        table.add_column("状态", justify="center")
        table.add_column("说明")
        marks = {"ok": "[green]✅[/green]", "warn": "[yellow]⚠️[/yellow]", "fail": "[red]❌[/red]"}
        for category, name, state, detail in rows:
            table.add_row(category, name, marks.get(state, "?"), detail)
        console.print(table)

    failed = [r for r in rows if r[2] == "fail"]
    return 1 if failed else 0


def doctor_command(
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出，便于脚本消费"),
    timeout: float = typer.Option(8.0, "--timeout", help="每个源探针的读取超时（秒）"),
    no_network: bool = typer.Option(False, "--no-network", help="跳过数据源网络探针"),
) -> None:
    """环境体检：Python / LLM key / 代理 / 磁盘 / 数据库 / 各源连通性。"""
    code = run_doctor(json_output=json_output, timeout_read_s=timeout, skip_network=no_network)
    raise typer.Exit(code=code)
