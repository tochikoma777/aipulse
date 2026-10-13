"""采集器运行时单测（respx mock，绝不打真实网络）。

覆盖：正常抓取、降级路径（GitHub → Search API、HF → 备用端点）、
optional 源失败降级、Reddit 三重补偿、availability 分级。
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from aipulse.collectors.github_trending import GitHubTrendingCollector
from aipulse.collectors.hackernews import HackerNewsCollector
from aipulse.collectors.hf_papers import HFPapersCollector
from aipulse.collectors.reddit import RedditCollector
from aipulse.collectors.rss import RSSCollector
from aipulse.core.config import FeedConfig, SourceConfig
from aipulse.utils.http import HttpClient
from tests.conftest import fixture_bytes, fixture_text

TRENDING_URL = "https://github.com/trending?since=daily"
SEARCH_URL = "https://api.github.com/search/repositories"
HF_URL = "https://huggingface.co/api/daily_papers"
REDDIT_URL = "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day"


def _http() -> HttpClient:
    return HttpClient(cache_enabled=False, max_retries=1)


def _window():
    """fixtures 是冻结快照：统一用 30 天窗口，避免测试结果随真实时间漂移。"""
    from aipulse.core.timeutil import window_since

    return window_since("30d")


@respx.mock
async def test_github_trending_fetch():
    respx.get(TRENDING_URL).mock(
        return_value=httpx.Response(200, text=fixture_text("github_trending.html"))
    )
    collector = GitHubTrendingCollector(SourceConfig(rate_limit="1/6h", weight=1.0), _http())
    since, until = _window()
    items = await collector.fetch(since, until)
    assert len(items) == 9
    assert items[0].external_id == "morluto/rea"
    assert items[0].metrics.stars_total == 191725
    assert items[0].metrics.stars_in_window == 54706
    assert items[0].language == "TypeScript"
    assert items[0].url == "https://github.com/morluto/rea"


@respx.mock
async def test_github_trending_degrades_to_search_api_when_empty():
    """HTML 改版导致解析出 0 条 → 自动降级 Search API（坑 5 的正解）。"""
    respx.get(TRENDING_URL).mock(return_value=httpx.Response(200, text="<html></html>"))
    respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=json.loads(fixture_text("github_search.json")))
    )
    collector = GitHubTrendingCollector(
        SourceConfig(rate_limit="1/6h", fallback_search_api=True), _http()
    )
    since, until = _window()
    items = await collector.fetch(since, until)
    assert collector.degraded_to_search_api is True
    assert len(items) == 10
    assert items[0].metrics.stars_total is not None


@respx.mock
async def test_github_trending_raises_on_http_error():
    respx.get(TRENDING_URL).mock(return_value=httpx.Response(500))
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(500))
    collector = GitHubTrendingCollector(SourceConfig(rate_limit="1/6h"), _http())
    since, until = _window()
    from aipulse.core.errors import CollectorError

    with pytest.raises(CollectorError):
        await collector.fetch(since, until)


@respx.mock
async def test_hf_papers_uses_official_endpoint_by_default():
    respx.get(HF_URL).mock(
        return_value=httpx.Response(200, content=fixture_bytes("hf_daily_papers.json"))
    )
    cfg = SourceConfig(rate_limit="1/1s", weight=0.9)
    collector = HFPapersCollector(cfg, _http())
    since, until = _window()
    items = await collector.fetch(since, until)
    assert len(items) == 50
    # 与 arXiv 同一篇论文 → 规范 URL 必须是 arxiv:{id}
    assert items[0].url.startswith("arxiv:")
    assert items[0].extra["arxiv_id"]


@respx.mock
async def test_hf_papers_falls_back_to_user_configured_endpoint():
    """v1.4：默认不写镜像，但用户填了 fallback_endpoints 就必须生效。"""
    respx.get(HF_URL).mock(side_effect=httpx.ConnectTimeout)
    respx.get("https://hf-mirror.com/api/daily_papers").mock(
        return_value=httpx.Response(200, content=fixture_bytes("hf_daily_papers.json"))
    )
    cfg = SourceConfig(rate_limit="1/1s", fallback_endpoints=["https://hf-mirror.com"])
    collector = HFPapersCollector(cfg, _http())
    since, until = _window()
    items = await collector.fetch(since, until)
    assert len(items) == 50


@respx.mock
async def test_reddit_rss_triple_compensation():
    respx.get(REDDIT_URL).mock(
        return_value=httpx.Response(200, content=fixture_bytes("reddit_top.json"))
    )
    cfg = SourceConfig(rate_limit="1/2s", weight=0.55, mode="rss", subreddits=["LocalLLaMA"])
    collector = RedditCollector(cfg, _http())
    since, until = _window()
    items = await collector.fetch(since, until)
    assert len(items) == 25
    # ① score 置 0（RSS 无 score）；③ 排名位次作热度代理
    assert items[0].metrics.score == 0
    assert items[0].metrics.rank_score == 1.0
    assert items[-1].metrics.rank_score == pytest.approx(1 / 25, abs=1e-3)
    # ② 该源权重 0.55（来自配置，不是硬编码）
    assert items[0].extra["source_weight"] == 0.55


def test_reddit_oauth_mode_not_implemented():
    with pytest.raises(NotImplementedError):
        RedditCollector(SourceConfig(mode="oauth"), _http())


@respx.mock
async def test_hackernews_dedupes_across_queries():
    payload = json.loads(fixture_text("hn_search.json"))
    route = respx.get("https://hn.algolia.com/api/v1/search_by_date")
    route.mock(return_value=httpx.Response(200, json=payload))
    cfg = SourceConfig(
        rate_limit="10/1s", weight=0.85, queries=["AI", "LLM"], min_points=0, hits_per_page=50
    )
    collector = HackerNewsCollector(cfg, _http())
    since, until = _window()
    items = await collector.fetch(since, until)
    # 两个关键词返回同一批 hits → 必须按 objectID 去重
    assert len({i.external_id for i in items}) == len(items)
    assert items[0].metrics.points is not None


@respx.mock
async def test_rss_optional_failure_only_degrades():
    """v1.2/v1.4：optional（中文）源失败 → degraded，core 源失败才是 failed。"""
    respx.get("https://core.example/feed").mock(
        return_value=httpx.Response(200, content=fixture_bytes("rss_feed.xml"))
    )
    respx.get("https://optional.example/feed").mock(return_value=httpx.Response(500))
    cfg = SourceConfig(
        rate_limit="1/1s",
        weight=0.6,
        feeds=[
            FeedConfig(name="英文主干", url="https://core.example/feed", tier="core"),
            FeedConfig(name="中文补充", url="https://optional.example/feed", tier="optional"),
        ],
    )
    collector = RSSCollector(cfg, _http())
    since, until = _window()
    items = await collector.fetch(since, until)
    assert items, "core 源必须仍能产出条目"
    assert collector.status == "degraded"
    assert collector.feed_status["中文补充"] == "failed"


@respx.mock
async def test_rss_marks_title_only_source():
    respx.get("https://qbitai.example/feed").mock(
        return_value=httpx.Response(200, content=fixture_bytes("rss_feed_zh.xml"))
    )
    cfg = SourceConfig(
        rate_limit="1/1s",
        weight=0.6,
        feeds=[
            FeedConfig(
                name="量子位",
                url="https://qbitai.example/feed",
                tier="optional",
                title_only=True,
                weight=0.35,
            )
        ],
    )
    collector = RSSCollector(cfg, _http())
    since, until = _window()
    items = await collector.fetch(since, until)
    assert items
    assert items[0].extra["title_only"] is True
    assert items[0].extra["source_weight"] == 0.35  # 仅标题源权重降至最低档
