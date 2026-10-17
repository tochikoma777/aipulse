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
from collections.abc import Mapping
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
    # strong 档（deepseek-reasoner）会先吐思维链再出结论，同样的活儿比 fast 慢得多：
    # 共用 120s 时预言生成会被读超时打断（Actions 首跑 hybrid 就是这样 0 条的）。
    timeout_strong_s: int = 180
    # v1.16：输出预算分档。reasoner 先输出思维链，4k 在 174 条输入的 predict 场景会截断；
    # strong 给 2 倍。注意必须真的透传（沿用 timeout 的教训）。
    max_tokens_fast: int = 4000
    max_tokens_strong: int = 8000
    max_retries: int = 3
    cache_enabled: bool = True
    # v1.7：json_schema 兼容性。auto=首次带 json_schema，报 400 且错误体含
    # json_schema/response_format/unsupported 等关键词时自动降级 json_object 并记住；
    # true/false 供用户强制指定（§8.3）
    json_schema: Literal["auto", "true", "false"] = "auto"

    @field_validator("base_url", "api_key", mode="before")
    @classmethod
    def _none_to_empty(cls, value: Any) -> Any:
        """YAML 里 `${VAR}` 未设置时会被解析成 None，这里统一收敛成空串。"""
        return "" if value is None else value

    @field_validator("json_schema", mode="before")
    @classmethod
    def _coerce_json_schema(cls, value: Any) -> Any:
        """兼容旧配置的布尔写法：`true` → "true"，`false` → "false"。"""
        if isinstance(value, bool):
            return "true" if value else "false"
        return value

    def max_tokens_for(self, model_tier: str) -> int:
        """按模型档位取输出预算（strong 含思维链，给更大额度）。"""
        return self.max_tokens_strong if model_tier == "strong" else self.max_tokens_fast


class BudgetSettings(BaseModel):
    daily_limit_cny: float = 2.0
    degrade_order: list[str] = Field(
        default_factory=lambda: ["debate", "trend", "brief_topn", "all"]
    )
    # 成本估算单价（元/百万 token，混合输入输出后的保守近似），供 llm_usage.cost_cny 记账。
    # 真实定价会变动，放配置里可调；仅用于预算护栏，不做精确计费。
    price_fast_cny_per_1m: float = 1.0
    price_strong_cny_per_1m: float = 4.0


class PipelineSettings(BaseModel):
    daily_top_n: int = 30
    brief_sections: list[str] = Field(
        default_factory=lambda: ["开源项目", "论文与研究", "社区舆论", "产业与新闻"]
    )
    predictions_per_day: int = 5
    prediction_horizons: list[int] = Field(default_factory=lambda: [7, 30, 90])
    # v1.16：候选证据池收窄到 20 条，且只给 id + 标题（不给摘要），降低上下文与幻觉
    predict_candidate_top_n: int = 20
    auto_verify: bool = True
    weekly_debate_enabled: bool = True


class BriefSettings(BaseModel):
    """简报呈现参数（v1.15）。"""

    # 每个板块最多列 N 条；超出显示「另有 N 条」。24 条论文全列出来会让人无从下手。
    max_items_per_section: int = 10


class VerifySettings(BaseModel):
    """到期验证参数（设计方案 §10.2.2 / v1.9，全部可调）。"""

    grace_days: int = 7  # 证据不足时的重试窗口：due_date 后最多再等 N 天
    evidence_window_grace_days: int = 3  # 判定窗口右界宽限（窗口 = [生成日, due_date + N]）
    evidence_top_k: int = 20  # 检索证据的截断条数
    similarity_threshold: float = 0.15  # 进候选池的 TF-IDF 余弦下限
    strong_similarity: float = 0.30  # 单条即可视为强证据的阈值
    min_evidence: int = 3  # 语义路径的证据充分度下限
    partial_tolerance: float = 0.05  # 量化阈值型判据的 partial 容差带（默认 5%）
    max_context_tokens: int = 12000  # 证据注入 LLM 的 token 预算


class SignalSettings(BaseModel):
    """指标增速口径（M4）。

    两次快照间隔不足 `min_velocity_window_hours` 时**不计算**增速（标 `insufficient`）：
    调试/手动重跑常在同一小时内连跑，`Δvalue / Δhours` 会把"几分钟涨 3 star"
    放大成"日增 3000"这种离谱数字——离谱数据比没有数据更伤害可信度。
    按天正常运行时（cron 07:00）远大于该阈值，自动恢复正常。
    """

    min_velocity_window_hours: float = 6.0


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
    brief: BriefSettings = Field(default_factory=BriefSettings)
    verify: VerifySettings = Field(default_factory=VerifySettings)
    signals: SignalSettings = Field(default_factory=SignalSettings)
    output: OutputSettings = Field(default_factory=OutputSettings)
    notify: NotifySettings = Field(default_factory=NotifySettings)

    def effective_mode(self) -> RunMode:
        """实际运行档位：关闭 llm / 缺 api_key / 缺 base_url 时自动降级为 off（不报错）。

        **为什么 base_url 必须和 api_key 一样参与判断**（Actions 首跑 hybrid 时炸出来的坑）：
        `configs/default.yaml` 里 `base_url` 是 `${AIPULSE_LLM__BASE_URL}` 占位符，
        环境变量没设时会被插值成空串。若只看 api_key，那么"配了 key 但没配 base_url"的环境
        （典型就是 Actions：注入了 API key 的 secret，却漏配 base_url）会判定成 hybrid/full，
        一路走到 `OpenAICompatClient.__init__` 撞上 ConfigError——**整条 daily 崩溃**，
        直接违反红线 9（缺配置应降级，不报错退出）。
        """
        if not self.llm.enabled or not self.llm.api_key.strip() or not self.llm.base_url.strip():
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


Availability = Literal["always", "actions_only"]


def is_actions_env(env: Mapping[str, str] | None = None) -> bool:
    """是否运行在 GitHub Actions（`AIPULSE_ENV=actions`）。

    本地 WSL 与 Actions 的网络可达性不同（见设计方案 §5.10）：
    本地不可达的源标 `actions_only`，在本地跳过且不计失败，Actions 环境全开。
    """
    source = os.environ if env is None else env
    return str(source.get("AIPULSE_ENV", "")).strip().lower() == "actions"


class FeedConfig(BaseModel):
    """RSS 源条目。`tier=optional` 的源（中文补充）失效时只告警不报错。"""

    name: str
    url: str
    tier: Literal["core", "optional"] = "core"
    enabled: bool = True
    availability: Availability = "always"
    # v1.4：仅标题源（如量子位，摘要仅 22 字）→ 不参与 TF-IDF 聚类，热度靠排名位次
    title_only: bool = False
    weight: float | None = None  # 覆盖源级 weight（title_only 源降至 0.35）

    def effective_weight(self, source_weight: float) -> float:
        return source_weight if self.weight is None else self.weight


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="allow")  # 各源特有字段（queries / categories / ...）

    enabled: bool = True
    availability: Availability = "always"
    weight: float = 1.0
    rate_limit: str = "1/1s"
    # v1.15：时间语义三态。
    # event=published_at（HN/RSS）；state=last_seen_at（Trending）；
    # discovery=first_seen_at（arXiv/HF，索引滞后，关心"今天新发现了什么"）。
    time_semantics: Literal["event", "state", "discovery"] = "event"
    feeds: list[FeedConfig] = Field(default_factory=list)

    def is_available(self, env: Mapping[str, str] | None = None) -> bool:
        """当前环境下该源是否应采集。"""
        if self.availability == "always":
            return True
        return is_actions_env(env)

    def fallback_endpoints_list(self) -> list[str]:
        """备用端点列表（v1.4：默认空数组，由用户按需填写，不替用户决定镜像站）。

        注意：不能叫 `fallback_endpoints`——那会与同名的 yaml 键（extra 字段）冲突，
        `getattr` 会先命中方法本身。
        """
        value = (self.model_extra or {}).get("fallback_endpoints") or []
        return list(value)

    def source_extra(self, key: str, default: Any = None) -> Any:
        """读取各源特有配置项（extra=allow 存下来的字段）。"""
        value = getattr(self, key, None)
        return default if value is None else value


class SourcesConfig(BaseModel):
    sources: dict[str, SourceConfig] = Field(default_factory=dict)

    def get(self, name: str) -> SourceConfig | None:
        return self.sources.get(name)

    def enabled_sources(self) -> dict[str, SourceConfig]:
        return {name: cfg for name, cfg in self.sources.items() if cfg.enabled}

    def state_sources(self) -> set[str]:
        """状态型源名称（窗口过滤用 `last_seen_at`，见设计方案 §5.13）。"""
        return {name for name, cfg in self.sources.items() if cfg.time_semantics == "state"}

    def discovery_sources(self) -> set[str]:
        """发现型源名称（窗口过滤用 `first_seen_at`，v1.15）。"""
        return {name for name, cfg in self.sources.items() if cfg.time_semantics == "discovery"}


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


@lru_cache(maxsize=2)
def load_scoring(path: str | Path | None = None) -> dict[str, Any]:
    """加载热度打分配置（`configs/scoring.yaml`）。缓存：权重改文件后需清缓存或重启进程。"""
    config_path = Path(path) if path else default_config_dir() / "scoring.yaml"
    return load_yaml(config_path)


def load_entities(path: str | Path | None = None) -> dict[str, Any]:
    """加载实体词典（`configs/entities.yaml`）。不做缓存，便于运行时重载。"""
    config_path = Path(path) if path else default_config_dir() / "entities.yaml"
    return load_yaml(config_path)


def load_criteria(path: str | Path | None = None) -> dict[str, Any]:
    """加载量化判据模板库（`configs/criteria.yaml`，v1.3）。不做缓存。"""
    config_path = Path(path) if path else default_config_dir() / "criteria.yaml"
    return load_yaml(config_path)
