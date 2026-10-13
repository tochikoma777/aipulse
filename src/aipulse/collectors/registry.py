"""采集器注册表（设计方案 §5.0 / §5.10）。

职责：按名注册、按 `enabled` 与 `availability` 过滤、实例化。
**注册表必须感知 `availability`**：本地运行时 `actions_only` 的源直接跳过（由编排层写
`source_runs.status='skipped_offline'`），不计入失败、不影响退出码。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aipulse.core.config import is_actions_env
from aipulse.schema.items import SourceEnum
from aipulse.utils.http import HttpClient

from .arxiv import ArxivCollector
from .base import BaseCollector
from .github_trending import GitHubTrendingCollector
from .hackernews import HackerNewsCollector
from .hf_papers import HFPapersCollector
from .inbox import InboxCollector
from .reddit import RedditCollector
from .rss import RSSCollector

_REGISTRY: dict[str, type[BaseCollector]] = {}


def register(collector_cls: type[BaseCollector]) -> type[BaseCollector]:
    """注册一个采集器类（也可作装饰器用）。"""
    _REGISTRY[collector_cls.source.value] = collector_cls
    return collector_cls


def unregister(name: str) -> None:
    _REGISTRY.pop(name, None)


def get(name: str) -> type[BaseCollector] | None:
    return _REGISTRY.get(name)


def list_collectors() -> dict[str, type[BaseCollector]]:
    return dict(_REGISTRY)


# 6 个自动源 + inbox（v1.1 红线：不得新增微信 / X 相关采集器）
for _cls in (
    GitHubTrendingCollector,
    ArxivCollector,
    HFPapersCollector,
    HackerNewsCollector,
    RedditCollector,
    RSSCollector,
    InboxCollector,
):
    register(_cls)


def build(name: str, cfg: Any, http: HttpClient) -> BaseCollector:
    """按名实例化采集器。未知源抛 KeyError（配置写错要立刻暴露）。"""
    cls = _REGISTRY[name]
    return cls(cfg, http)


def select(
    sources_cfg: Mapping[str, Any],
    http: HttpClient,
    *,
    wanted: list[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[list[BaseCollector], list[tuple[str, str]]]:
    """选出本次要跑的采集器。

    返回 `(collectors, skipped)`，`skipped` 为 `[(源名, 跳过原因)]`
    ——编排层据此写 `source_runs.status='skipped_offline'`，但**不计失败**。
    """
    collectors: list[BaseCollector] = []
    skipped: list[tuple[str, str]] = []

    for name, cfg in sources_cfg.items():
        if wanted is not None and name not in wanted:
            continue
        if not cfg.enabled:
            skipped.append((name, "disabled"))
            continue
        if not cfg.is_available(env):
            # v1.4：本地跳过 actions_only 源，这是"环境不支持"，不是失败
            reason = "本环境不可达（actions_only），将在 GitHub Actions 中启用"
            skipped.append((name, reason))
            continue
        if name not in _REGISTRY:
            skipped.append((name, "no collector registered"))
            continue
        collectors.append(build(name, cfg, http))

    return collectors, skipped


def is_actions() -> bool:
    """便捷封装：当前是否在 Actions 环境（AIPULSE_ENV=actions）。"""
    return is_actions_env()


__all__ = [
    "BaseCollector",
    "SourceEnum",
    "build",
    "get",
    "is_actions",
    "list_collectors",
    "register",
    "select",
    "unregister",
]
