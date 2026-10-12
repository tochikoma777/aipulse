import asyncio

import httpx
import pytest
import respx

from aipulse.utils.http import (
    DEFAULT_USER_AGENT,
    ConfigError,
    HttpCache,
    HttpClient,
    RateLimit,
    TokenBucket,
    resolve_proxy,
)


def test_rate_limit_parse():
    assert RateLimit.parse("3/s") == RateLimit(3, 1.0)
    assert RateLimit.parse("10/1s") == RateLimit(10, 1.0)
    assert RateLimit.parse("1/6h").seconds == 6 * 3600
    assert RateLimit.parse("2/30m").seconds == 1800
    with pytest.raises(ConfigError):
        RateLimit.parse("abc")
    with pytest.raises(ConfigError):
        RateLimit.parse("0/s")


async def test_token_bucket_limits_rate():
    clock = [0.0]
    bucket = TokenBucket(RateLimit.parse("2/s"), clock=lambda: clock[0])

    await bucket.acquire()
    await bucket.acquire()
    assert bucket.available() == 0
    # 令牌耗尽后需要等待（0.5s/个），推进时钟即可拿到
    assert bucket.wait_time() == pytest.approx(0.5)
    clock[0] += 0.5
    assert bucket.wait_time() == 0.0
    await bucket.acquire()


async def test_token_bucket_caps_at_capacity():
    clock = [0.0]
    bucket = TokenBucket(RateLimit.parse("1/6h"), clock=lambda: clock[0])
    await bucket.acquire()
    clock[0] += 3600 * 100  # 攒很久也不会超过容量
    assert bucket.available() == 1.0


def test_cache_roundtrip_and_ttl(tmp_path):
    cache = HttpCache(tmp_path / "http.sqlite", ttl_s=60)
    key = HttpCache.make_key("GET", "https://example.com/x", {"a": 1})
    response = httpx.Response(
        200,
        headers={"Content-Type": "application/json"},
        content=b'{"ok": true}',
        request=httpx.Request("GET", "https://example.com/x"),
    )
    assert cache.get(key) is None
    cache.put(key, "https://example.com/x", response)
    cached = cache.get(key)
    assert cached is not None
    assert cached.json() == {"ok": True}
    assert cached.extensions["from_cache"] is True
    assert cache.get(key, ttl_s=-1) is None  # TTL 过期后不返回
    cache.clear()
    assert cache.get(key) is None


@respx.mock
async def test_get_returns_response():
    respx.get("https://example.com/x").mock(return_value=httpx.Response(200, json={"ok": True}))
    async with HttpClient(cache_enabled=False) as client:
        response = await client.get("https://example.com/x", source="unit")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@respx.mock
async def test_unified_user_agent():
    route = respx.get("https://example.com/ua").mock(return_value=httpx.Response(200, text="ok"))
    async with HttpClient(cache_enabled=False) as client:
        await client.get("https://example.com/ua", source="unit")
    assert route.calls[0].request.headers["User-Agent"] == DEFAULT_USER_AGENT


@respx.mock
async def test_retries_only_retryable_status():
    route = respx.get("https://example.com/retry").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(429),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with HttpClient(cache_enabled=False, max_retries=3) as client:
        response = await client.get("https://example.com/retry", source="unit")
    assert response.status_code == 200
    assert route.call_count == 3


@respx.mock
async def test_4xx_not_retried():
    route = respx.get("https://example.com/404").mock(return_value=httpx.Response(404))
    async with HttpClient(cache_enabled=False, max_retries=3) as client:
        response = await client.get("https://example.com/404", source="unit")
    assert response.status_code == 404
    assert route.call_count == 1


@respx.mock
async def test_retry_exhausted_returns_last_response():
    route = respx.get("https://example.com/down").mock(return_value=httpx.Response(503))
    async with HttpClient(cache_enabled=False, max_retries=2) as client:
        response = await client.get("https://example.com/down", source="unit")
    assert response.status_code == 503
    assert route.call_count == 2


@respx.mock
async def test_cache_avoids_second_request(tmp_path):
    route = respx.get("https://example.com/cached").mock(
        return_value=httpx.Response(200, json={"n": 1})
    )
    async with HttpClient(
        cache_enabled=True, cache_path=tmp_path / "http.sqlite", cache_ttl_s=60
    ) as client:
        first = await client.get("https://example.com/cached", source="unit")
        second = await client.get("https://example.com/cached", source="unit")
    assert first.status_code == second.status_code == 200
    assert route.call_count == 1
    assert client.stats["cache_hits"] == 1


@respx.mock
async def test_no_cache_flag_disables_cache(tmp_path):
    route = respx.get("https://example.com/nocache").mock(
        return_value=httpx.Response(200, text="x")
    )
    async with HttpClient(cache_enabled=True, cache_path=tmp_path / "http.sqlite") as client:
        await client.get("https://example.com/nocache", source="unit", cache=False)
        await client.get("https://example.com/nocache", source="unit", cache=False)
    assert route.call_count == 2


def test_proxy_resolution_and_priority():
    assert resolve_proxy({"HTTPS_PROXY": "http://a:1"}) == "http://a:1"
    assert resolve_proxy({"https_proxy": "http://b:2"}) == "http://b:2"
    assert resolve_proxy({"HTTP_PROXY": "http://c:3"}) == "http://c:3"
    assert resolve_proxy({}) is None


async def test_timeout_exception_propagates():
    """超时属于可重试异常，重试耗尽后必须抛出（由调用方记录到 source_runs）。"""
    async with HttpClient(cache_enabled=False, max_retries=2) as client:
        with respx.mock:
            respx.get("https://example.com/timeout").mock(side_effect=httpx.ConnectTimeout)
            with pytest.raises(httpx.ConnectTimeout):
                await client.get("https://example.com/timeout", source="unit")
    await asyncio.sleep(0)  # 确保事件循环无残留告警
