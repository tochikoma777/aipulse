"""M6c S1：用户知识库数据层与主库只读守卫。"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from aipulse.core.config import AppSettings, Settings
from aipulse.core.errors import StoreError
from aipulse.core.timeutil import ensure_utc
from aipulse.knowledge.models import KnowledgeItem, SchemaVersion
from aipulse.knowledge.store import (
    SCHEMA_VERSION,
    KnowledgeStore,
    init_user_db,
    user_db_path,
)
from aipulse.store.db import init_db, readonly_engine_for
from aipulse.store.models import Item


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_main_db(path: Path) -> None:
    engine = init_db(path)
    try:
        with Session(engine) as session:
            session.add(
                Item(
                    id="it_main_1",
                    source="rss",
                    title="主库条目",
                    url="https://example.com/a",
                    content_hash="main-hash-1",
                )
            )
            session.commit()
    finally:
        engine.dispose()


def test_user_db_path_is_top_level(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    assert user_db_path(data_dir) == data_dir / "user_data.db"

    settings = Settings(app=AppSettings(data_dir=str(data_dir)))
    assert settings.user_db_path() == data_dir / "user_data.db"
    assert "knowledge" not in settings.user_db_path().parts


def test_init_user_db_creates_only_user_tables(tmp_path: Path) -> None:
    db = tmp_path / "data" / "user_data.db"
    engine = init_user_db(db)
    try:
        assert set(inspect(engine).get_table_names()) == {
            "knowledge_items",
            "schema_version",
        }
        with Session(engine) as session:
            versions = session.exec(select(SchemaVersion)).all()
            assert [row.version for row in versions] == [SCHEMA_VERSION]
    finally:
        engine.dispose()

    # 重复初始化是幂等的，不会重复写 schema_version
    engine = init_user_db(db)
    try:
        with Session(engine) as session:
            assert len(session.exec(select(SchemaVersion)).all()) == 1
    finally:
        engine.dispose()


def test_upsert_creates_and_updates_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "data" / "user_data.db"
    t1 = datetime(2026, 10, 19, 1, 0, tzinfo=UTC)
    t2 = t1 + timedelta(minutes=5)
    monkeypatch.setattr("aipulse.knowledge.store.utcnow", lambda: t1)

    store = KnowledgeStore(db)
    try:
        created = store.upsert(
            "it_1",
            note="第一条笔记",
            tags="llm,agent",
            topic_id="tp_1",
        )
        assert created.item_id == "it_1"
        assert created.status == "unread"
        assert created.note == "第一条笔记"
        assert created.tags == "llm,agent"
        assert created.topic_id == "tp_1"
        assert ensure_utc(created.created_at) == t1
        assert ensure_utc(created.updated_at) == t1

        monkeypatch.setattr("aipulse.knowledge.store.utcnow", lambda: t2)
        updated = store.upsert("it_1", status="read", note="更新后的笔记")
        assert updated.status == "read"
        assert updated.note == "更新后的笔记"
        assert updated.tags == ""
        assert updated.topic_id is None
        assert ensure_utc(updated.created_at) == t1
        assert ensure_utc(updated.updated_at) == t2

        assert store.get("it_1") is not None
        assert store.get("missing") is None
    finally:
        store.close()


def test_list_filters_by_status_and_orders_by_updated_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "data" / "user_data.db"
    t1 = datetime(2026, 10, 19, 1, 0, tzinfo=UTC)
    store = KnowledgeStore(db)
    try:
        monkeypatch.setattr("aipulse.knowledge.store.utcnow", lambda: t1)
        store.upsert("it_1", note="一")
        monkeypatch.setattr("aipulse.knowledge.store.utcnow", lambda: t1 + timedelta(minutes=1))
        store.upsert("it_2", status="read", note="二")
        monkeypatch.setattr("aipulse.knowledge.store.utcnow", lambda: t1 + timedelta(minutes=2))
        store.upsert("it_3", status="skipped", note="三")

        assert [row.item_id for row in store.list()] == ["it_3", "it_2", "it_1"]
        assert [row.item_id for row in store.list(status="read")] == ["it_2"]
        assert [row.item_id for row in store.list(status="unread")] == ["it_1"]
        assert store.list(limit=1)[0].item_id == "it_3"
        assert [row.item_id for row in store.list(limit=1, offset=1)] == ["it_2"]
    finally:
        store.close()


def test_readonly_engine_rejects_writes_and_does_not_create_missing_db(
    tmp_path: Path,
) -> None:
    main_db = tmp_path / "data" / "aipulse.db"
    _seed_main_db(main_db)

    engine = readonly_engine_for(main_db)
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT count(*) FROM items").scalar_one() == 1
            with pytest.raises(OperationalError, match="readonly"):
                conn.exec_driver_sql("DELETE FROM items")
    finally:
        engine.dispose()

    missing = tmp_path / "data" / "missing.db"
    with pytest.raises(StoreError, match="不存在"):
        readonly_engine_for(missing)
    assert not missing.exists()


def test_knowledge_operations_do_not_touch_main_db(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    main_db = data_dir / "aipulse.db"
    _seed_main_db(main_db)

    before_size = main_db.stat().st_size
    before_mtime_ns = main_db.stat().st_mtime_ns
    before_hash = _sha256(main_db)

    store = KnowledgeStore(user_db_path(data_dir))
    try:
        store.upsert("it_main_1", note="只写用户库", tags="test")
        assert store.get("it_main_1") is not None
        assert store.list() != []
    finally:
        store.close()

    assert main_db.stat().st_size == before_size
    assert main_db.stat().st_mtime_ns == before_mtime_ns
    assert _sha256(main_db) == before_hash
    assert (data_dir / "user_data.db").exists()


def test_upsert_rejects_unknown_status_without_writing(tmp_path: Path) -> None:
    db = tmp_path / "data" / "user_data.db"
    store = KnowledgeStore(db)
    try:
        with pytest.raises(ValueError):
            store.upsert("it_1", status="unknown")
        assert store.list() == []
    finally:
        store.close()


def test_knowledge_item_defaults() -> None:
    row = KnowledgeItem(item_id="it_1")
    assert row.status == "unread"
    assert row.note == ""
    assert row.tags == ""
    assert row.topic_id is None
