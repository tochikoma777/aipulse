"""Hacker News 采集器（Algolia，设计方案 §5.5）。

- `search_by_date` 多关键词**串行**查询后按 objectID 去重（Algolia 免费额度宽松，串行即可）
- 可选对 Top N 取评论树（`/api/v1/items/{id}`），V1 默认只对前 3 条开启
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from aipulse.core.hashing import canonical_url
from aipulse.core.logging import get_logger
from aipulse.normalize.clean import clean_text
from aipulse.schema.items import RawItem, SourceEnum, SourceMetrics

from .base import BaseCollector

log = get_logger(__name__)

HN_SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
HN_ITEM = "https://hn.algolia.com/api/v1/items/{story_id}"

DEFAULT_QUERIES = ["AI", "LLM", "GPT", "Claude", "open source model", "agent", "inference"]


def parse_hn_hits(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """解析 search_by_date 响应（fixture: hn_search.json）。"""
    results: list[dict[str, Any]] = []
    for hit in payload.get("hits") or []:
        story_id = str(hit.get("objectID") or hit.get("story_id") or "").strip()
        if not story_id:
            continue
        created_at_i = hit.get("created_at_i")
        published = (
            datetime.fromtimestamp(int(created_at_i), tz=UTC)
            if isinstance(created_at_i, (int, float))
            else datetime.now(tz=UTC)
        )
        results.append(
            {
                "object_id": story_id,
                "title": clean_text(str(hit.get("title") or hit.get("story_title") or "")),
                "url": str(hit.get("url") or f"https://news.ycombinator.com/item?id={story_id}"),
                "author": hit.get("author"),
                "points": hit.get("points"),
                "num_comments": hit.get("num_comments"),
                "published_at": published,
                "story_text": clean_text(str(hit.get("story_text") or "")),
            }
        )
    return results


class HackerNewsCollector(BaseCollector):
    source = SourceEnum.HACKERNEWS
    display_name = "Hacker News"

    def healthcheck_url(self) -> str:
        return f"{HN_SEARCH}?query=AI&hitsPerPage=1"

    async def fetch(self, since: datetime, until: datetime) -> list[RawItem]:
        queries = self.extra("queries") or DEFAULT_QUERIES
        min_points = int(self.extra("min_points", 0))
        hits_per_page = int(self.extra("hits_per_page", 50))

        seen: dict[str, RawItem] = {}
        failed_queries = 0
        for query in queries:
            params = {
                "query": str(query),
                "tags": "story",
                "numericFilters": f"created_at_i>{int(since.timestamp())}",
                "hitsPerPage": str(hits_per_page),
            }
            try:
                response = await self.http.get(
                    HN_SEARCH,
                    source=self.source.value,
                    params=params,
                    rate_limit=self.cfg.rate_limit,
                )
            except httpx.HTTPError as exc:
                # 单关键词失败不影响其他关键词（HN 是舆论板块，少一路信号不至于归零）
                failed_queries += 1
                log.warning("collector.hackernews.query_failed", query=query, error=repr(exc))
                continue
            if response.status_code >= 400:
                failed_queries += 1
                log.warning(
                    "collector.hackernews.query_http", query=query, status=response.status_code
                )
                continue

            for hit in parse_hn_hits(response.json()):
                if hit["object_id"] in seen:
                    continue
                points = hit.get("points") or 0
                if points < min_points:
                    continue
                if not (since <= hit["published_at"] < until):
                    continue
                seen[hit["object_id"]] = self._to_item(hit)

        if failed_queries and failed_queries == len(queries):
            # 全部关键词都失败 = 源级故障，必须显式失败（不能静默返回空）
            raise self.raise_error(f"全部 {len(queries)} 个查询均失败")
        if not seen:
            log.warning("collector.hackernews.empty", queries=len(queries))
            return []

        items = sorted(seen.values(), key=lambda i: i.metrics.points or 0, reverse=True)
        top_n = int(self.extra("with_comments_top", 0))
        if top_n:
            await self._enrich_comments(items[:top_n])
        return items

    async def _enrich_comments(self, items: list[RawItem]) -> None:
        """取评论树，记录评论条数作为舆论热度信号。"""
        for item in items:
            try:
                response = await self.http.get(
                    HN_ITEM.format(story_id=item.external_id),
                    source=self.source.value,
                    rate_limit=self.cfg.rate_limit,
                )
            except Exception as exc:  # 评论树是 best-effort
                log.debug("collector.hackernews.item_failed", id=item.external_id, error=repr(exc))
                continue
            if response.status_code >= 400:
                continue
            payload = response.json() or {}
            children = payload.get("children") or []
            item.extra["comment_tree_size"] = len(children)
            item.metrics.num_comments = item.metrics.num_comments or len(children)

    def _to_item(self, hit: dict[str, Any]) -> RawItem:
        return RawItem(
            source=self.source,
            external_id=str(hit["object_id"]),
            title=str(hit["title"]) or f"HN story {hit['object_id']}",
            url=canonical_url(str(hit["url"])),
            summary=str(hit["story_text"])[:500],
            author=str(hit["author"]) if hit.get("author") else None,
            published_at=hit["published_at"],
            metrics=SourceMetrics(points=hit.get("points"), num_comments=hit.get("num_comments")),
            tags=["hackernews"],
            language="en",
            extra={
                "object_id": hit["object_id"],
                "hn_url": f"https://news.ycombinator.com/item?id={hit['object_id']}",
                "source_weight": self.weight,
            },
        )
