"""arXiv 采集器（设计方案 §5.3）。

- 端点：`export.arxiv.org/api/query`，按分类 + submittedDate 倒序
- 解析：`feedparser` 解析 Atom（fixture: arxiv_atom.xml）
- 过滤：先按分类白名单，再按关键词（可配），最后取 Top N
- 限速：配置 `rate_limit: 3/s`（硬限制，超限 503）
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import feedparser
import httpx

from aipulse.core.hashing import arxiv_id, canonical_url
from aipulse.core.logging import get_logger
from aipulse.normalize.clean import clean_text
from aipulse.schema.items import RawItem, SourceEnum, SourceMetrics

from .base import BaseCollector

log = get_logger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"


def _entry_datetime(entry: Any) -> datetime:
    """从 feedparser 的 *_parsed（struct_time，UTC）构造 datetime。"""
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed is None:
        return datetime.now(tz=UTC)
    return datetime(
        parsed.tm_year,
        parsed.tm_mon,
        parsed.tm_mday,
        parsed.tm_hour,
        parsed.tm_min,
        parsed.tm_sec,
        tzinfo=UTC,
    )


def parse_arxiv_atom(xml_text: str) -> list[dict[str, Any]]:
    """解析 arXiv Atom → 论文字典列表（纯函数，fixtures 驱动）。"""
    feed = feedparser.parse(xml_text or "")
    results: list[dict[str, Any]] = []
    for entry in feed.entries:
        raw_id = str(getattr(entry, "id", "") or getattr(entry, "link", ""))
        paper_id = arxiv_id(raw_id)
        if not paper_id:
            continue
        pdf_link = ""
        for link in getattr(entry, "links", []) or []:
            if getattr(link, "type", "") == "application/pdf":
                pdf_link = link.href
                break
        results.append(
            {
                "arxiv_id": paper_id,
                "title": clean_text(str(getattr(entry, "title", "") or "")),
                "summary": clean_text(str(getattr(entry, "summary", "") or "")),
                "authors": [
                    str(a.get("name", "")) for a in (getattr(entry, "authors", None) or [])
                ],
                "published_at": _entry_datetime(entry),
                "categories": [
                    str(t.get("term", "")) for t in (getattr(entry, "tags", None) or [])
                ],
                "comment": clean_text(str(getattr(entry, "arxiv_comment", "") or "")),
                "abs_url": f"https://arxiv.org/abs/{paper_id}",
                "pdf_url": pdf_link or f"https://arxiv.org/pdf/{paper_id}",
            }
        )
    return results


class ArxivCollector(BaseCollector):
    source = SourceEnum.ARXIV
    display_name = "arXiv"

    def healthcheck_url(self) -> str:
        return f"{ARXIV_API}?search_query=cat:cs.LG&max_results=1"

    def _build_url(self, max_results: int) -> str:
        categories = self.extra("categories") or ["cs.AI", "cs.LG", "cs.CL"]
        query = "+OR+".join(f"cat:{c}" for c in categories)
        return (
            f"{ARXIV_API}?search_query={query}"
            f"&sortBy=submittedDate&sortOrder=descending&max_results={max_results}"
        )

    async def fetch(self, since: datetime, until: datetime) -> list[RawItem]:
        max_results = int(self.extra("max_results", 200))
        try:
            response = await self.http.get(
                self._build_url(max_results),
                source=self.source.value,
                rate_limit=self.cfg.rate_limit,
            )
        except httpx.HTTPError as exc:
            raise self.raise_error(f"arXiv 请求失败：{exc}", cause=exc) from exc
        if response.status_code >= 400:
            raise self.raise_error(f"arXiv 返回 HTTP {response.status_code}")

        papers = parse_arxiv_atom(response.text)
        if not papers:
            log.warning("collector.arxiv.empty", msg="arXiv 返回 0 条（可能改版或限流）")
            return []

        # arXiv 索引有滞后：实测按 submittedDate 倒序取回的最新条目常比当天早 3-4 天，
        # 若严格按 24h 过滤会永远采空。因此允许按配置回看 N 天（默认 7 天）。
        lookback_days = int(self.extra("lookback_days", 7))
        effective_since = min(since, until - timedelta(days=lookback_days))
        if effective_since < since:
            log.warning(
                "collector.arxiv.window_widened",
                lookback_days=lookback_days,
                msg="arXiv 索引滞后，已按配置回看更长时间窗",
            )

        categories = set(self.extra("categories") or [])
        keywords = [k.lower() for k in (self.extra("keyword_filter") or [])]
        top_n = int(self.extra("top_n_after_filter", 60))

        items: list[RawItem] = []
        for paper in papers:
            if not (effective_since <= paper["published_at"] < until):
                continue
            if categories and not (categories & set(paper["categories"])):
                continue
            if keywords:
                haystack = f"{paper['title']} {paper['summary']}".lower()
                if not any(k in haystack for k in keywords):
                    continue
            items.append(self._to_item(paper))

        items.sort(key=lambda i: i.published_at, reverse=True)
        return items[:top_n]

    def _to_item(self, paper: dict[str, Any]) -> RawItem:
        paper_id = str(paper["arxiv_id"])
        return RawItem(
            source=self.source,
            external_id=paper_id,
            title=str(paper["title"]),
            # 规范 URL 统一成 arxiv:{id}，这是与 HF Daily Papers 合并成一条的前提
            url=canonical_url(str(paper["abs_url"])),
            summary=str(paper["summary"]),
            author=", ".join(paper["authors"][:3]) or None,
            published_at=paper["published_at"],
            metrics=SourceMetrics(),
            tags=list(paper["categories"]),
            language="en",
            extra={
                "arxiv_id": paper_id,
                "categories": paper["categories"],
                "authors": paper["authors"],
                "abs_url": paper["abs_url"],
                "pdf_url": paper["pdf_url"],
                "comment": paper["comment"],
                "source_weight": self.weight,
            },
        )
