"""arXiv 采集器的错误可见性（C1）。

背景：10-19/21/24 的 `source_runs.json` 里 error 是
`CollectorError: [arxiv] arXiv 请求失败：`——异常 `str()` 为空，
日志里既看不出是超时还是 TLS，也没法区分 429 与其它 4xx。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from aipulse.collectors.arxiv import ArxivCollector
from aipulse.core.config import SourceConfig
from aipulse.core.errors import CollectorError


class _BoomHttp:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def get(self, *_args: object, **_kwargs: object) -> httpx.Response:
        raise self.exc


class _StatusHttp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    async def get(self, *_args: object, **_kwargs: object) -> httpx.Response:
        return httpx.Response(self.status_code, request=httpx.Request("GET", "https://x"))


def _fetch(http: object) -> str:
    collector = ArxivCollector(SourceConfig(rate_limit="1/3s"), http)  # type: ignore[arg-type]
    until = datetime(2026, 10, 24, tzinfo=UTC)
    with pytest.raises(CollectorError) as exc:
        import asyncio

        asyncio.run(collector.fetch(until - timedelta(days=1), until))
    return str(exc.value)


def test_timeout_error_carries_exception_type() -> None:
    """超时类异常 str() 为空，必须补类型名，否则日志是"请求失败："。"""
    message = _fetch(_BoomHttp(httpx.ReadTimeout("")))
    assert "ReadTimeout" in message
    assert "无错误详情" in message


def test_timeout_error_keeps_detail_when_present() -> None:
    message = _fetch(_BoomHttp(httpx.ConnectError("connection refused")))
    assert "ConnectError" in message
    assert "connection refused" in message


def test_429_message_explains_rate_limit() -> None:
    message = _fetch(_StatusHttp(429))
    assert "HTTP 429" in message
    assert "3 秒 1 次" in message


def test_other_status_has_no_rate_limit_hint() -> None:
    message = _fetch(_StatusHttp(503))
    assert "HTTP 503" in message
    assert "3 秒 1 次" not in message
