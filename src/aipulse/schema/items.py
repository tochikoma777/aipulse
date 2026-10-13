"""采集层统一 schema。

所有源都必须归一到 :class:`RawItem`，下游（归一化、打分、聚类、简报）零改动。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aipulse.core.timeutil import ensure_utc, utcnow


class SourceEnum(StrEnum):
    """数据源枚举（v1.2：6 个自动源 + inbox 手动投喂，无微信/X）。"""

    GITHUB_TRENDING = "github_trending"
    ARXIV = "arxiv"
    HF_PAPERS = "hf_papers"
    HACKERNEWS = "hackernews"
    REDDIT = "reddit"
    RSS = "rss"
    INBOX = "inbox"

    @property
    def display_name(self) -> str:
        return _DISPLAY_NAMES[self.value]


_DISPLAY_NAMES = {
    "github_trending": "GitHub Trending",
    "arxiv": "arXiv",
    "hf_papers": "HuggingFace Daily Papers",
    "hackernews": "Hacker News",
    "reddit": "Reddit",
    "rss": "RSS",
    "inbox": "手动投喂",
}


class SourceMetrics(BaseModel):
    """源特有指标。

    各源只填自己有的字段，缺失即 None（不要填 0 冒充数据——reddit 无 score 就是无 score，
    降权与排名位次补偿在打分层处理，见设计方案 §5.6）。
    """

    model_config = ConfigDict(extra="allow")

    stars_total: int | None = None
    stars_in_window: int | None = None
    forks: int | None = None
    points: int | None = None
    num_comments: int | None = None
    score: int | None = None
    upvotes: int | None = None
    rank_score: float | None = None  # reddit RSS 无 score 时的热度代理：(N-rank)/N


class RawItem(BaseModel):
    """采集器输出的统一条目（不做去重、不写库、不调 LLM）。"""

    source: SourceEnum
    external_id: str
    title: str
    url: str
    summary: str = ""
    author: str | None = None
    published_at: datetime = Field(default_factory=utcnow)
    metrics: SourceMetrics = Field(default_factory=SourceMetrics)
    tags: list[str] = Field(default_factory=list)
    language: str | None = None
    # 跨源合并后记录"这条被哪些源看到过"（dedup 层填写，空表示单源）
    seen_in: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] | None = None

    def normalized_published_at(self) -> datetime:
        """发布时间统一为 UTC（源给的时间可能带偏移或是 naive）。"""
        return ensure_utc(self.published_at)
