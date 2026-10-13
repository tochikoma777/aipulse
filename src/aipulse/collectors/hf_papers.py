"""HuggingFace Daily Papers 采集器（设计方案 §5.4 / v1.4）。

- 主端点：`https://huggingface.co/api/daily_papers?date=YYYY-MM-DD`（官方，默认）
- 备用端点：`fallback_endpoints`（**配置默认空数组**，由用户自行填写；
  v1.4 红线：不替用户决定镜像站）
- 去重关键：`paper.id` 即 arXiv 编号 → 以 `arxiv:{id}` 与 arXiv 源合并成一条
- enrich（可选）：`/api/arxiv/{id}/repos` 判断论文是否开源代码
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

HF_DAILY_PAPERS = "https://huggingface.co/api/daily_papers"
HF_ARXIV_REPOS = "https://huggingface.co/api/arxiv/{arxiv_id}/repos"


def _parse_published(value: str | None) -> datetime:
    """ISO8601（`2026-09-29T08:21:27.000Z`）→ UTC datetime；失败用当前时间。"""
    if not value:
        return datetime.now(tz=UTC)
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(tz=UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_daily_papers(payload: Any) -> list[dict[str, Any]]:
    """解析 daily_papers 响应（顶层为数组；兼容 {"items": [...]} 形态）。"""
    if isinstance(payload, dict):
        payload = payload.get("items") or payload.get("data") or []
    if not isinstance(payload, list):
        return []

    results: list[dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        paper = entry.get("paper") or {}
        paper_id = str(paper.get("id") or entry.get("id") or "").strip()
        if not paper_id:
            continue
        results.append(
            {
                "arxiv_id": paper_id,
                "title": clean_text(str(entry.get("title") or paper.get("title") or "")),
                "summary": clean_text(str(entry.get("summary") or paper.get("summary") or "")),
                "upvotes": paper.get("upvotes", entry.get("upvotes")),
                "num_comments": entry.get("numComments"),
                "published_at": _parse_published(
                    str(entry.get("publishedAt") or paper.get("publishedAt") or "")
                ),
                "github_repo": paper.get("githubRepo"),
                "github_stars": paper.get("githubStars"),
                "authors": [
                    str(a.get("name", ""))
                    for a in (paper.get("authors") or [])
                    if isinstance(a, dict)
                ],
                "thumbnail": entry.get("thumbnail"),
            }
        )
    return results


class HFPapersCollector(BaseCollector):
    source = SourceEnum.HF_PAPERS
    display_name = "HuggingFace Daily Papers"

    def healthcheck_url(self) -> str:
        return HF_DAILY_PAPERS

    def endpoints(self) -> list[str]:
        """官方端点优先，其后是用户自行配置的备用端点（默认空数组）。

        用户在 `fallback_endpoints` 里只填**基址**（如 `https://hf-mirror.com`），
        路径由这里拼接——填一行即可用，不必记忆 API 路径。
        """
        return [
            HF_DAILY_PAPERS,
            *(
                f"{base.rstrip('/')}/api/daily_papers"
                for base in self.cfg.fallback_endpoints_list()
            ),
        ]

    async def fetch(self, since: datetime, until: datetime) -> list[RawItem]:
        date_str = until.date().isoformat()
        payload: Any = None
        last_error = ""
        for endpoint in self.endpoints():
            try:
                response = await self.http.get(
                    endpoint,
                    source=self.source.value,
                    params={"date": date_str},
                    rate_limit=self.cfg.rate_limit,
                )
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning("collector.hf_papers.unreachable", endpoint=endpoint, error=last_error)
                continue
            if response.status_code >= 400:
                last_error = f"HTTP {response.status_code}"
                log.warning(
                    "collector.hf_papers.http", endpoint=endpoint, status=response.status_code
                )
                continue
            payload = response.json()
            break

        if payload is None:
            raise self.raise_error(f"全部端点不可用（最后错误：{last_error or '未知'}）")

        papers = parse_daily_papers(payload)
        if not papers:
            log.warning("collector.hf_papers.empty", date=date_str)
            return []

        items = [self._to_item(p) for p in papers]
        if bool(self.extra("enrich_repos", False)):
            await self._enrich_repos(items)
        return items

    async def _enrich_repos(self, items: list[RawItem], limit: int = 5) -> None:
        """给 Top N 论文补"是否开源代码"（models/datasets/spaces 数量）。

        只对前 N 条做，避免为了冷门论文打几十个请求（HF 限流未知，保持温和）。
        """
        for item in items[:limit]:
            arxiv_key = str(item.extra.get("arxiv_id", ""))
            if not arxiv_key:
                continue
            try:
                response = await self.http.get(
                    HF_ARXIV_REPOS.format(arxiv_id=arxiv_key),
                    source=self.source.value,
                    rate_limit=self.cfg.rate_limit,
                )
            except Exception as exc:  # enrich 是 best-effort：失败只记日志，不影响主流程
                log.debug("collector.hf_papers.enrich_fail", id=arxiv_key, error=repr(exc))
                continue
            if response.status_code >= 400:
                continue
            data = response.json() or {}
            item.extra["linked_models"] = len(data.get("models") or [])
            item.extra["linked_datasets"] = len(data.get("datasets") or [])
            item.extra["linked_spaces"] = len(data.get("spaces") or [])

    def _to_item(self, paper: dict[str, Any]) -> RawItem:
        paper_id = str(paper["arxiv_id"])
        return RawItem(
            source=self.source,
            external_id=paper_id,
            title=str(paper["title"]),
            # 与 arXiv 源同一篇论文 → 规范 URL 相同 → 合并为一条 Item
            url=canonical_url(f"https://arxiv.org/abs/{paper_id}"),
            summary=str(paper["summary"]),
            author=", ".join(paper["authors"][:3]) or None,
            published_at=paper["published_at"],
            metrics=SourceMetrics(
                upvotes=paper.get("upvotes"),
                num_comments=paper.get("num_comments"),
            ),
            tags=[],
            language="en",
            extra={
                "arxiv_id": paper_id,
                "github_repo": paper.get("github_repo"),
                "github_stars": paper.get("github_stars"),
                "authors": paper.get("authors"),
                "source_weight": self.weight,
            },
        )
