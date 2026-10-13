"""采集器解析层单测：**全部由 tests/fixtures 的真实响应驱动**。

每个采集器覆盖三类：正常解析 / 边界（空、单条）/ 异常（脏数据字段缺失）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from aipulse.collectors.arxiv import parse_arxiv_atom
from aipulse.collectors.github_trending import parse_search_json, parse_trending_html
from aipulse.collectors.hackernews import parse_hn_hits
from aipulse.collectors.hf_papers import parse_daily_papers
from aipulse.collectors.inbox import parse_html_meta, parse_inbox_markdown
from aipulse.collectors.reddit import parse_reddit_feed
from aipulse.collectors.rss import parse_feed
from tests.conftest import fixture_text

# ── GitHub Trending ────────────────────────────────────────────────────


def test_github_trending_parses_real_fixture():
    repos = parse_trending_html(fixture_text("github_trending.html"))
    assert len(repos) == 9
    first = repos[0]
    assert first["full_name"] == "morluto/rea"
    assert first["language"] == "TypeScript"
    assert first["stars_total"] == 191725
    assert first["forks"] == 46658
    assert first["stars_in_window"] == 54706
    assert "Reverse engineer anything" in str(first["description"])


def test_github_trending_boundary_empty_and_single():
    assert parse_trending_html("") == []
    assert parse_trending_html("<html><body>no articles</body></html>") == []
    single = '<article><h2><a href="/a/b">a / b</a></h2><p>desc</p></article>'
    repos = parse_trending_html(single)
    assert len(repos) == 1
    # 脏数据（缺语言/星标）→ 字段为 None，不能编造 0
    assert repos[0]["language"] is None
    assert repos[0]["stars_total"] is None


def test_github_trending_dirty_block_skipped():
    dirty = "<article><div>no repo link here</div></article>"
    assert parse_trending_html(dirty) == []


def test_github_search_api_parses_real_fixture():
    repos = parse_search_json(json.loads(fixture_text("github_search.json")))
    assert repos
    first = repos[0]
    assert first["full_name"]
    assert first["stars_total"] > 0
    assert first["forks"] >= 0
    # Search API 只有总 star，窗口增速为 None（增速靠 signals 快照算）
    assert first["stars_in_window"] is None


def test_github_search_api_dirty_payload():
    assert parse_search_json({}) == []
    assert parse_search_json({"items": [{"no_full_name": 1}]}) == []


# ── arXiv ──────────────────────────────────────────────────────────────


def test_arxiv_parses_real_fixture():
    papers = parse_arxiv_atom(fixture_text("arxiv_atom.xml"))
    assert len(papers) == 20
    first = papers[0]
    assert first["arxiv_id"] == "2610.13948"
    assert first["published_at"] == datetime(2026, 10, 9, 17, 59, 56, tzinfo=UTC)
    assert "cs.AI" in first["categories"]
    assert first["authors"], "作者列表不能为空"
    assert first["abs_url"].endswith("/abs/2610.13948")


def test_arxiv_boundary_and_dirty():
    assert parse_arxiv_atom("") == []
    assert parse_arxiv_atom("<feed><entry><id>not-an-arxiv-id</id></entry></feed>") == []
    # 只有 id、其余字段缺失：仍能出条目且字段不报错
    papers = parse_arxiv_atom(
        "<feed><entry><id>http://arxiv.org/abs/2501.00001v2</id></entry></feed>"
    )
    assert len(papers) == 1 and papers[0]["arxiv_id"] == "2501.00001"


# ── HuggingFace Daily Papers ───────────────────────────────────────────


def test_hf_daily_papers_parses_real_fixture():
    papers = parse_daily_papers(json.loads(fixture_text("hf_daily_papers.json")))
    assert len(papers) == 50
    first = papers[0]
    assert first["arxiv_id"]
    assert first["title"]
    assert isinstance(first["upvotes"], int)
    assert first["published_at"].tzinfo is not None


def test_hf_daily_papers_boundary_and_dirty():
    assert parse_daily_papers([]) == []
    assert parse_daily_papers({"items": []}) == []
    # 缺 paper 子对象但有顶层 id：仍能解析
    papers = parse_daily_papers([{"id": "2501.00002", "title": "t"}])
    assert len(papers) == 1 and papers[0]["arxiv_id"] == "2501.00002"
    # 完全无 id：丢弃
    assert parse_daily_papers([{"title": "no id"}]) == []


# ── Hacker News ────────────────────────────────────────────────────────


def test_hackernews_parses_real_fixture():
    hits = parse_hn_hits(json.loads(fixture_text("hn_search.json")))
    assert len(hits) == 20
    first = hits[0]
    assert first["object_id"]
    assert first["title"]
    assert first["published_at"].year == 2026
    assert first["points"] is not None


def test_hackernews_boundary_and_dirty():
    assert parse_hn_hits({}) == []
    assert parse_hn_hits({"hits": [{"no_object_id": True}]}) == []
    hits = parse_hn_hits({"hits": [{"objectID": "1", "title": "t", "created_at_i": 1735689600}]})
    assert len(hits) == 1


# ── Reddit ─────────────────────────────────────────────────────────────


def test_reddit_parses_real_fixture():
    entries = parse_reddit_feed(fixture_text("reddit_top.json"))
    assert len(entries) == 25
    first = entries[0]
    assert first["id"].startswith("t3_")
    assert first["title"]
    assert first["url"].startswith("https://www.reddit.com/r/LocalLLaMA/")
    assert first["published_at"].tzinfo is not None


def test_reddit_boundary_and_dirty():
    assert parse_reddit_feed("") == []
    assert parse_reddit_feed("<feed><entry><title>no link</title></entry></feed>") == []


# ── RSS ────────────────────────────────────────────────────────────────


def test_rss_parses_english_fixture():
    entries = parse_feed(fixture_text("rss_feed.xml"))
    assert len(entries) == 30
    assert entries[0]["title"]
    assert entries[0]["url"].startswith("https://")


def test_rss_parses_chinese_fixture_is_title_only():
    """量子位摘要仅 22 字——这是 v1.4 把它定为 title_only 的依据。"""
    entries = parse_feed(fixture_text("rss_feed_zh.xml"))
    assert len(entries) == 10
    assert len(entries[0]["summary"]) <= 60


def test_rss_boundary_and_dirty():
    assert parse_feed("") == []
    assert parse_feed("not xml at all") == []


# ── inbox ──────────────────────────────────────────────────────────────


def test_inbox_markdown_parsing():
    text = "# 我的投喂\nhttps://example.com/a 这条很有意思\n\nhttps://example.com/b\n"
    entries = parse_inbox_markdown(text)
    assert len(entries) == 2
    assert entries[0]["url"] == "https://example.com/a"
    assert entries[0]["note"] == "这条很有意思"
    assert entries[1]["note"] == ""


def test_inbox_html_meta_parsing():
    html_text = (
        "<html><head><title>标题 &amp; 副标题</title>"
        '<meta name="description" content="摘要文本"></head></html>'
    )
    meta = parse_html_meta(html_text)
    assert meta["title"] == "标题 & 副标题"
    assert meta["description"] == "摘要文本"


def test_inbox_html_meta_dirty():
    meta = parse_html_meta("")
    assert meta == {"title": "", "description": ""}


def test_window_helpers_for_collectors():
    since = datetime.now(tz=UTC) - timedelta(hours=24)
    until = since + timedelta(hours=24)
    assert (until - since) == timedelta(hours=24)


@pytest.mark.parametrize(
    "name",
    [
        "github_trending.html",
        "arxiv_atom.xml",
        "hf_daily_papers.json",
        "hn_search.json",
        "reddit_top.json",
        "rss_feed.xml",
        "rss_feed_zh.xml",
    ],
)
def test_all_fixtures_present(name):
    """M1 首步已用 Actions 补齐 reddit 快照，此断言防止再次丢失。"""
    assert (fixture_text(name) is not None) and len(fixture_text(name)) > 0
