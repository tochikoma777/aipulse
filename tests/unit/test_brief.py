"""每日简报推演层单测（off 档 + 渲染 + 零网络断言）。"""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import respx

from aipulse.core.config import RunMode, Settings
from aipulse.llm.base import NullLLM, build_client
from aipulse.reasoning.brief import generate_brief
from aipulse.render.json_out import render_json
from aipulse.render.markdown import render_markdown
from aipulse.schema.brief import DailyBrief
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
    assert "本次运行模式：off（未启用 LLM）" in md


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
