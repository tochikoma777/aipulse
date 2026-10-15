"""`aipulse serve`：启动只读 Web 看板（M4，设计方案 §11.1）。

    aipulse serve --port 8000

**只读**：页面数据全部来自 SQLite（以 `mode=ro` 打开）与 `data/reports/` 下的报告文件，
不存在任何写接口（红线 22）。因此可以边跑 `daily` 边看，二者互不干扰。
"""

from __future__ import annotations

from pathlib import Path

import typer
import uvicorn
from rich.console import Console

from aipulse.core.config import load_settings
from aipulse.web import create_app

app = typer.Typer(name="serve", help="Web 看板（只读）", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def run(
    port: int = typer.Option(8000, "--port", help="监听端口"),
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址（默认仅本机）"),
    db: str = typer.Option(None, "--db", help="数据库路径（默认 data/aipulse.db）"),
    reports_dir: str = typer.Option(None, "--reports-dir", help="报告目录（默认 data/reports）"),
) -> None:
    """启动本地看板：今日简报 / 归档 / 预言记分板 / 主题 / 检索。"""
    settings = load_settings()
    console = Console()
    application = create_app(
        settings=settings,
        db_path=Path(db) if db else None,
        reports_dir=Path(reports_dir) if reports_dir else None,
    )
    console.print(
        f"[bold]AI 脉搏看板[/bold] → http://{host}:{port}\n"
        f"数据库：{db or settings.db_path()}\n"
        f"报告目录：{reports_dir or (settings.data_dir() / 'reports')}"
    )
    uvicorn.run(application, host=host, port=port, log_level=settings.app.log_level.lower())


__all__ = ["app"]
