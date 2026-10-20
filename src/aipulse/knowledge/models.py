"""用户知识库表定义（data/user_data.db）。

**刻意使用独立 MetaData**：`USER_METADATA.create_all()` 只会创建
`knowledge_items` / `schema_version`，不可能顺带创建主库的 `items` 等表。
主库 `data/aipulse.db` 在 M6c 中只读，不新增表、不新增列、不写数据。
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from sqlalchemy import MetaData
from sqlmodel import Field, SQLModel

from aipulse.core.timeutil import utcnow

USER_METADATA: Final = MetaData()

KNOWLEDGE_STATUSES: Final = ("unread", "read", "skipped")


class KnowledgeItem(SQLModel, table=True):
    """一条用户笔记；`item_id` 跨库关联主库 `items.id`，不建物理外键。"""

    metadata = USER_METADATA
    __tablename__ = "knowledge_items"

    item_id: str = Field(primary_key=True)
    status: str = Field(default="unread", index=True)
    note: str = Field(default="")
    tags: str = Field(default="")
    topic_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class SchemaVersion(SQLModel, table=True):
    """用户库自己的 schema 版本；与主库 alembic_version 完全独立。"""

    metadata = USER_METADATA
    __tablename__ = "schema_version"

    version: int = Field(primary_key=True)
    applied_at: datetime = Field(default_factory=utcnow)
