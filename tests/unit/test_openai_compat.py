"""openai_compat（httpx 直连）单测。

覆盖 v1.7 核心：httpx 直连、错误分类（401/403 ConfigError、429/5xx 重试、其余 4xx 降级）、
json_schema 运行时自动降级、缓存命中、预算护栏。
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from sqlmodel import Session, select

from aipulse.core.config import LLMSettings
from aipulse.core.errors import ConfigError, LLMError, LLMTruncationError
from aipulse.llm.base import ChatMessage
from aipulse.llm.budget import BudgetTracker
from aipulse.llm.cache import LLMCache, cache_key
from aipulse.llm.openai_compat import (
    OpenAICompatClient,
    json_schema_support,
    reset_json_schema_memory,
)
from aipulse.store.db import init_db
from aipulse.store.models import LLMUsage
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
async def test_read_timeout_comes_from_llm_settings_not_http_default():
    """★ 回归防线：不显式传 timeout，就会吃 HttpClient 的默认 20s——那是对采集请求定的。

    Actions 首跑 hybrid 时 20s 读超时把预言生成打断，generated=0；而 `llm.timeout_s: 120`
    当时完全是死配置。strong 档（思维链）比 fast 慢，故单独给更长的读超时。
    """

    class _SpyHttp:
        def __init__(self) -> None:
            self.read_timeouts: list[float | None] = []

        async def request(
            self, method, url, *, source=None, headers=None, json_body=None, timeout=None, **kwargs
        ):
            self.read_timeouts.append(timeout.read)
            return _ok_json("{}")

    spy = _SpyHttp()
    settings = _settings(timeout_s=42, timeout_strong_s=180)
    client = OpenAICompatClient(settings, http=spy)

    await client.chat(_messages(), model_tier="fast")
    await client.chat(_messages(), model_tier="strong")

    assert spy.read_timeouts == [42, 180]


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
async def test_degrades_to_plain_when_both_structured_params_rejected():
    """★ 回归防线：json_schema 与 json_object 双双报 400 时，第三级 plain 必须能救回来。

    `deepseek-reasoner`（R1 系列）两个结构化参数都不支持——之前阶梯只到 json_object，
    于是这种模型每次都一路降到 degraded，主编点评永远为空。
    """
    route = respx.post(ENDPOINT).mock(
        side_effect=[
            httpx.Response(
                400, json={"error": {"message": "response_format json_schema is not supported"}}
            ),
            httpx.Response(
                400, json={"error": {"message": "response_format json_object is not supported"}}
            ),
            _ok_json('{"a": 3}'),
        ]
    )
    client = _client(_settings(json_schema="auto"))
    result = await client.chat(_messages(), json_schema=_SCHEMA)
    assert result.content == '{"a": 3}'
    assert route.call_count == 3

    formats = [json.loads(c.request.content).get("response_format") for c in route.calls]
    assert formats[0]["type"] == "json_schema"
    assert formats[1]["type"] == "json_object"
    assert formats[2] is None  # plain 级不带任何 response_format

    assert json_schema_support("deepseek-chat") is False


@respx.mock
async def test_format_memory_is_per_model_not_global():
    """★ 回归防线：降级记忆按 (model, format) 存，不是全局布尔。

    同一进程里 reasoner 与 chat 混用：若记忆是全局的，先跑的 reasoner 会把
    chat 也拖下水，chat 本可用的 json_object 被白白跳过。
    """
    seen: list[tuple[str, str | None]] = []

    def _respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        fmt = (body.get("response_format") or {}).get("type")
        seen.append((body["model"], fmt))
        if body["model"] == "deepseek-reasoner":
            # R1 系列：任何 response_format 都拒绝
            if fmt is not None:
                return httpx.Response(
                    400, json={"error": {"message": "response_format is not supported"}}
                )
            return _ok_json('{"a": 1}')
        # deepseek-chat：不支持 json_schema，但支持 json_object
        if fmt == "json_schema":
            return httpx.Response(
                400, json={"error": {"message": "response_format is not supported"}}
            )
        return _ok_json('{"a": 2}')

    respx.post(ENDPOINT).mock(side_effect=_respond)
    settings = _settings(json_schema="auto")
    client = OpenAICompatClient(settings, http=HttpClient(cache_enabled=False))

    await client.chat(_messages(), model_tier="strong", json_schema=_SCHEMA)
    await client.chat(_messages(), model_tier="fast", json_schema=_SCHEMA)

    # reasoner 走满三级；chat 只降到 json_object 就成功，没被 reasoner 的记忆连坐
    assert seen == [
        ("deepseek-reasoner", "json_schema"),
        ("deepseek-reasoner", "json_object"),
        ("deepseek-reasoner", None),
        ("deepseek-chat", "json_schema"),
        ("deepseek-chat", "json_object"),
    ]


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


def _ok_json_with_finish(content: str, finish_reason: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


@respx.mock
async def test_finish_reason_is_exposed_on_result():
    respx.post(ENDPOINT).mock(return_value=_ok_json_with_finish("done", "stop"))
    result = await _client().chat(_messages())
    assert result.finish_reason == "stop"
    assert result.content == "done"


@respx.mock
async def test_finish_reason_length_raises_and_skips_cache(tmp_path):
    """★ 静默失败防线：撞 max_tokens 必须报错，且半截内容绝不能写进缓存。"""
    engine = init_db(tmp_path / "t.db")
    cache = LLMCache(engine)
    route = respx.post(ENDPOINT).mock(return_value=_ok_json_with_finish('{"trunc": ', "length"))
    client = _client(cache=cache, budget=BudgetTracker(engine, daily_limit_cny=100.0))
    with pytest.raises(LLMTruncationError) as excinfo:
        await client.chat(_messages(), json_schema=_SCHEMA, purpose="brief")
    assert excinfo.value.completion_tokens == 5
    assert route.call_count == 1
    # 若截断结果被缓存，第二次会命中缓存直接返回；这里必须仍然打网络
    with pytest.raises(LLMError, match="截断"):
        await client.chat(_messages(), json_schema=_SCHEMA, purpose="brief")
    assert route.call_count == 2
    # 截断也是真花了钱：usage 必须落库，并在 error 里留下可查的痕迹
    with Session(engine) as session:
        rows = session.exec(select(LLMUsage)).all()
    assert rows and rows[0].error and "length" in rows[0].error
    engine.dispose()


def test_missing_config_raises_config_error():
    with pytest.raises(ConfigError):
        OpenAICompatClient(
            LLMSettings(base_url="", api_key=""), http=HttpClient(cache_enabled=False)
        )


@respx.mock
async def test_degrade_order_blocks_only_the_disabled_purposes(tmp_path):
    """超支 2 个额度 → debate/trend 关，简报仍放行；trend 请求不得打到网络。"""
    engine = init_db(tmp_path / "t.db")
    budget = BudgetTracker(
        engine,
        daily_limit_cny=1.0,
        degrade_order=["debate", "trend", "brief_topn", "all"],
    )
    budget.record(purpose="misc", model="m", prompt_tokens=2_200_000, completion_tokens=0)
    route = respx.post(ENDPOINT).mock(return_value=_ok_json("ok"))
    client = _client(budget=budget)

    with pytest.raises(LLMError, match="预算"):
        await client.chat(_messages(), purpose="trend")
    assert route.call_count == 0

    result = await client.chat(_messages(), purpose="brief_daily")
    assert result.content == "ok"
    assert route.call_count == 1
    engine.dispose()
