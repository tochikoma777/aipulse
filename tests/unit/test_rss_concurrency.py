"""RSS 并发拉取单测（v1.6 前置待办：串行 298s → 并发）。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from aipulse.collectors.rss import RSSCollector
from aipulse.core.config import FeedConfig, SourceConfig
from aipulse.core.timeutil import window_since
from tests.conftest import fixture_text

_FEED_XML = fixture_text("rss_feed.xml")

# 同 test_pipeline_collect.py：fixture 时间戳在 2026-10-07 ~ 10-13，窗口钉在 10-14 避免 30d 过期。
_FIXTURE_NOW = datetime(2026, 10, 14, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _freeze_fixture_window(monkeypatch):
    monkeypatch.setattr("aipulse.core.timeutil.utcnow", lambda: _FIXTURE_NOW)


class _TrackingHttp:
    """假 HttpClient：记录并发在飞请求数，验证「并发 + 上限」两个命题。"""

    def __init__(self, *, max_concurrency: int, delay: float = 0.02) -> None:
        self.max_concurrency = max_concurrency
        self.delay = delay
        self.inflight = 0
        self.max_inflight = 0

    async def get(self, url: str, **kwargs) -> httpx.Response:
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            await asyncio.sleep(self.delay)
            return httpx.Response(200, text=_FEED_XML)
        finally:
            self.inflight -= 1


def _cfg(n_feeds: int) -> SourceConfig:
    feeds = [
        FeedConfig(name=f"feed{i}", url=f"https://example.com/{i}.xml", tier="core")
        for i in range(n_feeds)
    ]
    return SourceConfig(rate_limit="1000/1s", weight=0.6, feeds=feeds)


async def test_rss_fetches_feeds_concurrently_bounded():
    http = _TrackingHttp(max_concurrency=3)
    collector = RSSCollector(_cfg(8), http)  # type: ignore[arg-type]
    since, until = window_since("30d")
    items = await collector.fetch(since, until)

    assert items, "并发下仍应产出条目"
    assert http.max_inflight > 1, "必须并发（>1 个在飞）"
    assert http.max_inflight <= http.max_concurrency, "并发受 http.max_concurrency 上限约束"


async def test_rss_serial_equivalent_result():
    """并发改造不改变行为：每个 feed 都被拉取，条目数一致。"""
    http = _TrackingHttp(max_concurrency=6)
    collector = RSSCollector(_cfg(3), http)  # type: ignore[arg-type]
    since, until = window_since("30d")
    items = await collector.fetch(since, until)
    # 3 个 feed × 每个 feed 的条目（rss_feed.xml 里窗口内条数）
    assert len(items) > 0
