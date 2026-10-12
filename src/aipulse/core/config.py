"""配置系统：YAML 为主 + 环境变量插值 + pydantic 校验。

约定：
1. 权重 / 阈值 / 源配置一律走 `configs/*.yaml`，代码里禁止硬编码常量。
2. YAML 里写 `${AIPULSE_LLM__API_KEY}` 形式的占位符，加载时从环境变量插值；
   未设置的变量替换为空串（调用方据此判断"未配置"，而不是报错退出）。
3. 环境变量仍可用 `AIPULSE__` 嵌套语法覆盖（pydantic-settings 原生能力）。
"""

from __future__ import annotations

import os
import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def project_root() -> Path:
    """仓库根目录（可用 `AIPULSE_ROOT` 覆盖，便于测试指向临时目录）。"""
    override = os.getenv("AIPULSE_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[3]


def default_config_dir() -> Path:
    return project_root() / "configs"


class RunMode(StrEnum):
    """v1.3 三档运行模式：API 从"必需"降级为"可选增强"。"""

    OFF = "off"  # 零 API 花费
    HYBRID = "hybrid"  # 仅预言生成 + 主编点评
    FULL = "full"  # 全部能力


class AppSettings(BaseModel):
    name: str = "aipulse"
    timezone: str = "Asia/Shanghai"
    data_dir: str = "data"
    log_level: str = "INFO"


class HttpSettings(BaseModel):
    timeout_connect_s: float = 5.0
    timeout_read_s: float = 20.0
    max_concurrency: int = 6
    cache_enabled: bool = True
    cache_ttl_s: int = 1800
    cache_dir: str = "data/cache"
    user_agent: str = "aipulse/0.1 (+https://github.com/tochikoma777/aipulse)"
    max_retries: int = 3


class LLMSettings(BaseModel):
    enabled: bool = True
    provider: str = "openai_compat"
    base_url: str = ""
    api_key: str = ""
    fast_model: str = "deepseek-chat"
    strong_model: str = "deepseek-reasoner"
    temperature: float = 0.4
    timeout_s: int = 120
    max_retries: int = 3
    cache_enabled: bool = True

    @field_validator("base_url", "api_key", mode="before")
    @classmethod
    def _none_to_empty(cls, value: Any) -> Any:
        """YAML 里 `${VAR}` 未设置时会被解析成 None，这里统一收敛成空串。"""
        return "" if value is None else value


class BudgetSettings(BaseModel):
    daily_limit_cny: float = 2.0
    degrade_order: list[str] = Field(
        default_factory=lambda: ["debate", "trend", "brief_topn", "all"]
    )


class PipelineSettings(BaseModel):
    daily_top_n: int = 30
    brief_sections: list[str] = Field(
        default_factory=lambda: ["开源项目", "论文与研究", "社区舆论", "产业与新闻"]
    )
    predictions_per_day: int = 5
    prediction_horizons: list[int] = Field(default_factory=lambda: [7, 30, 90])
    auto_verify: bool = True
    weekly_debate_enabled: bool = True


class OutputSettings(BaseModel):
    formats: list[str] = Field(default_factory=lambda: ["md", "json"])
    html_enabled: bool = True
    dir: str = "data/reports"


class NotifySettings(BaseModel):
    """v1.2：只有 file 渠道；其余渠道仅登记名字，不实现。"""

    channels: list[str] = Field(default_factory=lambda: ["file"])


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIPULSE_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mode: RunMode = RunMode.FULL
    app: AppSettings = Field(default_factory=AppSettings)
    http: HttpSettings = Field(default_factory=HttpSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    budget: BudgetSettings = Field(default_factory=BudgetSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    output: OutputSettings = Field(default_factory=OutputSettings)
    notify: NotifySettings = Field(default_factory=NotifySettings)

    def effective_mode(self) -> RunMode:
        """实际运行档位：未配置 api_key / 关闭 llm 时自动降级为 off（不报错）。"""
        if not self.llm.enabled or not self.llm.api_key.strip():
            return RunMode.OFF
        return self.mode

    def data_dir(self) -> Path:
        path = Path(self.app.data_dir)
        return path if path.is_absolute() else project_root() / path

    def db_path(self) -> Path:
        return self.data_dir() / "aipulse.db"

    def cache_path(self) -> Path:
        path = Path(self.http.cache_dir)
        return path if path.is_absolute() else project_root() / path


class FeedConfig(BaseModel):
    """RSS 源条目。`tier=optional` 的源（中文补充）失效时只告警不报错。"""

    name: str
    url: str
    tier: Literal["core", "optional"] = "core"
    enabled: bool = True


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="allow")  # 各源特有字段（queries / categories / ...）

    enabled: bool = True
    weight: float = 1.0
    rate_limit: str = "1/1s"
    feeds: list[FeedConfig] = Field(default_factory=list)


class SourcesConfig(BaseModel):
    sources: dict[str, SourceConfig] = Field(default_factory=dict)

    def get(self, name: str) -> SourceConfig | None:
        return self.sources.get(name)

    def enabled_sources(self) -> dict[str, SourceConfig]:
        return {name: cfg for name, cfg in self.sources.items() if cfg.enabled}


def interpolate_env(text: str) -> str:
    """把 `${VAR}` / `${VAR:-default}` 替换成环境变量值（未设置时用默认值或空串）。"""
    return ENV_PATTERN.sub(
        lambda m: os.getenv(m.group(1), m.group(2) if m.group(2) is not None else ""),
        text,
    )


def load_yaml(path: Path) -> dict[str, Any]:
    """读 YAML 并做环境变量插值。文件不存在时返回空 dict（由调用方决定默认值）。"""
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(interpolate_env(raw)) or {}
    if not isinstance(data, dict):
        raise ValueError(f"配置文件顶层必须是 mapping：{path}")
    return data


@lru_cache(maxsize=8)
def load_settings(path: str | Path | None = None) -> Settings:
    """加载主配置。默认读 `configs/default.yaml`。"""
    config_path = Path(path) if path else default_config_dir() / "default.yaml"
    return Settings(**load_yaml(config_path))


def load_sources(path: str | Path | None = None) -> SourcesConfig:
    """加载数据源配置。默认读 `configs/sources.yaml`（不做缓存，便于运行时重载）。"""
    config_path = Path(path) if path else default_config_dir() / "sources.yaml"
    return SourcesConfig(**load_yaml(config_path))
