"""LLM 抽象层单测（结构化输出 / 缓存 / 预算 / prompt）。

重点覆盖 DoD：非法 JSON → 修复重试 → 再失败降级跳过、全程不中断。
"""

from __future__ import annotations

from pathlib import Path

from aipulse.llm.base import ChatMessage, LLMResult, NullLLM
from aipulse.llm.budget import BudgetTracker
from aipulse.llm.cache import LLMCache, cache_key
from aipulse.llm.prompt import PromptTemplate, load_prompt, render_prompt
from aipulse.llm.structured import generate_structured
from aipulse.schema.brief import DailyBrief
from aipulse.store.db import init_db


class _StubClient:
    """顺序返回预置内容的假客户端，记录调用次数。"""

    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.calls = 0

    async def chat(self, messages, **kwargs) -> LLMResult:
        content = self.contents[min(self.calls, len(self.contents) - 1)]
        self.calls += 1
        return LLMResult(content=content, model="stub")


def _messages() -> list[ChatMessage]:
    return [ChatMessage(role="system", content="hi")]


# ── structured ──────────────────────────────────────────────────────


async def test_structured_parses_valid_json():
    client = _StubClient(['{"headline": "今日头条", "executive_summary": "总览"}'])
    parsed, _ = await generate_structured(
        client, _messages(), response_model=DailyBrief, purpose="brief_daily"
    )
    assert parsed is not None
    assert parsed.headline == "今日头条"
    assert client.calls == 1


async def test_structured_repair_retry_recovers():
    """DoD ★：非法 JSON → 修复重试 → 第二次成功，全程不抛异常。"""
    client = _StubClient(["not-json{{{", '{"headline": "修复成功"}'])
    parsed, result = await generate_structured(
        client, _messages(), response_model=DailyBrief, purpose="brief_daily"
    )
    assert parsed is not None
    assert parsed.headline == "修复成功"
    assert client.calls == 2  # 一次原始 + 一次修复重试


async def test_structured_degrades_after_two_failures():
    """DoD ★：两次都失败 → 返回 None（降级跳过），绝不 raise。"""
    client = _StubClient(["bad", "still-bad"])
    parsed, _ = await generate_structured(
        client, _messages(), response_model=DailyBrief, purpose="brief_daily"
    )
    assert parsed is None
    assert client.calls == 2


async def test_null_llm_returns_empty_without_network():
    result = await NullLLM().chat(_messages())
    assert result.content == ""
    assert result.model == "null"


# ── cache ───────────────────────────────────────────────────────────


def test_cache_key_is_deterministic():
    msgs = [ChatMessage(role="user", content="x")]
    assert cache_key("m", msgs, temperature=0.3) == cache_key("m", msgs, temperature=0.3)
    assert cache_key("m", msgs) != cache_key("other", msgs)


def test_cache_put_and_get(tmp_path: Path):
    engine = init_db(tmp_path / "t.db")
    cache = LLMCache(engine)
    key = cache_key("m", [ChatMessage(role="user", content="q")])
    assert cache.get(key) is None
    cache.put(key, prompt="q", response='{"a":1}', model="m")
    assert cache.get(key) == '{"a":1}'
    engine.dispose()


# ── budget ──────────────────────────────────────────────────────────


def test_budget_records_and_limits(tmp_path: Path):
    engine = init_db(tmp_path / "t.db")
    budget = BudgetTracker(engine, daily_limit_cny=0.01)
    assert budget.can_afford("brief") is True
    # 记一笔接近上限的花费（强模型 5w token ≈ 0.2 元）→ 超限
    budget.record(
        purpose="brief", model="m", prompt_tokens=50000, completion_tokens=1000, model_tier="strong"
    )
    assert budget.spent_today() > 0.01
    assert budget.can_afford("brief") is False
    engine.dispose()


def test_budget_cache_hit_is_free(tmp_path: Path):
    engine = init_db(tmp_path / "t.db")
    budget = BudgetTracker(engine, daily_limit_cny=0.01)
    budget.record(
        purpose="brief", model="m", prompt_tokens=1000, completion_tokens=1000, cache_hit=True
    )
    assert budget.spent_today() == 0.0
    engine.dispose()


# ── prompt ──────────────────────────────────────────────────────────


def test_load_prompt_reads_front_matter():
    template = load_prompt("brief/daily_brief")
    assert isinstance(template, PromptTemplate)
    assert template.purpose == "brief_daily"
    assert template.model_tier in ("fast", "strong")
    assert len(template.version_hash) == 8
    assert "头条" in template.body or "headline" in template.body


def test_render_prompt_injects_variables():
    text, template = render_prompt(
        "brief/daily_brief",
        items_json="[]",
        entities_json="[]",
        sections_json='["开源项目"]',
    )
    assert "[]" in text
    assert "开源项目" in text
