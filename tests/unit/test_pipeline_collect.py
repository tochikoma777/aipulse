"""采集编排的故障注入与环境分级测试（设计方案 §5.9 / §5.10）。

全部用 respx mock，**不打真实网络**。
"""

from __future__ import annotations

import httpx
import pytest
import respx
from sqlmodel import Session, select

from aipulse.core.config import SourceConfig, is_actions_env
from aipulse.pipeline.collect import (
    STATUS_DEGRADED,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_SKIPPED_OFFLINE,
    run_collect,
)
from aipulse.store.db import engine_for
from aipulse.store.models import SourceRun
from tests.conftest import fixture_bytes, fixture_text

TRENDING_URL = "https://github.com/trending?since=daily"
SEARCH_URL = "https://api.github.com/search/repositories"
HN_URL = "https://hn.algolia.com/api/v1/search_by_date"
ARXIV_URL = "https://export.arxiv.org/api/query"


SIMON_URL = "https://simonwillison.net/atom/everything/"
QBIT_URL = "https://www.qbitai.com/feed"


def _test_sources_yaml(tmp_path) -> None:
    """把复制过来的 sources.yaml 收敛成**确定性的测试 profile**。

    生产配置有 7 个英文主干 feed，逐个 mock 会淹没测试意图；
    这里只保留 1 个 core + 1 个 optional（title_only）feed，
    多 feed 行为由 tests/unit/test_collectors_runtime.py 用显式配置覆盖。
    """
    import yaml

    path = tmp_path / "configs" / "sources.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["sources"]["rss"]["feeds"] = [
        {"name": "Simon Willison", "url": SIMON_URL, "tier": "core"},
        {
            "name": "量子位",
            "url": QBIT_URL,
            "tier": "optional",
            "title_only": True,
            "weight": 0.35,
        },
    ]
    data["sources"]["hackernews"]["queries"] = ["AI"]
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _mock_feeds(*, simon: int = 200, qbitai: int = 200) -> None:
    """显式声明两个 feed 的期望结果（默认：主干 200，中文源 404）。"""
    respx.get(SIMON_URL).mock(
        return_value=(
            httpx.Response(200, content=fixture_bytes("rss_feed.xml"))
            if simon == 200
            else httpx.Response(simon)
        )
    )
    respx.get(QBIT_URL).mock(
        return_value=(
            httpx.Response(200, content=fixture_bytes("rss_feed_zh.xml"))
            if qbitai == 200
            else httpx.Response(qbitai)
        )
    )


def _localize(monkeypatch, tmp_path):
    """把项目根指向临时目录（避免写进真实 data/），同时复制真实配置进去。

    复制而不是另写一套：测试要覆盖的正是"生产配置 + 真实 fixture"的组合。
    """
    import shutil
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("AIPULSE_ROOT", str(tmp_path))
    from aipulse.core.config import load_settings

    load_settings.cache_clear()
    shutil.copytree(repo_root / "configs", tmp_path / "configs", dirs_exist_ok=True)
    shutil.copy(repo_root / "alembic.ini", tmp_path / "alembic.ini")
    ini = tmp_path / "alembic.ini"
    ini.write_text(
        ini.read_text(encoding="utf-8").replace(
            "%(here)s/src/aipulse/store/migrations",
            str(repo_root / "src" / "aipulse" / "store" / "migrations"),
        ),
        encoding="utf-8",
    )
    _test_sources_yaml(tmp_path)


@pytest.fixture(autouse=True)
def _clear_settings():
    from aipulse.core.config import load_settings

    load_settings.cache_clear()
    yield
    load_settings.cache_clear()


def test_is_actions_env_flag(monkeypatch):
    monkeypatch.delenv("AIPULSE_ENV", raising=False)
    assert is_actions_env() is False
    monkeypatch.setenv("AIPULSE_ENV", "actions")
    assert is_actions_env() is True


def test_source_availability_grading():
    assert SourceConfig(availability="always").is_available({}) is True
    assert SourceConfig(availability="actions_only").is_available({}) is False
    assert (
        SourceConfig(availability="actions_only").is_available({"AIPULSE_ENV": "actions"}) is True
    )


@respx.mock
async def test_single_source_failure_does_not_break_pipeline(monkeypatch, tmp_path):
    """故障注入：GitHub 500、HN 超时、arXiv 返回空、RSS 正常 → 其余源照常完成。"""
    _localize(monkeypatch, tmp_path)
    _mock_feeds()
    respx.get(TRENDING_URL).mock(return_value=httpx.Response(500))
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(500))
    respx.get(HN_URL).mock(side_effect=httpx.ConnectTimeout)
    respx.get(ARXIV_URL).mock(return_value=httpx.Response(200, text="<feed></feed>"))

    result = await run_collect(
        sources=["github_trending", "hackernews", "arxiv", "rss"],
        since="30d",
        db_path=str(tmp_path / "t.db"),
    )
    statuses = {r.source: r.status for r in result.results}
    assert statuses["github_trending"] == STATUS_FAILED
    assert statuses["hackernews"] == STATUS_FAILED
    assert statuses["arxiv"] == STATUS_DEGRADED  # 空返回 → 降级而非失败
    assert statuses["rss"] == STATUS_OK
    assert result.items, "正常源必须仍产出条目"
    # 失败源被记录进 source_runs，而不是被吞掉
    engine = engine_for(tmp_path / "t.db")
    with Session(engine) as session:
        runs = session.exec(select(SourceRun)).all()
        assert any(run.status == STATUS_FAILED for run in runs)
    engine.dispose()


@respx.mock
async def test_429_is_retried_then_succeeds(monkeypatch, tmp_path):
    _localize(monkeypatch, tmp_path)
    _mock_feeds()
    route = respx.get(SIMON_URL).mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, content=fixture_bytes("rss_feed.xml")),
        ]
    )
    result = await run_collect(sources=["rss"], since="30d", db_path=str(tmp_path / "t.db"))
    assert route.call_count == 2
    assert result.items


@respx.mock
async def test_empty_response_degrades_not_fails(monkeypatch, tmp_path):
    _localize(monkeypatch, tmp_path)
    _mock_feeds()
    respx.get(SIMON_URL).mock(return_value=httpx.Response(200, text=""))
    result = await run_collect(sources=["rss"], since="30d", db_path=str(tmp_path / "t.db"))
    assert result.results[0].status == STATUS_DEGRADED
    assert result.failed_sources == []


@respx.mock
async def test_html_structure_change_triggers_search_fallback(monkeypatch, tmp_path):
    """HTML 改版 → 解析 0 条 → 自动降级 Search API（坑 5）。"""
    _localize(monkeypatch, tmp_path)
    respx.get(TRENDING_URL).mock(return_value=httpx.Response(200, text="<html>changed</html>"))
    respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(
            200, json=__import__("json").loads(fixture_text("github_search.json"))
        )
    )
    result = await run_collect(
        sources=["github_trending"], since="30d", db_path=str(tmp_path / "t.db")
    )
    assert result.results[0].status == STATUS_OK
    assert len(result.items) == 10
    assert "Search API" in result.results[0].note


async def test_actions_only_sources_are_skipped_locally(monkeypatch, tmp_path):
    """DoD ★：本地跳过 actions_only 源，status='skipped_offline'，不计失败。"""
    _localize(monkeypatch, tmp_path)
    monkeypatch.delenv("AIPULSE_ENV", raising=False)
    result = await run_collect(
        sources=["reddit", "hf_papers"], since="30d", db_path=str(tmp_path / "t.db"), no_cache=True
    )
    assert result.failed_sources == []
    assert len(result.skipped) == 2
    assert all(r.status == STATUS_SKIPPED_OFFLINE for r in result.skipped)
    assert all("actions_only" in r.note for r in result.skipped)
    # 跳过不写 source_runs（没有真实采集发生），也不影响退出码（CLI 恒为 0）
    engine = engine_for(tmp_path / "t.db")
    with Session(engine) as session:
        assert session.exec(select(SourceRun)).all() == []
    engine.dispose()


@respx.mock
async def test_actions_env_collects_actions_only_sources(monkeypatch, tmp_path):
    """DoD ★：AIPULSE_ENV=actions 时 actions_only 源正常采集。"""
    _localize(monkeypatch, tmp_path)
    monkeypatch.setenv("AIPULSE_ENV", "actions")
    respx.get("https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day").mock(
        return_value=httpx.Response(200, content=fixture_bytes("reddit_top.json"))
    )
    # 第二个 subreddit（MachineLearning）返回 404：逐 subreddit 隔离 → reddit 降级而非失败
    respx.get("https://www.reddit.com/r/MachineLearning/top/.rss?t=day").mock(
        return_value=httpx.Response(404)
    )
    respx.get("https://huggingface.co/api/daily_papers").mock(
        return_value=httpx.Response(200, content=fixture_bytes("hf_daily_papers.json"))
    )
    result = await run_collect(
        sources=["reddit", "hf_papers"], since="30d", db_path=str(tmp_path / "t.db"), no_cache=True
    )
    assert result.skipped == []
    statuses = {r.source: r.status for r in result.results}
    assert statuses == {"reddit": STATUS_DEGRADED, "hf_papers": STATUS_OK}
    assert len(result.items) == 75  # 25 (reddit) + 50 (hf)


@respx.mock
async def test_dry_run_writes_nothing(monkeypatch, tmp_path):
    _localize(monkeypatch, tmp_path)
    _mock_feeds()
    db_path = tmp_path / "t.db"
    result = await run_collect(sources=["rss"], since="30d", dry_run=True, db_path=str(db_path))
    assert result.items
    assert result.persisted == {"inserted": 0, "updated": 0, "signals": 0}
    assert not db_path.exists(), "--dry-run 不应建库"


@respx.mock
async def test_optional_chinese_feed_failure_keeps_exit_zero(monkeypatch, tmp_path):
    """DoD ★：中文 optional 源失效时 pipeline 仍退出码 0，仅 warning。"""
    _localize(monkeypatch, tmp_path)
    _mock_feeds(qbitai=500)  # 中文 optional 源 500
    result = await run_collect(sources=["rss"], since="30d", db_path=str(tmp_path / "t.db"))
    assert result.results[0].status == STATUS_DEGRADED  # 不是 failed
    assert result.failed_sources == []
    assert result.items


@respx.mock
def test_cli_exit_code_zero_when_optional_feed_fails(monkeypatch, tmp_path):
    """DoD ★：CLI 层退出码必须为 0（中文 optional 源失效不得让 Actions 报红）。"""
    from typer.testing import CliRunner

    from aipulse.cli.commands.collect import app as collect_app

    _localize(monkeypatch, tmp_path)
    _mock_feeds(qbitai=500)  # 中文源 500
    outcome = CliRunner().invoke(
        collect_app, ["--sources", "rss", "--since", "30d", "--db", str(tmp_path / "t.db")]
    )
    assert outcome.exit_code == 0


@respx.mock
def test_cli_json_output_is_parseable(monkeypatch, tmp_path):
    import json as _json

    from typer.testing import CliRunner

    from aipulse.cli.commands.collect import app as collect_app

    _localize(monkeypatch, tmp_path)
    _mock_feeds()
    outcome = CliRunner().invoke(
        collect_app,
        ["--sources", "rss", "--since", "30d", "--db", str(tmp_path / "t.db"), "--json"],
    )
    assert outcome.exit_code == 0
    payload = _json.loads(outcome.stdout)
    assert payload["total_items"] > 0
    assert any(s["source"] == "rss" for s in payload["sources"])


@respx.mock
async def test_persisted_items_merge_arxiv_and_hf(monkeypatch, tmp_path):
    """端到端：同一篇论文分别来自 arXiv 与 HF → 库里只有 1 条且 seen_in 含两个源。"""
    _localize(monkeypatch, tmp_path)
    monkeypatch.setenv("AIPULSE_ENV", "actions")
    import json as _json

    hf_payload = _json.loads(fixture_text("hf_daily_papers.json"))
    hf_paper = hf_payload[0]["paper"]
    # 用 HF fixture 中真实存在的论文 id/标题构造 arXiv Atom —— 保证两源确实指向同一篇论文
    atom = (
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<entry>"
        f"<id>http://arxiv.org/abs/{hf_paper['id']}v1</id>"
        f"<title>{hf_paper['title']}</title>"
        f"<summary>{hf_paper.get('summary', '')}</summary>"
        "<published>2026-10-09T00:00:00Z</published>"
        "<author><name>Test Author</name></author>"
        '<link href="https://arxiv.org/abs/x" rel="alternate"/>'
        '<category term="cs.LG"/>'
        "</entry></feed>"
    )
    respx.get(ARXIV_URL).mock(return_value=httpx.Response(200, text=atom))
    respx.get("https://huggingface.co/api/daily_papers").mock(
        return_value=httpx.Response(200, content=fixture_bytes("hf_daily_papers.json"))
    )
    db_path = tmp_path / "t.db"
    for _ in range(2):  # 跑两轮，验证跨运行也能合并
        await run_collect(
            sources=["arxiv", "hf_papers"],
            since="30d",
            db_path=str(db_path),
            no_cache=True,
        )

    from aipulse.store.models import Item

    engine = engine_for(db_path)
    with Session(engine) as session:
        merged = [
            item
            for item in session.exec(select(Item)).all()
            if set(item.seen_in or []) >= {"arxiv", "hf_papers"}
        ]
        assert merged, "arXiv 与 HF 的重叠论文必须合并为一条"
        assert merged[0].skip_cluster is False
    engine.dispose()
