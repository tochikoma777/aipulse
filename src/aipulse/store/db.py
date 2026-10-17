"""数据库连接与初始化。

- `engine_for(path)`：SQLite 引擎（单文件，check_same_thread=False 供 CLI 与 pipeline 共用）
- `init_db(path)`：`SQLModel.metadata.create_all`，供测试与 `aipulse init` 兜底
- 正式环境的表结构演进走 alembic（`src/aipulse/store/migrations`）
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, SQLModel
from sqlmodel import create_engine as sqlmodel_create_engine

from aipulse.core.errors import StoreError
from aipulse.store.models import (
    Entity,  # noqa: F401  # 导入以注册到 SQLModel.metadata
    Item,
    LLMCache,
    LLMUsage,
    PipelineRun,
    Prediction,
    Signal,
    SourceRun,
    Topic,
)

__all__ = [
    "Entity",
    "Item",
    "LLMCache",
    "LLMUsage",
    "PipelineRun",
    "Prediction",
    "Signal",
    "SourceRun",
    "Topic",
    "engine_for",
    "init_db",
    "session_for",
]


def engine_for(db_path: str | Path, *, echo: bool = False) -> Engine:
    """创建 SQLite 引擎。父目录不存在时自动创建。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return sqlmodel_create_engine(
            f"sqlite:///{path}", echo=echo, connect_args={"check_same_thread": False}
        )
    except Exception as exc:  # pragma: no cover - 仅在环境异常时触发
        raise StoreError(f"无法打开数据库 {path}: {exc}") from exc


def init_db(db_path: str | Path, *, echo: bool = False) -> Engine:
    """建表（已存在则跳过）。返回 engine。"""
    engine = engine_for(db_path, echo=echo)
    SQLModel.metadata.create_all(engine)
    return engine


def session_for(engine: Engine) -> Iterator[Session]:
    """会话上下文：提交成功即关闭，异常自动回滚。"""
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def migrate_to_head(db_path: str | Path, *, config_file: Path | None = None) -> None:
    """用 alembic 把库升级到最新版本（正式环境的建表方式）。"""
    from alembic import command
    from alembic.config import Config

    from aipulse.core.config import project_root

    ini = Path(config_file) if config_file else project_root() / "alembic.ini"
    if not ini.exists():
        raise StoreError(f"找不到 alembic.ini：{ini}")
    target = Path(db_path).resolve()
    # 全新 clone 下 `data/` 目录并不存在（它只被 .gitignore 覆盖，仓库里没有占位文件），
    # 而 alembic 会直接连接 SQLite —— 父目录缺失时报 "unable to open database file"。
    # GitHub Actions 首次运行必然命中这种情况，所以这里必须先建目录。
    target.parent.mkdir(parents=True, exist_ok=True)
    cfg = Config(str(ini))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{target}")
    command.upgrade(cfg, "head")


def ensure_schema(db_path: str | Path) -> None:
    """确保库文件与表结构就绪（CLI 之外的入口，如 pipeline 直跑时用）。

    优先走 alembic（与 `aipulse init` 一致）；alembic.ini 缺失时退化为 create_all。

    **已有库也必须升级**：Actions 会从 cache 恢复旧版 SQLite，若只判断"items 表存在"
    就返回，新加的列（如 `first_seen_at`）永远补不上。带 `alembic_version` 的库执行
    `upgrade head`（幂等）；由测试 `create_all` 建出的库没有版本表，跳过（模型已是最新）。
    """
    path = Path(db_path)
    if path.exists():
        names = table_names(path)
        if "items" in names:
            if "alembic_version" in names:
                migrate_to_head(path)
            return
    try:
        migrate_to_head(path)
    except StoreError:
        init_db(path)


def table_names(db_path: str | Path) -> set[str]:
    """列出库内表名（测试与 doctor 用）。"""
    from sqlalchemy import inspect

    engine = engine_for(db_path)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
