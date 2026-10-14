"""openai_compat（httpx 直连）单测。

覆盖 v1.7 核心：httpx 直连、错误分类（401/403 ConfigError、429/5xx 重试、其余 4xx 降级）、
json_schema 运行时自动降级、缓存命中、预算护栏。
"""

from __future__ import annotations

import httpx
import pytest
import respx

from aipulse.core.config import LLMSettings
from aipulse.core.errors import ConfigError, LLMError
from aipulse.llm.base import ChatMessage
from aipulse.llm.budget import BudgetTracker
from aipulse.llm.cache import LLMCache, cache_key
from aipulse.llm.openai_compat import (
    OpenAICompatClient,
    json_schema_support,
    reset_json_schema_memory,
)
from aipulse.store.db import init_db
from aipulse.utils.http import HttpClient

BASE_URL = "https://api.deepseek.com/v1"
ENDPOINT = f"{BASE_URL}/chat/completions"


def _settings(**kwargs) -> LLMSettings:
    defaults = {"base_url": BASE_URL, "api_key": "sk-test", "json_schema": "auto"}
    defaults.update(kwargs)
    return LLMSettings(**defaults)


def _client(settings: LLMSettings | None = None, **kwargs) -> OpenAICompatClient:
    http = HttpClient(cache_enabled=False)
    return OpenAICompatClient(settings or _settings(), http=http, **kwargs)


def _messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="你好")]


def _ok_json(content: str = '{"a": 1}') -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


_SCHEMA = {"title": "Batch", "type": "object", "properties": {"a": {"type": "integer"}}}


@pytest.fixture(autouse=True)
def _clean_memory():
    reset_json_schema_memory()
    yield
    reset_json_schema_memory()


# ── 成功 / 解析 ─────────────────────────────────────────────────────


@respx.mock
async def test_success_parses_content_and_usage():
    route = respx.post(ENDPOINT).mock(return_value=_ok_json("hello"))
    client = _client()
    result = await client.chat(_messages(), purpose="brief", model_tier="fast")
    assert result.content == "hello"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.model == "deepseek-chat"
    body = route.calls[0].request.content
    assert b'"model":"deepseek-chat"' in body
    assert b"Authorization" in b"".join(
        [(k + b": " + v) for k, v in route.calls[0].request.headers.raw]
    )


@respx.mock
async def test_strong_model_selected():
    route = respx.post(ENDPOINT).mock(return_value=_ok_json("x"))
    client = _client()
    result = await client.chat(_messages(), model_tier="strong")
    assert result.model == "deepseek-reasoner"
    assert b'"model":"deepseek-reasoner"' in route.calls[0].request.content


# ── 错误分类 ────────────────────────────────────────────────────────


@respx.mock
async def test_auth_401_raises_config_error():
    respx.post(ENDPOINT).mock(return_value=httpx.Response(401, json={"error": "bad key"}))
    client = _client()
    with pytest.raises(ConfigError):
        await client.chat(_messages())


@respx.mock
async def test_other_4xx_raises_llm_error():
    respx.post(ENDPOINT).mock(return_value=httpx.Response(422, json={"error": "bad request"}))
    client = _client()
    with pytest.raises(LLMError):
        await client.chat(_messages())


@respx.mock
async def test_retryable_5xx_retried_then_llm_error():
    # HttpClient 会退避重试；用 side_effect 返回两次 500，最终耗尽重试仍 500 → LLMError
    respx.post(ENDPOINT).mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(500),
        ]
    )
    client = _client()
    with pytest.raises(LLMError):
        await client.chat(_messages(), max_tokens=1)


# ── json_schema 运行时自动降级（§8.3）───────────────────────────────


@respx.mock
async def test_json_schema_auto_degrades_to_json_object():
    route = respx.post(ENDPOINT).mock(
        side_effect=[
            httpx.Response(
                400, json={"error": {"message": "response_format json_schema is not supported"}}
            ),
            _ok_json('{"a": 2}'),
        ]
    )
    client = _client(_settings(json_schema="auto"))
    result = await client.chat(_messages(), json_schema=_SCHEMA)
    assert result.content == '{"a": 2}'
    assert route.call_count == 2
    # 第一次带 json_schema，第二次降级为 json_object 且内嵌 schema
    first = route.calls[0].request.content
    second = route.calls[1].request.content
    assert b'"json_schema"' in first
    assert b'"json_object"' in second
    assert b"JSON Schema" in second
    # 进程内记住"不支持"
    assert json_schema_support("deepseek-chat") is False


@respx.mock
async def test_json_schema_auto_remembers_support_on_success():
    respx.post(ENDPOINT).mock(return_value=_ok_json("{}"))
    client = _client(_settings(json_schema="auto"))
    await client.chat(_messages(), json_schema=_SCHEMA)
    assert json_schema_support("deepseek-chat") is True


@respx.mock
async def test_json_schema_mode_false_uses_json_object_directly():
    route = respx.post(ENDPOINT).mock(return_value=_ok_json("{}"))
    client = _client(_settings(json_schema="false"))
    await client.chat(_messages(), json_schema=_SCHEMA)
    assert route.call_count == 1
    assert b'"json_object"' in route.calls[0].request.content


@respx.mock
async def test_json_schema_mode_true_no_fallback():
    respx.post(ENDPOINT).mock(
        return_value=httpx.Response(400, json={"error": {"message": "json_schema unsupported"}})
    )
    client = _client(_settings(json_schema="true"))
    with pytest.raises(LLMError):
        await client.chat(_messages(), json_schema=_SCHEMA)


@respx.mock
async def test_no_schema_does_not_set_response_format():
    route = respx.post(ENDPOINT).mock(return_value=_ok_json("x"))
    client = _client()
    await client.chat(_messages())
    assert b"response_format" not in route.calls[0].request.content


# ── 缓存 / 预算 ─────────────────────────────────────────────────────


@respx.mock
async def test_cache_hit_returns_cached_without_network(tmp_path):
    engine = init_db(tmp_path / "t.db")
    cache = LLMCache(engine)
    key = cache_key("deepseek-chat", _messages(), response_model_name="", temperature=0.3)
    cache.put(key, prompt="q", response='{"cached": true}', model="deepseek-chat")

    route = respx.post(ENDPOINT).mock(return_value=_ok_json("should-not-hit"))
    client = _client(cache=cache)
    result = await client.chat(_messages())
    assert result.content == '{"cached": true}'
    assert result.cached is True
    assert route.call_count == 0
    engine.dispose()


@respx.mock
async def test_budget_exceeded_raises(tmp_path):
    engine = init_db(tmp_path / "t.db")
    budget = BudgetTracker(engine, daily_limit_cny=0.001)
    budget.record(
        purpose="brief", model="m", prompt_tokens=10000, completion_tokens=1000, model_tier="strong"
    )
    route = respx.post(ENDPOINT).mock(return_value=_ok_json("x"))
    client = _client(budget=budget)
    with pytest.raises(LLMError):
        await client.chat(_messages(), purpose="brief")
    assert route.call_count == 0
    engine.dispose()


def test_missing_config_raises_config_error():
    with pytest.raises(ConfigError):
        OpenAICompatClient(
            LLMSettings(base_url="", api_key=""), http=HttpClient(cache_enabled=False)
        )
