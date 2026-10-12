"""fixtures 契约测试：保证真实响应快照可用、且缺失时被显式标出（不静默通过）。"""

from __future__ import annotations

import json
from pathlib import Path

import feedparser
import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

API_FIXTURES = [
    "github_trending.html",
    "arxiv_atom.xml",
    "hf_daily_papers.json",
    "hn_search.json",
]
RSS_FIXTURES = ["rss_feed.xml", "rss_feed_zh.xml"]


def _require(name: str) -> Path:
    path = FIXTURES / name
    if not path.exists():
        pytest.skip(f"{name} 未落盘：对应源探测失败，原因见 docs/数据源手册.md")
    return path


@pytest.mark.parametrize("name", API_FIXTURES + RSS_FIXTURES)
def test_fixture_is_non_empty(name):
    path = _require(name)
    assert path.stat().st_size > 0


def test_probe_report_records_every_source():
    path = _require("probe_report.json")
    report = json.loads(path.read_text(encoding="utf-8"))
    assert "probed_at" in report
    assert report["results"]
    for item in report["results"]:
        # 每个源必须有明确结论；失败的源必须带错误信息
        assert item["conclusion"], f"{item['name']} 缺少结论"
        if item["status"] is None or not (200 <= item["status"] < 300):
            assert item["error"], f"{item['name']} 失败但没有记录错误信息"


def test_arxiv_fixture_parses():
    path = _require("arxiv_atom.xml")
    feed = feedparser.parse(path.read_text(encoding="utf-8"))
    assert feed.entries, "arXiv 快照必须能解析出条目"
    first = feed.entries[0]
    assert first.get("id") and first.get("title") and first.get("published")
    assert "arxiv.org/abs/" in first["id"]


def test_hf_fixture_parses():
    path = _require("hf_daily_papers.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data
    assert "paper" in data[0]
    assert data[0]["paper"]["id"]  # arXiv 编号，跨源去重要用


def test_hn_fixture_parses():
    path = _require("hn_search.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hits"]
    hit = data["hits"][0]
    for key in ("objectID", "title", "points", "created_at_i"):
        assert key in hit


def test_github_trending_fixture_has_repo_blocks():
    import re

    path = _require("github_trending.html")
    html = path.read_text(encoding="utf-8", errors="ignore")
    repos = re.findall(r'<h2[^>]*>\s*<a[^>]+href="/([\w.\-]+/[\w.\-]+)"', html)
    assert repos, "Trending 快照必须能抽出仓库名"
    assert "<article" in html


@pytest.mark.parametrize("name", RSS_FIXTURES)
def test_rss_fixtures_parse(name):
    path = _require(name)
    feed = feedparser.parse(path.read_text(encoding="utf-8"))
    assert feed.entries, f"{name} 必须解析出条目"
    assert feed.entries[0].get("title") and feed.entries[0].get("link")
