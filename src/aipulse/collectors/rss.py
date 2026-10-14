"""通用 RSS / Atom 采集器（设计方案 §5.7 / v1.4）。

要点：
1. feed 列表全部来自 `configs/sources.yaml`（新增 RSS 源**零代码**，改配置即可）；
2. `tier: optional` 的源失败/空/解析异常 → 只 warning + `status='degraded'`，不影响流水线退出码；
   `tier: core` 失败才计入失败统计；
3. `title_only: true` 的源（如量子位，摘要仅 22 字）标记 `extra.title_only`，
   **不参与 TF-IDF 聚类**（M2 聚类器据此跳过），并用 feed 级 weight（0.35）覆盖源权重。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import feedparser
import httpx

from aipulse.core.config import FeedConfig, SourceConfig
from aipulse.core.hashing import canonical_url
from aipulse.core.logging import get_logger
from aipulse.normalize.clean import clean_text, detect_language
from aipulse.schema.items import RawItem, SourceEnum, SourceMetrics
from aipulse.utils.http import HttpClient

from .base import BaseCollector

log = get_logger(__name__)


def _entry_datetime(entry: Any) -> datetime:
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


def parse_feed(xml_text: str) -> list[dict[str, Any]]:
    """通用 RSS/Atom 解析（fixtures: rss_feed.xml / rss_feed_zh.xml）。"""
    feed = feedparser.parse(xml_text or "")
    results: list[dict[str, Any]] = []
    for entry in feed.entries:
        link = str(getattr(entry, "link", "") or getattr(entry, "id", "") or "")
        if not link:
            continue
        contents = getattr(entry, "content", None) or []
        content_html = str(contents[0].get("value", "") or "") if contents else ""
        summary = clean_text(content_html or str(getattr(entry, "summary", "") or ""))
        results.append(
            {
                "id": str(getattr(entry, "id", "") or link),
                "title": clean_text(str(getattr(entry, "title", "") or "")),
                "url": link,
                "author": getattr(entry, "author", None),
                "published_at": _entry_datetime(entry),
                "summary": summary,
                "tags": [str(t.get("term", "")) for t in (getattr(entry, "tags", None) or [])],
            }
        )
    return results


class RSSCollector(BaseCollector):
    source = SourceEnum.RSS
    display_name = "RSS / 博客"

    def __init__(self, cfg: SourceConfig, http: HttpClient) -> None:
        super().__init__(cfg, http)
        self.status = "ok"  # ok | degraded：由编排层写入 source_runs
        self.feed_status: dict[str, str] = {}

    @property
    def feeds(self) -> list[FeedConfig]:
        feeds = getattr(self.cfg, "feeds", None) or []
        return [f for f in feeds if f.enabled]

    def healthcheck_url(self) -> str | None:
        core_feeds = [f for f in self.feeds if f.tier == "core"]
        return core_feeds[0].url if core_feeds else None

    async def fetch(self, since: datetime, until: datetime) -> list[RawItem]:
        # v1.6：串行 8 feed 实测耗时 298s，改为每 feed 一个任务并发拉取。
        # 内部 semaphore 用 http.max_concurrency（与全局并发 6 一致），
        # 避免 8 个 feed 同时打满网络；请求仍走 HttpClient 的每源令牌桶限速。
        semaphore = asyncio.Semaphore(max(1, self.http.max_concurrency))
        tasks = [self._fetch_feed(feed, since, until, semaphore) for feed in self.feeds]
        results = await asyncio.gather(*tasks)
        items: list[RawItem] = []
        for batch in results:
            items.extend(batch)
        return items

    async def _fetch_feed(
        self, feed: FeedConfig, since: datetime, until: datetime, semaphore: asyncio.Semaphore
    ) -> list[RawItem]:
        """拉取单个 feed 并转成 RawItem；任何异常都内部隔离，绝不向上抛。"""
        async with semaphore:
            try:
                response = await self.http.get(
                    feed.url,
                    source=self.source.value,
                    rate_limit=self.cfg.rate_limit,
                    headers={"Accept-Encoding": "identity"},
                )
            except httpx.HTTPError as exc:
                self._mark(feed, "failed", f"{type(exc).__name__}: {exc}")
                return []
            except Exception as exc:  # 逐 feed 隔离：一个 feed 的意外异常不拖垮整个 RSS 源
                self._mark(feed, "failed", f"{type(exc).__name__}: {exc}")
                return []
            if response.status_code >= 400:
                self._mark(feed, "failed", f"HTTP {response.status_code}")
                return []

            try:
                entries = parse_feed(response.text)
            except Exception as exc:  # 脏 XML：解析异常也不能让流水线挂掉
                self._mark(feed, "failed", f"解析失败：{type(exc).__name__}: {exc}")
                return []

            in_window = [e for e in entries if since <= e["published_at"] < until]
            if not entries:
                self._mark(feed, "empty", "feed 返回 0 条")
                return []
            if not in_window:
                self._mark(feed, "empty", "窗口内无新条目")
                return []

            self._mark(feed, "ok", f"{len(in_window)} 条")
            total = len(in_window)
            return [
                self._to_item(entry, feed, rank=rank, total=total)
                for rank, entry in enumerate(in_window)
            ]

    def _mark(self, feed: FeedConfig, state: str, detail: str) -> None:
        self.feed_status[feed.name] = state
        if state == "ok":
            log.info("collector.rss.feed_ok", feed=feed.name, detail=detail)
            return
        # optional（中文补充）源：只告警；core（英文主干）源：计入失败
        if feed.tier == "optional":
            self.status = "degraded"
            log.warning(
                "collector.rss.feed_degraded",
                feed=feed.name,
                tier=feed.tier,
                detail=detail,
                msg="optional 源异常只降级，不影响流水线退出码",
            )
        else:
            self.status = "degraded"
            log.error("collector.rss.feed_failed", feed=feed.name, tier=feed.tier, detail=detail)

    def _to_item(
        self, entry: dict[str, Any], feed: FeedConfig, *, rank: int, total: int
    ) -> RawItem:
        title = str(entry["title"])
        summary = str(entry["summary"])
        return RawItem(
            source=self.source,
            external_id=str(entry["id"]),
            title=title,
            url=canonical_url(str(entry["url"])),
            summary=summary,
            author=str(entry["author"]) if entry.get("author") else None,
            published_at=entry["published_at"],
            metrics=SourceMetrics(
                # RSS 无点赞数：用排名位次作热度代理（与 Reddit 同一套补偿逻辑）
                rank_score=round((total - rank) / total, 4) if total else None
            ),
            tags=list(entry["tags"]),
            language=detect_language(f"{title} {summary}"),
            extra={
                "feed": feed.name,
                "feed_url": feed.url,
                "tier": feed.tier,
                "title_only": feed.title_only,  # M2 聚类器据此跳过
                "rank": rank,
                "total_in_feed": total,
                "source_weight": feed.effective_weight(self.weight),
            },
        )
