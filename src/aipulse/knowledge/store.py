"""`data/user_data.db` 的连接、建表与会话管理。

与主库 `store/db.py` 明确分离：

- 用户库只用 `knowledge.models.USER_METADATA`，`create_all` 不会碰主库；
- `KnowledgeStore` 只打开传入的用户库路径，不 import 主库 engine；
- 需要读主库时，只能使用 `store.db.readonly_engine_for()`（mode=ro 物理只读）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from sqlalchemy import Engine
from sqlmodel import Session, create_engine, select

from aipulse.core.errors import StoreError
from aipulse.core.timeutil import utcnow
from aipulse.knowledge.models import (
    KNOWLEDGE_STATUSES,
    USER_METADATA,
    KnowledgeItem,
    SchemaVersion,
)

USER_DB_NAME: Final = "user_data.db"
SCHEMA_VERSION: Final = 1


def user_db_path(data_dir: str | Path) -> Path:
    """用户库固定放在 `data_dir` 顶层，绝不放 `data/knowledge/` 下。"""
    return Path(data_dir) / USER_DB_NAME


def init_user_db(db_path: str | Path) -> Engine:
    """用 create_all 建用户表并写入 schema_version（刻意不走 alembic）。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine: Engine | None = None
    try:
        engine = create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False},
        )
        USER_METADATA.create_all(engine)
        with Session(engine) as session:
            if session.get(SchemaVersion, SCHEMA_VERSION) is None:
                session.add(SchemaVersion(version=SCHEMA_VERSION))
                session.commit()
        return engine
    except Exception as exc:
        if engine is not None:
            engine.dispose()
        raise StoreError(f"初始化用户库失败 {path}: {exc}") from exc


@contextmanager
def user_session_for(engine: Engine) -> Iterator[Session]:
    """用户库会话：与主库 `session_for` 分开命名，避免误用。"""
    with Session(engine, expire_on_commit=False) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def _validate_status(status: str | None) -> None:
    if status is not None and status not in KNOWLEDGE_STATUSES:
        allowed = " / ".join(KNOWLEDGE_STATUSES)
        raise ValueError(f"非法笔记状态 {status!r}；允许值：{allowed}")


class KnowledgeStore:
    """用户笔记的最小数据层；所有写操作只发生在 `user_data.db`。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._engine: Engine | None = None

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = init_user_db(self.db_path)
        return self._engine

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    @contextmanager
    def session(self) -> Iterator[Session]:
        with user_session_for(self.engine) as session:
            yield session

    def get(self, item_id: str) -> KnowledgeItem | None:
        with self.session() as session:
            return session.get(KnowledgeItem, item_id)

    def all(self) -> list[KnowledgeItem]:
        """导出用：取全部笔记行（不加 limit）。"""
        with self.session() as session:
            return list(session.exec(select(KnowledgeItem)).all())

    def list(
        self,
        *,
        status: str | None = None,
        with_notes: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[KnowledgeItem]:
        _validate_status(status)
        with self.session() as session:
            stmt = select(KnowledgeItem)
            if status is not None:
                stmt = stmt.where(KnowledgeItem.status == status)
            if with_notes:
                stmt = stmt.where(KnowledgeItem.note != "")
            stmt = (
                stmt.order_by(KnowledgeItem.updated_at.desc())  # type: ignore[attr-defined]
                .offset(offset)
                .limit(limit)
            )
            return list(session.exec(stmt).all())

    def _update_fields(
        self,
        item_id: str,
        *,
        status: str | None = None,
        note: str | None = None,
    ) -> KnowledgeItem:
        """局部更新：只改传入字段，保留另一字段与 created_at。"""
        _validate_status(status)
        now = utcnow()
        with self.session() as session:
            row = session.get(KnowledgeItem, item_id)
            if row is None:
                row = KnowledgeItem(
                    item_id=item_id,
                    status=status or "unread",
                    note=note or "",
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                if status is not None:
                    row.status = status
                if note is not None:
                    row.note = note
                row.updated_at = now
                session.add(row)
            session.flush()
            return row

    def set_status(self, item_id: str, status: str) -> KnowledgeItem:
        """只改状态；条目不存在时创建。"""
        return self._update_fields(item_id, status=status)

    def set_note(self, item_id: str, note: str) -> KnowledgeItem:
        """只改笔记；空字符串表示清空，条目不存在时创建。"""
        return self._update_fields(item_id, note=note)

    def upsert(
        self,
        item_id: str,
        *,
        status: str = "unread",
        note: str = "",
        tags: str = "",
        topic_id: str | None = None,
    ) -> KnowledgeItem:
        """整行写入：新建或覆盖用户可编辑字段，保留 created_at。"""
        _validate_status(status)
        now = utcnow()
        with self.session() as session:
            row = session.get(KnowledgeItem, item_id)
            if row is None:
                row = KnowledgeItem(
                    item_id=item_id,
                    status=status,
                    note=note,
                    tags=tags,
                    topic_id=topic_id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.status = status
                row.note = note
                row.tags = tags
                row.topic_id = topic_id
                row.updated_at = now
                session.add(row)
            session.flush()
            return row
