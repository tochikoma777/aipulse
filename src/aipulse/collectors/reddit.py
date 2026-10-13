"""Reddit r/LocalLLaMA 采集器（v1.2：只走免认证 RSS，不实现 OAuth）。

RSS 模式**没有 score 字段**（已由 M0/M1 实测确认），按设计方案 §5.6 做三重补偿：
① `metrics.score = 0`（不是 None——后续打分公式按数值处理更方便），但保留 comments；
② 该源 `weight` 降为 0.55（配置里读，代码不硬编码）；
③ 用条目在列表中的排名位次 `rank_score = (N - rank) / N` 作为热度代理信号。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import feedparser
import httpx

from aipulse.core.config import SourceConfig
from aipulse.core.hashing import canonical_url
from aipulse.core.logging import get_logger
from aipulse.normalize.clean import clean_text, detect_language
from aipulse.schema.items import RawItem, SourceEnum, SourceMetrics
from aipulse.utils.http import HttpClient

from .base import BaseCollector

log = get_logger(__name__)

REDDIT_RSS = "https://www.reddit.com/r/{subreddit}/top/.rss?t=day"
# Reddit RSS 正文里常带 "N comments"，这是唯一能拿到的互动数线索
_COMMENTS_RE = re.compile(r"(\d[\d,]*)\s+comments?", re.I)


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


def parse_reddit_feed(xml_text: str) -> list[dict[str, Any]]:
    """解析 Reddit RSS（Atom 形态，fixture: reddit_top.json）。"""
    feed = feedparser.parse(xml_text or "")
    results: list[dict[str, Any]] = []
    for entry in feed.entries:
        link = str(getattr(entry, "link", "") or "")
        if not link:
            continue
        content_html = ""
        contents = getattr(entry, "content", None) or []
        if contents:
            content_html = str(contents[0].get("value", "") or "")
        body = clean_text(content_html or str(getattr(entry, "summary", "") or ""))
        comments_match = _COMMENTS_RE.search(body)
        results.append(
            {
                "id": str(getattr(entry, "id", "") or link),
                "title": clean_text(str(getattr(entry, "title", "") or "")),
                "url": link,
                "author": getattr(entry, "author", None),
                "published_at": _entry_datetime(entry),
                "body": body,
                "num_comments": int(comments_match.group(1).replace(",", ""))
                if comments_match
                else None,
            }
        )
    return results


class RedditCollector(BaseCollector):
    source = SourceEnum.REDDIT
    display_name = "Reddit r/LocalLLaMA"

    def __init__(self, cfg: SourceConfig, http: HttpClient) -> None:
        super().__init__(cfg, http)
        mode = str(self.extra("mode", "rss")).lower()
        if mode == "oauth":
            # v1.2 决策：OAuth 不实现，只留配置项与明确的报错
            raise NotImplementedError(
                "Reddit OAuth 模式暂未实现（v1.2 决策：先用免认证 RSS，M1 验收后再评估）"
            )
        self.mode = mode
        self.status = "ok"  # ok | degraded：部分 subreddit 失败只降级
        self.subreddit_status: dict[str, str] = {}

    def healthcheck_url(self) -> str:
        subs = self.extra("subreddits") or ["LocalLLaMA"]
        return REDDIT_RSS.format(subreddit=subs[0])

    async def fetch(self, since: datetime, until: datetime) -> list[RawItem]:
        subreddits = self.extra("subreddits") or ["LocalLLaMA"]
        items: list[RawItem] = []
        for subreddit in subreddits:
            url = REDDIT_RSS.format(subreddit=subreddit)
            try:
                response = await self.http.get(
                    url,
                    source=self.source.value,
                    rate_limit=self.cfg.rate_limit,
                    headers={"Accept-Encoding": "identity"},
                )
            except httpx.HTTPError as exc:
                self._mark(subreddit, f"{type(exc).__name__}: {exc}")
                continue
            except Exception as exc:  # 逐 subreddit 隔离
                self._mark(subreddit, f"{type(exc).__name__}: {exc}")
                continue
            if response.status_code >= 400:
                self._mark(subreddit, f"HTTP {response.status_code}")
                continue

            self.subreddit_status[subreddit] = "ok"
            entries = [
                e for e in parse_reddit_feed(response.text) if since <= e["published_at"] < until
            ]
            if not entries:
                log.warning("collector.reddit.empty", subreddit=subreddit)
                continue
            # 排名位次代理：越靠前越热（RSS 本身就是按 top 排序返回的）
            total = len(entries)
            for rank, entry in enumerate(entries):
                items.append(self._to_item(entry, rank=rank, total=total))
        return items

    def _mark(self, subreddit: str, detail: str) -> None:
        """记录单个 subreddit 的失败；全部失败才算源级失败。"""
        self.subreddit_status[subreddit] = "failed"
        log.warning("collector.reddit.subreddit_failed", subreddit=subreddit, detail=detail)
        if all(state == "failed" for state in self.subreddit_status.values()):
            raise self.raise_error(f"全部 subreddit 均失败（最后：{detail}）")
        self.status = "degraded"

    def _to_item(self, entry: dict[str, Any], *, rank: int, total: int) -> RawItem:
        return RawItem(
            source=self.source,
            external_id=str(entry["id"]),
            title=str(entry["title"]),
            url=canonical_url(str(entry["url"])),
            summary=str(entry["body"])[:1000],
            author=str(entry["author"]) if entry.get("author") else None,
            published_at=entry["published_at"],
            metrics=SourceMetrics(
                score=0,  # RSS 无 score：按设计置 0，热度交给 rank_score 与降权后的权重
                num_comments=entry.get("num_comments"),
                # (N-rank)/N：第 1 名接近 1.0，最后一名接近 0
                rank_score=round((total - rank) / total, 4) if total else None,
            ),
            tags=["reddit", f"r/{self.extra('subreddits', ['LocalLLaMA'])[0]}"],
            language=detect_language(str(entry["title"])),
            extra={
                "subreddit": self.extra("subreddits", ["LocalLLaMA"])[0],
                "rank": rank,
                "total_in_feed": total,
                "source_weight": self.weight,  # 0.55（配置读取，非硬编码）
            },
        )
