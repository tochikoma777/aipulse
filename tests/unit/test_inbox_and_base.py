"""inbox 采集器与 BaseCollector 通用能力单测（提升 collectors 覆盖率）。"""

from __future__ import annotations

import httpx
import respx

from aipulse.collectors.base import BaseCollector
from aipulse.collectors.hackernews import HackerNewsCollector
from aipulse.collectors.inbox import InboxCollector
from aipulse.core.config import SourceConfig
from aipulse.schema.items import RawItem, SourceEnum
from aipulse.utils.http import HttpClient
from tests.conftest import fixture_bytes, fixture_text


def _http() -> HttpClient:
    return HttpClient(cache_enabled=False, max_retries=1)


async def test_inbox_fetch_reads_markdown_files(tmp_path):
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    (inbox_dir / "notes.md").write_text(
        "# 我的观察\nhttps://example.com/a 这条信息值得追踪\n", encoding="utf-8"
    )
    with respx.mock:
        respx.get("https://example.com/a").mock(
            return_value=httpx.Response(
                200,
                text="<html><head><title>示例文章</title>"
                '<meta name="description" content="摘要内容"></head></html>',
            )
        )
        collector = InboxCollector(
            SourceConfig(weight=0.5, rate_limit="10/1s"), _http(), inbox_dir=inbox_dir
        )
        items = await collector.fetch(*_window())
    assert len(items) == 1
    assert items[0].source == SourceEnum.INBOX
    assert items[0].title == "示例文章"
    assert items[0].extra["note"] == "这条信息值得追踪"


async def test_inbox_fetch_missing_dir_is_noop(tmp_path):
    collector = InboxCollector(SourceConfig(weight=0.5), _http(), inbox_dir=tmp_path / "not-exist")
    assert await collector.fetch(*_window()) == []


@respx.mock
async def test_inbox_item_from_url_survives_fetch_failure(tmp_path):
    """抓不到标题时不能丢条目：标题退化为 URL，保证"手动投喂永不失效"。"""
    respx.get("https://broken.example/x").mock(side_effect=httpx.ConnectTimeout)
    collector = InboxCollector(SourceConfig(weight=0.5), _http(), inbox_dir=tmp_path)
    item = await collector.item_from_url("https://broken.example/x", note="我的备注")
    assert item is not None
    assert item.title == "https://broken.example/x"
    assert item.summary == "我的备注"


def test_inbox_healthcheck_needs_no_network(tmp_path):
    collector = InboxCollector(SourceConfig(weight=0.5), _http(), inbox_dir=tmp_path)
    assert collector.healthcheck_url() is None


async def test_base_healthcheck_returns_false_on_error():
    class Broken(BaseCollector):
        source = SourceEnum.RSS
        display_name = "broken"

        def healthcheck_url(self) -> str:
            return "https://broken.example/feed"

        async def fetch(self, since, until) -> list[RawItem]:  # pragma: no cover - 不调用
            return []

    with respx.mock:
        respx.get("https://broken.example/feed").mock(side_effect=httpx.ConnectTimeout)
        collector = Broken(SourceConfig(), _http())
        assert await collector.healthcheck() is False


async def test_hackernews_enriches_comment_tree():
    with respx.mock:
        respx.get("https://hn.algolia.com/api/v1/search_by_date").mock(
            return_value=httpx.Response(200, content=fixture_bytes("hn_search.json"))
        )
        # 评论树端点是任意 story id：用正则匹配，避免依赖"哪条排第一"
        respx.get(url__regex=r"https://hn\.algolia\.com/api/v1/items/\d+").mock(
            return_value=httpx.Response(200, content=fixture_bytes("hn_item.json"))
        )
        cfg = SourceConfig(
            weight=0.85,
            rate_limit="10/1s",
            queries=["AI"],
            min_points=0,
            with_comments_top=1,
            hits_per_page=5,
        )
        collector = HackerNewsCollector(cfg, _http())
        items = await collector.fetch(*_window())
    assert items
    assert "comment_tree_size" in items[0].extra  # 评论树是 best-effort，成功时应写入


async def test_hackernews_partial_query_failure_keeps_results():
    """部分关键词失败（404）→ 其余关键词照常返回，源不判失败。"""
    with respx.mock:
        route = respx.get("https://hn.algolia.com/api/v1/search_by_date")
        route.side_effect = [
            httpx.Response(200, content=fixture_bytes("hn_search.json")),
            httpx.Response(404),
        ]
        cfg = SourceConfig(
            weight=0.85, rate_limit="10/1s", queries=["AI", "LLM"], min_points=0, hits_per_page=5
        )
        collector = HackerNewsCollector(cfg, _http())
        items = await collector.fetch(*_window())
    assert items


def test_hn_fixture_text_is_used():
    # 保证 fixture 存在（避免 CI 上路径漂移导致"假绿"）
    assert "hits" in fixture_text("hn_search.json")


def _window():
    from aipulse.core.timeutil import window_since

    return window_since("30d")
