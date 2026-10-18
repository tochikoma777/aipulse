from datetime import date

from sqlmodel import Session, select

from aipulse.core.timeutil import utcnow
from aipulse.store.db import engine_for, ensure_schema, init_db, migrate_to_head, table_names
from aipulse.store.models import Item, Prediction, Signal, SourceRun

EXPECTED_TABLES = {
    "items",
    "signals",
    "topics",
    "entities",
    "predictions",
    "source_runs",
    "pipeline_runs",
    "llm_usage",
    "llm_cache",
}


def test_init_db_creates_all_tables(tmp_path):
    db = tmp_path / "aipulse.db"
    engine = init_db(db)
    try:
        assert table_names(db) >= EXPECTED_TABLES
    finally:
        engine.dispose()


def test_alembic_upgrade_head_creates_all_tables(tmp_path):
    db = tmp_path / "migrated.db"
    migrate_to_head(db)
    assert table_names(db) >= EXPECTED_TABLES
    assert "alembic_version" in table_names(db)


def test_item_json_fields_roundtrip(tmp_path):
    engine = init_db(tmp_path / "aipulse.db")
    try:
        with Session(engine) as session:
            session.add(
                Item(
                    id="item-1",
                    source="arxiv",
                    external_id="2501.12345",
                    cross_key="arxiv:2501.12345",
                    title="Test paper",
                    url="arxiv:2501.12345",
                    content_hash="hash-1",
                    simhash="12345",
                    tags=["cs.LG", "llm"],
                    metrics={"upvotes": 12},
                    seen_in=["arxiv", "hf_papers"],
                    published_at=utcnow(),
                )
            )
            session.commit()
            loaded = session.exec(select(Item).where(Item.id == "item-1")).one()
            assert loaded.tags == ["cs.LG", "llm"]
            assert loaded.metrics["upvotes"] == 12
            assert loaded.seen_in == ["arxiv", "hf_papers"]
    finally:
        engine.dispose()


def test_signal_and_prediction_insert(tmp_path):
    engine = init_db(tmp_path / "aipulse.db")
    try:
        with Session(engine) as session:
            session.add(
                Signal(entity_type="repo", entity_key="owner/name", metric="stars", value=1234.0)
            )
            session.add(
                Prediction(
                    id="pred-1",
                    date=date(2026, 10, 13),
                    statement="某仓库 star 将在 30 天内达到 80000",
                    category="community",
                    confidence=0.7,
                    horizon_days=30,
                    due_date=date(2026, 11, 12),
                    falsifiable_criteria="signals 最新 stars >= 80000",
                    origin="human",
                    criteria="github_stars_reach",
                    criteria_params={"repo": "owner/name", "threshold": 80000},
                )
            )
            session.add(SourceRun(source="arxiv", status="ok", item_count=42))
            session.commit()

            signal = session.exec(select(Signal)).one()
            assert signal.entity_key == "owner/name" and signal.value == 1234.0

            prediction = session.exec(select(Prediction)).one()
            assert prediction.origin == "human"
            assert prediction.criteria_params == {"repo": "owner/name", "threshold": 80000}
            assert prediction.status == "pending"

            run = session.exec(select(SourceRun)).one()
            assert run.status == "ok" and run.item_count == 42
    finally:
        engine.dispose()


def test_engine_for_creates_parent_dirs(tmp_path):
    db = tmp_path / "nested" / "deep" / "a.db"
    engine = engine_for(db)
    try:
        assert db.parent.exists()
    finally:
        engine.dispose()


def test_ensure_schema_creates_missing_parent_dir(tmp_path):
    """回归：全新 clone（无 data/ 目录）下 `aipulse daily` 必须能建库。

    Actions 上实测过 `sqlite3.OperationalError: unable to open database file`——
    `ensure_schema` 走 alembic 时不建父目录。父目录缺失是**正常起点**，不是异常。
    """
    db = tmp_path / "fresh" / "data" / "aipulse.db"  # 父目录都不存在
    assert not db.parent.exists()

    ensure_schema(db)

    assert db.exists()
    assert table_names(db) >= EXPECTED_TABLES


def test_ensure_schema_upgrades_existing_alembic_db(tmp_path):
    """Actions cache 恢复的旧库必须自动 upgrade，而不是"items 表存在"就跳过。

    模拟 v1.14 的库：版本停在 c4e8b1a72f90，且没有 first_seen_at 列。
    回退版本时也要删掉更晚迁移建出的表（item_enhance），否则不是真正的旧库。
    """
    import sqlite3

    db = tmp_path / "cached.db"
    migrate_to_head(db)
    con = sqlite3.connect(db)
    con.execute("DROP INDEX ix_items_first_seen_at")
    con.execute("ALTER TABLE items DROP COLUMN first_seen_at")
    con.execute("DROP TABLE item_enhance")
    con.execute("UPDATE alembic_version SET version_num = 'c4e8b1a72f90'")
    con.commit()
    con.close()

    ensure_schema(db)

    con = sqlite3.connect(db)
    columns = {row[1] for row in con.execute("PRAGMA table_info(items)")}
    version = con.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    con.close()
    assert "first_seen_at" in columns
    assert version == "f1a2b3c4d5e6"
