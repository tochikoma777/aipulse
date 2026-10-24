"""Web 看板（设计方案 §11.1 M4：FastAPI + Jinja2 + HTMX，只读）。

页面：
- `/`            今日简报（最新报告；无报告时降级为"最近条目"）
- `/archive`     按日期浏览（`?date=YYYY-MM-DD`）
- `/predictions` ★ 预言记分板 + 校准曲线
- `/topics`      主题演化
- `/search`      关键词检索

**红线 22**：全站只读。数据访问统一走 `web/data.py`（SQLite 以 `mode=ro` 打开），
页面里不存在任何提交表单或写接口；「趋势」「辩论」入口按 M4 要求置灰占位，
M5 完成后才点亮。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from aipulse.analysis.stats import PredictionStats
from aipulse.core.config import Settings, load_settings
from aipulse.core.logging import get_logger
from aipulse.core.timeutil import today_local
from aipulse.render.scoreboard import render_scoreboard_markdown
from aipulse.web.charts import build_calibration_chart
from aipulse.web.data import ReadOnlyStore, ReportIndex

log = get_logger(__name__)

_HERE = Path(__file__).resolve().parent
_TEMPLATES_DIR = _HERE / "templates"
_STATIC_DIR = _HERE / "static"

# 「趋势」「辩论」是 M5 能力，M4 只登记入口（置灰）——不要在 M4 实现它们
M5_ENTRIES = (
    {"label": "趋势", "note": "周期长文（M5）"},
    {"label": "辩论", "note": "多角色辩论（M5）"},
)


def _stats_view(stats: PredictionStats) -> dict[str, Any]:
    """模板友好的统计视图（避免模板里做算术）。"""
    return {
        "total": stats.total,
        "verified": stats.verified,
        "pending": stats.pending,
        "unverifiable": stats.unverifiable,
        "hits": stats.hits,
        "partials": stats.partials,
        "misses": stats.misses,
        "hit_rate": _pct(stats.hit_rate),
        "weighted_score": _num(stats.weighted_score),
        "brier": _num(stats.brier),
        "brier_label": _brier_label(stats.brier),
        "has_results": stats.has_results,
        "groups": [
            {
                "name": name,
                "rows": [
                    {
                        "label": row.label,
                        "n": row.n,
                        "hit_rate": _pct(row.hit_rate),
                        "weighted_score": _num(row.weighted_score),
                    }
                    for row in rows
                ],
            }
            for name, rows in stats.groups.items()
            if rows
        ],
    }


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _num(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _brier_label(brier: float | None) -> str:
    if brier is None:
        return "尚无样本"
    if brier < 0.20:
        return "优秀（<0.20）"
    if brier < 0.25:
        return "优于随机基线（0.25）"
    return "接近或差于随机基线"


def _empty_state(runtime_days: int, first_due: date | None) -> str:
    """0 样本空态文案（M4 DoD：显示"系统已运行 N 天，首批预言将于 X 日到期"，不得空白或报错）。"""
    if runtime_days <= 0:
        return "系统尚未开始积累数据，手写一条预言即可开始。"
    if first_due is not None:
        return f"系统已运行 {runtime_days} 天，首批预言将于 {first_due.isoformat()} 到期。"
    return f"系统已运行 {runtime_days} 天，暂无待验证的到期预言。"


def create_app(
    *,
    settings: Settings | None = None,
    db_path: str | Path | None = None,
    reports_dir: str | Path | None = None,
) -> FastAPI:
    """构造只读看板应用。测试可注入临时 db / 报告目录。"""
    cfg = settings or load_settings()
    store = ReadOnlyStore(db_path or cfg.db_path(), tz_name=cfg.app.timezone)
    reports = ReportIndex(reports_dir or (cfg.data_dir() / "reports"))
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    app = FastAPI(title="AI 脉搏 · 看板", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    def _base(request: Request, active: str, **extra: Any) -> dict[str, Any]:
        return {
            "request": request,
            "tz": cfg.app.timezone,
            "active": active,
            "m5_entries": M5_ENTRIES,
            **extra,
        }

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        day = reports.latest()
        daily = reports.load_daily(day) if day else None
        meta = reports.load_meta(day) if day else {}
        items = store.recent_items(limit=60) if daily is None else None
        return templates.TemplateResponse(
            request,
            "index.html",
            _base(
                request,
                "index",
                day=day,
                daily=daily,
                meta=meta,
                fallback_items=items,
                days=reports.days()[:14],
            ),
        )

    @app.get("/archive", response_class=HTMLResponse)
    def archive(
        request: Request, date_param: str | None = Query(None, alias="date")
    ) -> HTMLResponse:
        days = reports.days()
        selected = date_param or (days[0] if days else None)
        daily = reports.load_daily(selected) if selected else None
        meta = reports.load_meta(selected) if selected else {}
        return templates.TemplateResponse(
            request,
            "archive.html",
            _base(request, "archive", days=days, selected=selected, daily=daily, meta=meta),
        )

    @app.get("/predictions", response_class=HTMLResponse)
    def predictions(request: Request) -> HTMLResponse:
        stats = store.prediction_stats()
        runtime_days = store.runtime_days()
        first_due = store.first_due_date()
        rows = store.predictions()
        return templates.TemplateResponse(
            request,
            "predictions.html",
            _base(
                request,
                "predictions",
                stats=_stats_view(stats),
                chart=build_calibration_chart(stats.calibration),
                buckets=[
                    {
                        "label": b.label,
                        "n": b.n,
                        "mean_confidence": _num(b.mean_confidence),
                        "hit_rate": _pct(b.hit_rate),
                    }
                    for b in stats.calibration
                ],
                predictions=rows[:80],
                runtime_days=runtime_days,
                first_due=first_due.isoformat() if first_due else None,
                empty_state=_empty_state(runtime_days, first_due),
                scoreboard_md=render_scoreboard_markdown(stats) if stats.has_results else "",
            ),
        )

    @app.get("/topics", response_class=HTMLResponse)
    def topics(request: Request) -> HTMLResponse:
        # ★ 必须用 today_local()：报告日期按本地时区（默认 Asia/Shanghai）生成，
        #   用 date.today()（容器/系统时区）会在 UTC 16:00-24:00 之间错开一天，
        #   页面就会查不到当天的 topic 与 entity，表现为"主题还在、实体全空"。
        day = reports.latest() or today_local().isoformat()
        return templates.TemplateResponse(
            request,
            "topics.html",
            _base(
                request,
                "index",
                day=day,
                topics=store.topics_for_day(date.fromisoformat(day)),
                history=store.topic_history(),
                entities=store.entities_for_day(date.fromisoformat(day)),
                days=reports.days()[:14],
            ),
        )

    @app.get("/search", response_class=HTMLResponse)
    def search(request: Request, q: str = Query("")) -> HTMLResponse:
        results = store.search_items(q)
        return templates.TemplateResponse(
            request,
            "search.html",
            _base(request, "search", q=q, results=results, searched=bool(q.strip())),
        )

    @app.get("/search/partial", response_class=HTMLResponse)
    def search_partial(request: Request, q: str = Query("")) -> HTMLResponse:
        """HTMX 局部刷新片段（无 JS 时表单退回整页 `GET /search`）。"""
        results = store.search_items(q)
        return templates.TemplateResponse(
            request,
            "_results.html",
            {"request": request, "q": q, "results": results, "searched": bool(q.strip())},
        )

    return app


__all__ = ["M5_ENTRIES", "create_app"]
