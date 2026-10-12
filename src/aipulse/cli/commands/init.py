"""`aipulse init`：建库 + 生成配置骨架 + 创建目录。

幂等：重复执行不会产生副作用（已存在的文件/目录跳过）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.table import Table

from aipulse.core.config import default_config_dir, load_settings, project_root
from aipulse.core.logging import get_logger
from aipulse.store.db import migrate_to_head

log = get_logger(__name__)

# 配置骨架：仅包含"必须存在"的骨架字段，密钥一律用 ${ENV} 占位（不会把真实密钥写进文件）
_DEFAULT_SKELETON = {
    "app": {
        "name": "aipulse",
        "timezone": "Asia/Shanghai",
        "data_dir": "data",
        "log_level": "INFO",
    },
    "mode": "full",
    "llm": {
        "enabled": True,
        "provider": "openai_compat",
        "base_url": "${AIPULSE_LLM__BASE_URL}",
        "api_key": "${AIPULSE_LLM__API_KEY}",
        "fast_model": "deepseek-chat",
        "strong_model": "deepseek-reasoner",
    },
    "budget": {"daily_limit_cny": 2.0},
    "notify": {"channels": ["file"]},
    "http": {"timeout_connect_s": 5, "timeout_read_s": 20, "cache_ttl_s": 1800},
}

_SOURCES_SKELETON = {
    "sources": {
        "rss": {
            "enabled": True,
            "weight": 0.6,
            "rate_limit": "1/1s",
            "feeds": [
                {
                    "name": "Simon Willison",
                    "url": "https://simonwillison.net/atom/everything/",
                    "tier": "core",
                }
            ],
        }
    }
}


def _ensure_dir(path: Path, table: Table) -> None:
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True)
    table.add_row("目录", str(path), "已存在" if existed else "已创建")


def _ensure_yaml(path: Path, data: dict[str, Any], table: Table) -> None:
    if path.exists():
        table.add_row("配置", str(path), "已存在")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    table.add_row("配置", str(path), "已生成骨架")


def init_command(
    db: str | None = typer.Option(None, "--db", help="数据库路径（默认 data/aipulse.db）"),
    config_dir: str | None = typer.Option(None, "--config-dir", help="配置目录（默认 configs/）"),
) -> None:
    """初始化项目：创建目录、生成配置骨架、建库（alembic upgrade head）。"""
    console = Console()
    root = project_root()
    settings = load_settings()

    data_dir = settings.data_dir()
    db_path = Path(db) if db else settings.db_path()

    table = Table(title="aipulse init", header_style="bold cyan")
    table.add_column("类型")
    table.add_column("路径")
    table.add_column("结果")

    for sub in ("", "cache", "reports", "inbox", "logs"):
        _ensure_dir(data_dir / sub if sub else data_dir, table)

    cfg_dir = Path(config_dir) if config_dir else default_config_dir()
    _ensure_yaml(cfg_dir / "default.yaml", _DEFAULT_SKELETON, table)
    _ensure_yaml(cfg_dir / "sources.yaml", _SOURCES_SKELETON, table)

    # .env：只从 .env.example 复制（含空占位，不含真实密钥）
    env_example = root / ".env.example"
    env_file = root / ".env"
    if env_file.exists():
        table.add_row("环境变量", str(env_file), "已存在")
    elif env_example.exists():
        env_file.write_bytes(env_example.read_bytes())
        table.add_row("环境变量", str(env_file), "已从 .env.example 复制")
    else:
        table.add_row("环境变量", str(env_file), "跳过（无 .env.example）")

    try:
        migrate_to_head(db_path)
        table.add_row("数据库", str(db_path), "已迁移至 head")
        log.info("init.db.ok", path=str(db_path))
    except Exception as exc:  # 建库失败必须明确暴露，不静默
        table.add_row("数据库", str(db_path), f"失败：{exc}")
        console.print(table)
        raise typer.Exit(code=1) from exc

    console.print(table)
    console.print(
        "\n[bold]下一步[/bold]：设置 LLM key（可选，未设置将按 off 档运行）后执行 "
        "[cyan]uv run aipulse doctor[/cyan]"
    )
