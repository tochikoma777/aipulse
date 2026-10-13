"""采集器基类（设计方案 §5.0）。

铁律：
1. 采集器只负责"拿到数据 + 转成 RawItem"，**不做去重、不写库、不调 LLM**；
2. 所有 HTTP 请求必须走注入的 `HttpClient`，**禁止在采集器内直接 httpx.get**；
3. "源返回空"必须返回空列表并记 warning，**不得抛异常**；单源异常由编排层隔离。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, ClassVar

import httpx

from aipulse.core.config import SourceConfig
from aipulse.core.errors import CollectorError
from aipulse.core.logging import get_logger
from aipulse.schema.items import RawItem, SourceEnum
from aipulse.utils.http import HttpClient

log = get_logger(__name__)


class BaseCollector(ABC):
    """所有采集器的基类。子类只需实现 `fetch()`（外加可选的 `_healthcheck_url`）。"""

    source: ClassVar[SourceEnum]
    display_name: ClassVar[str] = ""

    def __init__(self, cfg: SourceConfig, http: HttpClient) -> None:
        self.cfg = cfg
        self.http = http

    # ── 子类必须实现 ──────────────────────────────────────────────────
    @abstractmethod
    async def fetch(self, since: datetime, until: datetime) -> list[RawItem]:
        """抓取 `[since, until)` 窗口内的数据，转成 RawItem 列表。

        约定：
        - 源返回空 / 无匹配 → 返回 `[]` 并 `log.warning`，不抛异常；
        - 网络或解析异常 → 转成 `CollectorError` 抛出，由编排层写 `source_runs` 后继续跑其他源。
        """

    # ── 可选覆写 ──────────────────────────────────────────────────────
    def healthcheck_url(self) -> str | None:
        """健康检查用的最小请求 URL；返回 None 表示不需要网络探活。"""
        return None

    async def healthcheck(self) -> bool:
        """轻量连通性检查（`aipulse doctor` 用）。默认发一次最小请求。"""
        url = self.healthcheck_url()
        if url is None:
            return True
        try:
            response = await self.http.get(
                url,
                source=self.source.value,
                rate_limit=self.cfg.rate_limit,
                cache=False,
                max_retries=1,
            )
        except httpx.HTTPError as exc:
            log.warning("collector.healthcheck.fail", source=self.source.value, error=repr(exc))
            return False
        return 200 <= response.status_code < 400

    # ── 公共工具 ──────────────────────────────────────────────────────
    @property
    def weight(self) -> float:
        return self.cfg.weight

    def extra(self, key: str, default: Any = None) -> Any:
        """读该源的特有配置项（如 arxiv.categories、hackernews.queries）。"""
        return self.cfg.source_extra(key, default)

    def raise_error(self, message: str, cause: BaseException | None = None) -> CollectorError:
        return CollectorError(self.source.value, message, cause=cause)
