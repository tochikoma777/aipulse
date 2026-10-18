"""SQLModel 表定义（SQLite 单文件，后期可平滑迁移 Postgres）。

字段严格对应设计方案 §7。JSON 字段统一用 SQLAlchemy 的 `JSON` 类型
（SQLite 下以文本存储，SQLAlchemy 负责序列化），避免手工 json.dumps 出错。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from aipulse.core.timeutil import utcnow


class Item(SQLModel, table=True):
    """主表：归一化后的条目。"""

    __tablename__ = "items"
    __table_args__ = (
        Index("ix_items_source_published_at", "source", "published_at"),
        Index("ix_items_hot_score", "hot_score"),
    )

    id: str = Field(primary_key=True)
    source: str = Field(index=True)
    external_id: str = ""
    cross_key: str | None = Field(default=None, index=True)
    title: str = ""
    url: str = ""
    summary: str = ""
    author: str | None = None
    published_at: datetime = Field(default_factory=utcnow, index=True)
    collected_at: datetime = Field(default_factory=utcnow)
    # v1.15：首次发现。只在第一次入库时设置，之后 upsert 不更新。
    # discovery 语义（arXiv / HF，索引滞后 3-4 天）按它过滤——读者关心"今天新发现了什么"。
    first_seen_at: datetime = Field(default_factory=utcnow, index=True)
    # v1.14：状态型源（GitHub Trending）没有发布时间，窗口过滤必须用"最近一次仍被采到"。
    # 每次 upsert 无条件更新；事件型源不依赖它。
    last_seen_at: datetime = Field(default_factory=utcnow, index=True)
    language: str | None = None
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    metrics: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    seen_in: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    content_hash: str = Field(unique=True, index=True)
    simhash: str = ""
    hot_score: float = 0.0
    topic_id: str | None = Field(default=None, index=True)
    # v1.4：仅标题源（量子位，摘要 22 字）不参与 TF-IDF 聚类，避免污染相似度矩阵
    skip_cluster: bool = False
    is_duplicate: bool = False
    dedup_group_id: str | None = None
    raw_ref: str | None = None


class Signal(SQLModel, table=True):
    """指标时间序列：算 star / points 增速的唯一可靠来源。"""

    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_key", "metric", "ts", name="uq_signal_point"),
    )

    id: int | None = Field(default=None, primary_key=True)
    entity_type: str = Field(index=True)  # repo / hn_story / paper / model
    entity_key: str = Field(index=True)
    metric: str = ""  # stars / points / comments / upvotes
    value: float = 0.0
    ts: datetime = Field(default_factory=utcnow, index=True)


class Topic(SQLModel, table=True):
    """主题聚类结果。"""

    __tablename__ = "topics"

    id: str = Field(primary_key=True)
    name: str = ""
    keywords: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    representative_item_id: str | None = None
    item_count: int = 0
    date: date_type = Field(index=True)
    avg_hot_score: float = 0.0
    summary: str = ""


class Entity(SQLModel, table=True):
    """实体频次：驱动周/月趋势的"上升 / 下降 / 涌现"判定。"""

    __tablename__ = "entities"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    type: str = ""  # model / company / framework / concept / person / hardware
    item_id: str = ""
    date: date_type = Field(index=True)
    weight: float = 1.0


class Prediction(SQLModel, table=True):
    """预言表（★ 项目灵魂：可证伪 + 可回测）。"""

    __tablename__ = "predictions"

    id: str = Field(primary_key=True)
    date: date_type = Field(index=True)
    statement: str = ""
    category: str = ""  # capability/product/research/business/policy/hardware/community
    confidence: float = 0.5
    horizon_days: int = 30
    due_date: date_type = Field(index=True)
    falsifiable_criteria: str = ""
    rationale: str = ""
    evidence_item_ids: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    model: str = ""
    prompt_version: str = ""
    status: str = Field(default="pending", index=True)  # pending/verified/unverifiable
    verdict: str | None = None  # hit/partial/miss
    verdict_score: float | None = None  # hit=1.0 / partial=0.5 / miss=0.0
    verdict_note: str | None = None
    verdict_evidence_ids: list[str] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    verified_at: datetime | None = None
    verified_by: str | None = None  # auto / human
    # v1.3：预言来源与可选量化判据（到期查表即判，零 API 成本）
    origin: str = "llm"  # human / llm
    criteria: str | None = None
    criteria_params: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )


class SourceRun(SQLModel, table=True):
    """每次采集的源级运行记录（单源失败隔离的落点）。"""

    __tablename__ = "source_runs"

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    status: str = "running"  # running/ok/degraded/failed
    item_count: int = 0
    error: str | None = None


class PipelineRun(SQLModel, table=True):
    """流水线级运行记录。"""

    __tablename__ = "pipeline_runs"

    id: int | None = Field(default=None, primary_key=True)
    date: date_type = Field(index=True)
    stage: str = ""
    status: str = "running"
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    stats: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


class LLMUsage(SQLModel, table=True):
    """LLM 调用成本审计。"""

    __tablename__ = "llm_usage"

    id: int | None = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=utcnow, index=True)
    purpose: str = ""  # brief/predict/verify/debate/trend
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_cny: float = 0.0
    cache_hit: bool = False
    # v1.7：记录降级/失败原因（如 "json_schema unsupported → json_object"），便于事后审计
    error: str | None = None


class LLMCache(SQLModel, table=True):
    """prompt_hash → response 缓存。"""

    __tablename__ = "llm_cache"

    prompt_hash: str = Field(primary_key=True)
    prompt: str = ""
    response: str = ""
    model: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class ItemEnhance(SQLModel, table=True):
    """条目 LLM 增强结果的持久化落点（M6b，S1）。

    一行一条目，两个调用各写各的字段（互不覆盖）：
    - `one_liner`：要点，**一律中文**（中文概述的责任已并入这里），
      由 `prompts/brief/item_comment.j2` 产出；
    - `why` / `stance`：为什么重要 / 立场，由 `prompts/brief/item_enhance.j2` 产出。

    为什么必须持久化（红线 23）：增强结果每次重算会让成本随天数线性增长；
    同一条目命中同一 `content_hash` 时直接复用。`one_liner` 也必须落盘——
    否则 off 档永远只能显示英文摘要截断。

    `item_id` 语义上引用 `items.id`（本项目不用 DB 级外键：SQLite 下
    PRAGMA foreign_keys 默认关闭，写约束只会在迁移与删行时制造意外）。
    """

    __tablename__ = "item_enhance"
    __table_args__ = (Index("ix_item_enhance_updated_at", "updated_at"),)

    item_id: str = Field(primary_key=True)
    one_liner: str = ""
    why: str = ""
    stance: str = ""
    content_hash: str = ""  # 生成时 items.content_hash 的快照
    last_hot_score: float = 0.0  # refresh_on_hot_delta 的基线
    signals_count: int = 0  # refresh_on_new_signals 的基线
    model: str = ""
    one_liner_ver: str = ""  # item_comment.j2 的 version_hash
    enhance_ver: str = ""  # item_enhance.j2 的 version_hash
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
