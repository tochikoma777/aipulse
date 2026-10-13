"""测试公共夹具：fixtures 路径、采集器配置构造、HttpClient 便捷工厂。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aipulse.core.config import FeedConfig, SourceConfig
from aipulse.utils.http import HttpClient

FIXTURES = Path(__file__).resolve().parents[0] / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="ignore")


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def make_cfg(**kwargs: Any) -> SourceConfig:
    """构造采集器配置（extra=allow，可传各源特有字段）。"""
    return SourceConfig(**kwargs)


def make_feed(**kwargs: Any) -> FeedConfig:
    return FeedConfig(**kwargs)


def make_http(tmp_path: Path | None = None, **kwargs: Any) -> HttpClient:
    """构造一个禁用缓存的 HttpClient（单测绝不打真实网络）。"""
    kwargs.setdefault("cache_enabled", False)
    return HttpClient(**kwargs)
