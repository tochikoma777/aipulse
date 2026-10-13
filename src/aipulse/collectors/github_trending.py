"""GitHub Trending 采集器（设计方案 §5.2）。

解析策略：只用**稳定结构特征**，不依赖易变 class 名——
- `<article>` 容器
- `h2 > a[href="/owner/repo"]` 取仓库名
- `itemprop="programmingLanguage"` 取语言
- `/stargazers` 与 `/forks` 链接旁的计数
- 文本 `N stars today` 取窗口内增速

结果 <5 条时自动降级 GitHub Search API（双通道，避免 HTML 改版导致采空）。
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Any

import httpx

from aipulse.core.config import SourceConfig
from aipulse.core.logging import get_logger
from aipulse.normalize.clean import clean_text
from aipulse.schema.items import RawItem, SourceEnum, SourceMetrics
from aipulse.utils.http import HttpClient

from .base import BaseCollector

log = get_logger(__name__)

TRENDING_URL = "https://github.com/trending?since=daily"
SEARCH_URL = "https://api.github.com/search/repositories"

_ARTICLE_RE = re.compile(r"<article\b.*?</article>", re.S)
_REPO_RE = re.compile(r'<h2[^>]*>\s*<a[^>]*href="/([\w.\-]+/[\w.\-]+)"', re.S)
# 注意：必须写成 <p(\s...)?>，否则 <path d="...">（svg）也会被当成 <p> 匹配到
_DESC_RE = re.compile(r"<p(?:\s[^>]*)?>(.*?)</p>", re.S)
_LANG_RE = re.compile(r'itemprop="programmingLanguage"[^>]*>([^<]+)<')
_STARS_RE = re.compile(r'/stargazers"[^>]*>(.*?)</a>', re.S)
_FORKS_RE = re.compile(r'/forks"[^>]*>(.*?)</a>', re.S)
_TODAY_RE = re.compile(r"([\d,]+)\s*stars?\s*today", re.I)
_NUMBER_RE = re.compile(r"([\d,]+)")


def _to_int(text: str | None) -> int | None:
    """从 "191,725" 这类文本里取整数，取不到返回 None（不冒充 0）。"""
    if not text:
        return None
    match = _NUMBER_RE.search(text.replace("\xa0", " "))
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _text_after_svg(raw: str) -> str:
    """计数文本里通常夹着 svg，剥掉标签后剩下的就是数字。"""
    return re.sub(r"<[^>]+>", " ", raw)


def parse_trending_html(html_text: str) -> list[dict[str, Any]]:
    """解析 Trending 页面 → 仓库字典列表（纯函数，便于 fixtures 驱动单测）。"""
    results: list[dict[str, Any]] = []
    for block in _ARTICLE_RE.findall(html_text or ""):
        repo_match = _REPO_RE.search(block)
        if not repo_match:
            continue  # 结构变了：跳过该块，最终由"条数<5"触发 Search API 降级
        full_name = repo_match.group(1)
        desc_match = _DESC_RE.search(block)
        description = clean_text(desc_match.group(1)) if desc_match else ""
        lang_match = _LANG_RE.search(block)
        stars_match = _STARS_RE.search(block)
        forks_match = _FORKS_RE.search(block)
        today_match = _TODAY_RE.search(block)
        results.append(
            {
                "full_name": full_name,
                "description": description,
                "language": lang_match.group(1).strip() if lang_match else None,
                "stars_total": _to_int(_text_after_svg(stars_match.group(1)))
                if stars_match
                else None,
                "forks": _to_int(_text_after_svg(forks_match.group(1))) if forks_match else None,
                "stars_in_window": _to_int(today_match.group(1)) if today_match else None,
            }
        )
    return results


def parse_search_json(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """解析 Search API 响应（fixture: github_search.json）。"""
    items = payload.get("items") or []
    results: list[dict[str, Any]] = []
    for repo in items:
        full_name = repo.get("full_name")
        if not full_name:
            continue
        results.append(
            {
                "full_name": full_name,
                "description": clean_text(repo.get("description") or ""),
                "language": repo.get("language"),
                "stars_total": repo.get("stargazers_count"),
                "forks": repo.get("forks_count"),
                "stars_in_window": None,  # Search API 只给总 star，增速靠 signals 快照算
                "created_at": repo.get("created_at"),
                "url": repo.get("html_url") or f"https://github.com/{full_name}",
            }
        )
    return results


class GitHubTrendingCollector(BaseCollector):
    source = SourceEnum.GITHUB_TRENDING
    display_name = "GitHub Trending"

    def __init__(self, cfg: SourceConfig, http: HttpClient) -> None:
        super().__init__(cfg, http)
        self.degraded_to_search_api = False

    def healthcheck_url(self) -> str:
        return TRENDING_URL

    async def fetch(self, since: datetime, until: datetime) -> list[RawItem]:
        items = await self._fetch_trending()
        min_items = int(self.extra("min_items_before_fallback", 5))
        if len(items) < min_items and bool(self.extra("fallback_search_api", True)):
            log.warning(
                "collector.github_trending.degrade",
                got=len(items),
                msg="Trending 结果过少，降级到 GitHub Search API",
            )
            self.degraded_to_search_api = True
            items = await self._fetch_search_api(since) or items
        return items

    async def _fetch_trending(self) -> list[RawItem]:
        try:
            response = await self.http.get(
                TRENDING_URL,
                source=self.source.value,
                rate_limit=self.cfg.rate_limit,
                # 该环境偶发返回损坏的 gzip（坑 28）：明确要求不压缩
                headers={"Accept-Encoding": "identity"},
            )
        except httpx.HTTPError as exc:
            raise self.raise_error(f"Trending 页面请求失败：{exc}", cause=exc) from exc
        if response.status_code >= 400:
            raise self.raise_error(f"Trending 页面返回 HTTP {response.status_code}")
        repos = parse_trending_html(response.text)
        return [self._to_item(repo) for repo in repos]

    async def _fetch_search_api(self, since: datetime) -> list[RawItem]:
        created_after = (since - timedelta(days=7)).date().isoformat()
        per_page = int(self.extra("search_per_page", 50))
        headers = {"Accept": "application/vnd.github+json", "Accept-Encoding": "identity"}
        token = os.getenv("GITHUB_TOKEN", "").strip()
        if token:  # 有 token 30 req/min，无 token 10 req/min
            headers["Authorization"] = f"Bearer {token}"
        params = {
            "q": f"created:>{created_after}&sort=stars&order=desc",
            "per_page": str(per_page),
        }
        try:
            response = await self.http.get(
                SEARCH_URL,
                source=self.source.value,
                params=params,
                headers=headers,
                rate_limit="1/2s",
            )
        except httpx.HTTPError as exc:
            log.warning("collector.github_trending.search_failed", error=repr(exc))
            return []
        if response.status_code >= 400:
            log.warning("collector.github_trending.search_http", status=response.status_code)
            return []
        return [self._to_item(repo) for repo in parse_search_json(response.json())]

    def _to_item(self, repo: dict[str, Any]) -> RawItem:
        full_name = str(repo["full_name"])
        language = repo.get("language")
        return RawItem(
            source=self.source,
            external_id=full_name,
            title=full_name,
            url=f"https://github.com/{full_name}",
            summary=str(repo.get("description") or ""),
            metrics=SourceMetrics(
                stars_total=repo.get("stars_total"),
                stars_in_window=repo.get("stars_in_window"),
                forks=repo.get("forks"),
            ),
            language=str(language) if language else None,
            tags=[str(language)] if language else [],
            extra={"language": language, "source_weight": self.weight},
        )
