"""每日简报推演层单测（off 档 + 渲染 + 零网络断言）。"""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import respx

from aipulse.analysis.signals import RepoStar
from aipulse.core.config import RunMode, Settings
from aipulse.llm.base import NullLLM, build_client
from aipulse.reasoning.brief import generate_brief
from aipulse.render.json_out import render_json
from aipulse.render.markdown import render_markdown
from aipulse.schema.brief import (
    DailyBrief,
    EditorNote,
    ItemComment,
    OverviewBullet,
    Section,
)
from aipulse.store.models import Item


def _item(id_: str, source: str, title: str, hot_score: float):
    return Item(
        id=id_,
        source=source,
        external_id=f"ext-{id_}",
        title=title,
        url=f"https://example.com/{id_}",
        summary="summary",
        published_at=datetime.now(tz=UTC),
        metrics={},
        seen_in=[source],
        hot_score=hot_score,
    )


def _items():
    return [
        _item("a", "github_trending", "vLLM v1", 90.0),
        _item("b", "hackernews", "GPT-5 讨论", 80.0),
        _item("c", "arxiv", "LLM 综述", 50.0),
    ]


async def test_off_mode_builds_data_brief():
    settings = Settings(mode=RunMode.OFF, llm={"api_key": ""})
    day = date.today()
    out = await generate_brief(
        client=NullLLM(),
        settings=settings,
        items=_items(),
        topics=[],
        entity_counts={},
        day=day,
        mode=RunMode.OFF,
    )
    assert out.meta == {"mode": "off"}
    assert out.brief.headline == "vLLM v1"
    assert out.brief.comments == []
    assert out.brief.stats["total_items"] == 3
    # 源 → 板块映射正确
    names = {s.name for s in out.brief.sections}
    assert "开源项目" in names and "社区舆论" in names and "论文与研究" in names


def test_markdown_annotates_run_mode():
    out_brief = DailyBrief(date=date.today(), headline="h", executive_summary="s")
    md = render_markdown(out_brief, {}, {"mode": "off"})
    assert "运行模式 off（未启用 LLM）" in md
    # off 档 overview_bullets 是统计目录，不是判断 → 标题用「今日构成」
    assert "## 📋 今日构成" in md


def test_markdown_unified_format_contract():
    """v1.14 格式契约：头条带链接、总览分条、点评四节、表格列数恒定。"""
    items = {
        "a": _item("a", "github_trending", "vLLM v1", 91.2),
        "b": _item("b", "github_trending", "LinkSwift", 70.0),
        "c": _item("c", "hackernews", "Gemini plays StarCraft", 73.1),
    }
    items["a"].metrics = {"streak_days": 3}
    brief = DailyBrief(
        date=date.today(),
        headline="推理框架进入工程化决战",
        headline_item_id="a",
        overview_bullets=[
            OverviewBullet(icon="🛠️", topic="开源", text="vLLM 连续三天霸榜"),
            OverviewBullet(icon="💬", topic="社区", text="游戏智能体引发讨论"),
        ],
        executive_summary="工程编排正在取代模型能力成为新战场。",
        sections=[
            Section(name="开源项目", item_ids=["a", "b"], summary="工具链平民化"),
            Section(name="社区舆论", item_ids=["c"]),
            Section(name="产业与新闻", item_ids=[]),
        ],
        editor_note=EditorNote(
            core="核心判断内容",
            cross_signal="交叉信号内容",
            counterintuitive="反直觉内容",
            risk="风险内容",
        ),
        comments=[
            ItemComment(
                item_id="a",
                one_liner="一句话",
                why="因为重要",
                stance="看好",
            )
        ],
    )

    md = render_markdown(
        brief,
        items,
        {"mode": "hybrid", "analysis": {"items": 3, "topics": 2}},
        generated_at=datetime(2026, 10, 17, 2, 0, tzinfo=UTC),
    )

    # 头条：来源 / 标题 / 链接 / 平台标签 / 热度
    assert "🔗 来源：GitHub Trending · [vLLM v1](https://example.com/a)" in md
    assert "🏷️ `github_trending` · 🔥 热度 91.2" in md
    # 总览分条，不再是一整段
    assert "- 🛠️ **开源**：vLLM 连续三天霸榜" in md
    assert "- 💬 **社区**：游戏智能体引发讨论" in md
    # 主编点评四个固定小节
    for heading in ("🎯 核心判断", "🔍 交叉信号", "🔄 反直觉", "⚠️ 风险提醒"):
        assert f"### {heading}" in md
    # 空板块不渲染；列数恒定：开源项目 7 列（含 ★ 总数 / 增量），其余 5 列
    assert "## 🏢 产业与新闻" not in md
    table_rows = [
        line for line in md.splitlines() if line.startswith("|") and set(line) != {"|", "-"}
    ]
    assert len(table_rows) == 1 + 2 + 1 + 1  # 两张表头 + 两个板块各 2/1 行
    assert all(line.count("|") == 8 for line in table_rows[:3])  # 开源项目：7 列
    assert all(line.count("|") == 6 for line in table_rows[3:])  # 其余板块：5 列
    # 未生成增强的条目保留整行，`为什么重要` / `立场` 用 — 占位
    assert "| [LinkSwift](https://example.com/b) | 70.0 |" in md
    assert "| [LinkSwift](https://example.com/b) | 70.0 | — | — | summary | — | — |" in md
    # 连续在榜信号进入热度列
    assert "91.2 🔥 · 连续 3 天" in md


def test_json_contains_meta():
    import json as _json

    out_brief = DailyBrief(date=date.today(), headline="h")
    payload = _json.loads(render_json(out_brief, {}, {"mode": "full"}))
    assert payload["meta"]["mode"] == "full"


@respx.mock
async def test_off_mode_makes_zero_llm_requests(monkeypatch):
    """DoD ★：off 档 httpx 从未请求过 llm.base_url（respx 断言 0 次调用）。"""
    monkeypatch.delenv("AIPULSE_LLM__API_KEY", raising=False)
    base_url = "https://api.deepseek.com/v1"
    settings = Settings(mode=RunMode.FULL, llm={"api_key": "", "base_url": base_url})
    assert settings.effective_mode() == RunMode.OFF

    client = build_client(settings)
    assert isinstance(client, NullLLM)

    route = respx.post(f"{base_url}/chat/completions").mock(
        return_value=httpx.Response(200, json={})
    )
    out = await generate_brief(
        client=client,
        settings=settings,
        items=_items(),
        topics=[],
        entity_counts={},
        day=date.today(),
        mode=RunMode.OFF,
    )
    assert route.call_count == 0
    assert out.meta["mode"] == "off"


def test_markdown_caps_items_per_section_and_reports_overflow():
    """v1.15：每板块最多 10 条，超出显示「另有 N 条」，不静默丢弃。"""
    items = {f"i{i}": _item(f"i{i}", "github_trending", f"repo-{i}", 50.0 + i) for i in range(12)}
    brief = DailyBrief(
        date=date.today(),
        sections=[Section(name="开源项目", item_ids=[f"i{i}" for i in range(12)])],
    )
    md = render_markdown(brief, items, {"mode": "hybrid"}, max_items_per_section=10)
    rows = [line for line in md.splitlines() if line.startswith("| [repo-")]
    assert len(rows) == 10
    assert "另有 2 条未展示" in md


def test_markdown_no_summary_shows_dash_not_duplicate_title():
    """v1.16：无摘要时「要点」保持 —，不回退整标题（避免第一列重复）。"""
    item = _item("x", "hackernews", "How the Claude Code team does code review", 80.0)
    item.summary = ""
    brief = DailyBrief(
        date=date.today(),
        sections=[Section(name="社区舆论", item_ids=["x"])],
    )
    md = render_markdown(brief, {"x": item}, {"mode": "hybrid"})
    row = next(line for line in md.splitlines() if line.startswith("| ["))
    assert row.count("How the Claude Code team does code review") == 1
    assert row.endswith("| — | — | — |")


def test_sections_dedupe_to_source_primary_section():
    """v1.16：同一条目跨板块出现时，只保留源对应的主板块。"""
    from aipulse.reasoning.brief import _ensure_single_section

    items = {
        "rss1": _item("rss1", "rss", "Apple ML Research", 80.0),
        "gh1": _item("gh1", "github_trending", "vLLM", 90.0),
    }
    sections = [
        Section(name="社区舆论", item_ids=["rss1"]),
        Section(name="开源项目", item_ids=["gh1"]),
        Section(name="产业与新闻", item_ids=["rss1"]),
    ]
    _ensure_single_section(sections, items)
    by_name = {section.name: section.item_ids for section in sections}
    assert by_name["社区舆论"] == []
    assert by_name["产业与新闻"] == ["rss1"]
    assert by_name["开源项目"] == ["gh1"]


def _rea_star() -> RepoStar:
    return RepoStar(
        entity_key="morluto/rea",
        total=270369.0,
        delta=8617.0,
        status="ok",
        last_ts=datetime(2026, 10, 16, 1, 3, 59, tzinfo=UTC),
        hours=10.3,
    )


def test_markdown_shows_star_total_and_delta_after_heat():
    """§5.14 任务 1：「热度」之后紧跟 ★ 总数 / 增量（绝对增量，不是速率）。"""
    item = _item("a", "github_trending", "vLLM v1", 91.2)
    brief = DailyBrief(date=date.today(), sections=[Section(name="开源项目", item_ids=["a"])])
    stars = {
        "ext-a": RepoStar(
            entity_key="ext-a",
            total=1200.0,
            delta=200.0,
            status="ok",
            last_ts=datetime(2026, 10, 17, 1, 0, tzinfo=UTC),
            hours=24.0,
        )
    }
    md = render_markdown(brief, {"a": item}, {"mode": "hybrid"}, repo_stars=stars)
    header = next(line for line in md.splitlines() if line.startswith("| 项目 |"))
    assert header == "| 项目 | 热度 | ★ 总数 | 增量 | 要点 | 为什么重要 | 立场 |"
    row = next(line for line in md.splitlines() if line.startswith("| [vLLM v1]"))
    assert "| 91.2 🔥 | 1200 | +200 / 24h |" in row


def test_markdown_velocity_board_keeps_dropped_repo():
    """§5.14 任务 2：掉榜的 REA 仍出现在增速榜，已展示项目不重复出现。"""
    items = {
        "a": _item("a", "github_trending", "vLLM v1", 91.2),
        "b": _item("b", "github_trending", "LinkSwift", 70.0),
    }
    brief = DailyBrief(date=date.today(), sections=[Section(name="开源项目", item_ids=["a", "b"])])
    stars = {
        "ext-a": RepoStar(
            entity_key="ext-a",
            total=1200.0,
            delta=200.0,
            status="ok",
            last_ts=datetime(2026, 10, 17, 1, 0, tzinfo=UTC),
            hours=24.0,
        ),
        "morluto/rea": _rea_star(),
    }
    md = render_markdown(brief, items, {"mode": "hybrid"}, repo_stars=stars)

    assert "### 📈 增速榜（追踪中）" in md
    assert "- **morluto/rea** · ★270369 · +8617 / 10h · 上次在榜 10-16" in md
    # 今日已展示 → 不进榜（避免同一项目出现两次）
    assert "- **ext-a**" not in md


def test_markdown_hides_velocity_board_when_empty_or_disabled():
    """红线 43：0 条时整个区块都不显示（不能只剩空标题）。"""
    item = _item("a", "github_trending", "vLLM v1", 91.2)
    brief = DailyBrief(date=date.today(), sections=[Section(name="开源项目", item_ids=["a"])])
    only_cold = {
        "morluto/rea": RepoStar(
            entity_key="morluto/rea",
            total=270369.0,
            delta=None,
            status="cold_start",
            last_ts=datetime(2026, 10, 16, 1, 3, 59, tzinfo=UTC),
        )
    }
    md = render_markdown(brief, {"a": item}, {"mode": "hybrid"}, repo_stars=only_cold)
    assert "增速榜" not in md

    md_disabled = render_markdown(
        brief,
        {"a": item},
        {"mode": "hybrid"},
        repo_stars={"morluto/rea": _rea_star()},
        velocity_board_enabled=False,
    )
    assert "增速榜" not in md_disabled


def test_markdown_velocity_board_sorts_by_daily_average_and_shows_window():
    """★ 增速榜按日均排序，但显示给读者的是绝对增量 + 窗口。"""
    anchor = datetime(2026, 10, 17, 8, 0, tzinfo=UTC)
    stars = {
        "org/long": RepoStar(
            entity_key="org/long",
            total=15000.0,
            delta=5000.0,
            status="ok",
            last_ts=anchor,
            hours=160.0,
        ),
        "org/short": RepoStar(
            entity_key="org/short",
            total=4000.0,
            delta=3000.0,
            status="ok",
            last_ts=anchor,
            hours=10.0,
        ),
    }
    brief = DailyBrief(date=date.today(), sections=[Section(name="开源项目", item_ids=[])])
    md = render_markdown(brief, {}, {"mode": "hybrid"}, repo_stars=stars)

    rows = [line for line in md.splitlines() if line.startswith("- **org/")]
    assert rows[0].startswith("- **org/short**")
    assert "+3000 / 10h" in rows[0]
    assert rows[1].startswith("- **org/long**")
    assert "+5000 / 160h" in rows[1]
