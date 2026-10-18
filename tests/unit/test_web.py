"""Web 看板单测（M4）：只读保证、五个页面、0 样本空态。

红线 22（Web 严禁写操作）在这里是**可执行断言**：直接对看板用的 engine 发 DELETE，
必须被 SQLite 拒绝——不是靠"我们没写代码"来保证。
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from aipulse.core.timeutil import today_local
from aipulse.store.db import init_db
from aipulse.store.models import Entity, Item, Prediction, Topic
from aipulse.web import create_app
from aipulse.web.charts import build_calibration_chart
from aipulse.web.data import ReadOnlyStore, ReportIndex


def _seed_db(
    db_path,
    *,
    predictions: list[Prediction] | None = None,
    items: list[Item] | None = None,
    topics: list[Topic] | None = None,
    entities: list[Entity] | None = None,
) -> None:
    engine = init_db(db_path)
    with Session(engine, expire_on_commit=False) as session:
        for row in predictions or []:
            session.add(row)
        for row in items or []:
            session.add(row)
        for row in topics or []:
            session.add(row)
        for row in entities or []:
            session.add(row)
        session.commit()
    engine.dispose()


def _item(item_id: str, title: str, *, days_ago: int = 0, source: str = "github_trending") -> Item:
    moment = datetime.now(tz=UTC) - timedelta(days=days_ago)
    return Item(
        id=item_id,
        source=source,
        external_id=f"org/{item_id}",
        title=title,
        url=f"https://example.com/{item_id}",
        summary=f"{title} 的摘要",
        collected_at=moment,
        published_at=moment,
        metrics={"stars_total": 100},
        seen_in=[source],
        content_hash=f"h-{item_id}",
        hot_score=88.0,
    )


def _prediction(pred_id: str, *, status: str = "pending", **kwargs) -> Prediction:
    today = today_local()
    base = {
        "id": pred_id,
        "date": today - timedelta(days=10),
        "statement": f"关于 {pred_id} 的可证伪断言",
        "category": "capability",
        "confidence": 0.7,
        "horizon_days": 30,
        "due_date": today + timedelta(days=20),
        "falsifiable_criteria": "窗口内出现 X 即命中",
        "status": status,
    }
    return Prediction(**{**base, **kwargs})


def _write_report(reports_dir, day: str, *, headline: str) -> None:
    target = reports_dir.joinpath(*day.split("-"))
    target.mkdir(parents=True, exist_ok=True)
    (target / "daily.json").write_text(
        json.dumps(
            {
                "date": day,
                "headline": headline,
                "executive_summary": "总览内容",
                "editor_note": "主编观点",
                "sections": [{"name": "开源项目", "summary": "", "item_ids": ["a"]}],
                "comments": [
                    {
                        "item_id": "a",
                        "one_liner": "一句话",
                        "why": "因为重要",
                        "stance": "",
                    }
                ],
                "contradictions": [],
                "underrated": [],
                "stats": {},
                "items": {
                    "a": {
                        "id": "a",
                        "source": "github_trending",
                        "title": "vLLM 发布 v1",
                        "url": "https://example.com/a",
                        "summary": "推理加速",
                        "hot_score": 91.2,
                        "topic_id": None,
                        "seen_in": ["github_trending", "hackernews"],
                        "published_at": "2026-10-14T00:00:00+00:00",
                        "language": "en",
                    }
                },
                "meta": {"mode": "off"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (target / "meta.json").write_text(
        json.dumps(
            {
                "mode": "off",
                "day": day,
                "analysis": {"items": 1, "topics": 1, "new_entity_mention_rows": 2},
                "verify": {"verified": 1, "unverifiable": 0, "deferred": 0, "llm_calls": 0},
                "predictions": {"total": 1, "verified": 1},
                "signals": {"entities": 3, "points": 4, "with_velocity": 2},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _client(tmp_path, *, db=None, reports=None) -> TestClient:
    app = create_app(
        db_path=db or (tmp_path / "aipulse.db"),
        reports_dir=reports or (tmp_path / "reports"),
    )
    return TestClient(app)


# ── 只读保证（红线 22）─────────────────────────────────────────────


def test_readonly_engine_rejects_writes(tmp_path):
    db = tmp_path / "ro.db"
    _seed_db(db, items=[_item("a", "标题 A")])

    store = ReadOnlyStore(db)
    engine = store._get_engine()
    assert engine is not None
    assert store.items_for_day(today_local())  # 读得到

    with engine.connect() as conn, pytest.raises(OperationalError, match="readonly"):
        conn.exec_driver_sql("DELETE FROM items")
    store.close()


def test_store_does_not_create_missing_db(tmp_path):
    missing = tmp_path / "nope.db"
    store = ReadOnlyStore(missing)

    assert store.available is False
    assert store.items_for_day(today_local()) == []
    assert store.predictions() == []
    assert store.prediction_stats().total == 0
    assert store.runtime_days() == 0
    assert store.first_due_date() is None
    assert not missing.exists(), "看板不得凭查询创建数据库文件"


# ── 页面 ────────────────────────────────────────────────────────────


def test_htmx_is_served_locally_not_from_cdn(tmp_path):
    """M4：本项目宣称"零外部依赖也能跑完整流程"，首屏不该吊在第三方 CDN 上。"""
    client = _client(tmp_path)

    asset = client.get("/static/htmx.min.js")
    assert asset.status_code == 200
    assert "htmx" in asset.text.lower()

    html = client.get("/").text
    assert 'src="/static/htmx.min.js"' in html
    assert "unpkg" not in html and "cdn." not in html


def test_all_pages_render_without_any_data(tmp_path):
    client = _client(tmp_path)

    for path in ("/", "/archive", "/predictions", "/topics", "/search", "/search?q=vllm"):
        response = client.get(path)
        assert response.status_code == 200, path

    home = client.get("/").text
    assert "还没有任何报告" in home
    assert "nav-disabled" in home  # 趋势 / 辩论 置灰占位
    assert "趋势" in home and "辩论" in home
    assert "只读" in client.get("/predictions").text


def test_predictions_empty_state_reports_runtime_days(tmp_path):
    """M4 DoD：0 样本时必须显示"系统已运行 N 天，首批预言将于 X 日到期"。"""
    db = tmp_path / "aipulse.db"
    due = today_local() + timedelta(days=12)
    _seed_db(
        db,
        items=[_item("a", "标题 A", days_ago=5)],
        predictions=[_prediction("p1", date=today_local() - timedelta(days=5), due_date=due)],
    )

    html = _client(tmp_path, db=db).get("/predictions").text

    assert "系统已运行 5 天" in html
    assert f"首批预言将于 {due.isoformat()} 到期" in html
    assert "尚无到期判定结果" in html or "已累计" in html


def test_predictions_scoreboard_with_results(tmp_path):
    db = tmp_path / "aipulse.db"
    today = today_local()
    _seed_db(
        db,
        predictions=[
            _prediction("p1", status="verified", verdict="hit", verdict_score=1.0, confidence=0.8),
            _prediction("p2", status="verified", verdict="miss", verdict_score=0.0, confidence=0.6),
            _prediction("p3", status="unverifiable", verdict=None, confidence=0.5),
            _prediction("p4"),
        ],
    )

    html = _client(tmp_path, db=db).get("/predictions").text

    assert "50.0%" in html  # 1/2 命中
    assert "Brier" in html
    assert "校准曲线" in html
    assert "<polyline" in html  # 有样本才画线
    assert "0.05, 0.5" in html  # 低置信桶必须存在（v1.9）
    assert "无法验证" in html
    # 分母口径：unverifiable / pending 不入分母
    assert "不计入" in html
    assert today.isoformat() in html


def test_home_renders_latest_report(tmp_path):
    reports = tmp_path / "reports"
    _write_report(reports, (today_local() - timedelta(days=1)).isoformat(), headline="昨日头条")
    _write_report(reports, today_local().isoformat(), headline="今日头条：预言闭环")

    html = _client(tmp_path, reports=reports).get("/").text

    assert "今日头条：预言闭环" in html
    assert "vLLM 发布 v1" in html
    assert "跨源" in html  # seen_in > 1
    assert "为什么重要" in html and "因为重要" in html
    assert "到期验证" in html
    # 回归：`meta.analysis.items` 会取到 dict.items 方法本身（Jinja 先属性后键），必须用下标
    assert "条目 1" in html
    assert "built-in method" not in html


def test_home_renders_unified_format(tmp_path):
    """Web 与 brief.md 复用同一套结构：头条来源、分条总览、四节点评、五列表格。"""
    reports = tmp_path / "reports"
    day = today_local().isoformat()
    target = reports.joinpath(*day.split("-"))
    target.mkdir(parents=True, exist_ok=True)
    (target / "daily.json").write_text(
        json.dumps(
            {
                "date": day,
                "headline": "推理框架进入工程化决战",
                "headline_item_id": "a",
                "overview_bullets": [
                    {"icon": "🛠️", "topic": "开源", "text": "vLLM 连续霸榜"},
                ],
                "executive_summary": "工程编排成为新战场。",
                "editor_note": {
                    "core": "核心判断",
                    "cross_signal": "交叉信号",
                    "counterintuitive": "反直觉",
                    "risk": "风险",
                },
                "sections": [
                    {"name": "开源项目", "summary": "", "item_ids": ["a", "b"]},
                    {"name": "产业与新闻", "summary": "", "item_ids": []},
                ],
                "comments": [],
                "contradictions": [],
                "underrated": [],
                "stats": {},
                "items": {
                    "a": {
                        "id": "a",
                        "source": "github_trending",
                        "title": "vLLM v1",
                        "url": "https://example.com/a",
                        "summary": "推理加速",
                        "hot_score": 91.2,
                        "streak_days": 3,
                        "seen_in": ["github_trending"],
                    },
                    "b": {
                        "id": "b",
                        "source": "github_trending",
                        "title": "LinkSwift",
                        "url": "https://example.com/b",
                        "summary": "网盘直链",
                        "hot_score": 70.0,
                        "seen_in": ["github_trending"],
                    },
                },
                "meta": {
                    "mode": "hybrid",
                    "analysis": {"items": 2, "topics": 1},
                    "brief": {"max_items_per_section": 1},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (target / "meta.json").write_text(
        json.dumps(
            {
                "mode": "hybrid",
                "analysis": {"items": 2, "topics": 1},
                "brief": {"max_items_per_section": 1},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    html = _client(tmp_path, reports=reports).get("/").text

    assert "🔗 来源：github_trending · <a" in html or "🔗 来源" in html
    assert "https://example.com/a" in html
    assert "🛠️ <strong>开源</strong>：vLLM 连续霸榜" in html
    for heading in ("🎯 核心判断", "🔍 交叉信号", "🔄 反直觉", "⚠️ 风险提醒"):
        assert heading in html
    assert "连续 3 天" in html
    assert "另有 1 条未展示" in html
    assert "LinkSwift" not in html  # 超出上限的条目不在首屏，但有数量提示
    assert "产业与新闻" not in html  # 空板块不渲染
    assert "为什么重要" in html and "立场" in html
    assert "—" in html  # 未生成增强字段的占位


def test_archive_lists_and_selects_days(tmp_path):
    reports = tmp_path / "reports"
    older = (today_local() - timedelta(days=3)).isoformat()
    _write_report(reports, older, headline="旧的一天")

    client = _client(tmp_path, reports=reports)
    listing = client.get("/archive").text
    assert older in listing

    picked = client.get(f"/archive?date={older}").text
    assert "旧的一天" in picked
    assert "新增实体提及 2" in picked  # 口径澄清后的字段名（archive 页展示）


def test_topics_and_search_pages(tmp_path):
    db = tmp_path / "aipulse.db"
    today = today_local()
    _seed_db(
        db,
        items=[_item("a", "Qwen3 推理优化")],
        topics=[
            Topic(
                id="tp_1",
                name="推理加速",
                keywords=["vllm", "推理"],
                item_count=3,
                date=today,
                avg_hot_score=77.7,
            )
        ],
        entities=[Entity(name="vLLM", type="framework", item_id="a", date=today, weight=2.0)],
    )
    client = _client(tmp_path, db=db)

    topics = client.get("/topics").text
    assert "推理加速" in topics
    assert "vLLM" in topics
    assert "█" in topics or "▄" in topics  # 跨日演化密度条

    search = client.get("/search", params={"q": "Qwen3"}).text
    assert "Qwen3 推理优化" in search
    assert "共 1 条结果" in search

    partial = client.get("/search/partial", params={"q": "Qwen3"}).text
    assert "Qwen3 推理优化" in partial
    assert "<html" not in partial  # HTMX 片段不是整页

    assert "没有匹配的条目" in client.get("/search", params={"q": "不存在的关键词"}).text


def test_report_index_handles_broken_json(tmp_path):
    reports = tmp_path / "reports"
    bad = reports.joinpath("2026", "10", "13")
    bad.mkdir(parents=True)
    (bad / "daily.json").write_text("{ 不是合法 JSON", encoding="utf-8")

    index = ReportIndex(reports)
    assert index.load_daily("2026-10-13") is None
    assert index.load_meta("2026-10-13") == {}
    assert index.load_markdown("2026-10-13", "missing.md") == ""


# ── 校准曲线坐标（纯函数）──────────────────────────────────────────


def test_calibration_chart_maps_points_and_skips_empty_buckets():
    from aipulse.analysis.stats import CALIBRATION_BUCKETS, CalibrationBucket

    buckets = []
    for label, _lo, _hi in CALIBRATION_BUCKETS:
        bucket = CalibrationBucket(label=label)
        if label.startswith("[0.5"):
            bucket.n, bucket.hits, bucket.confidence_sum = 2, 1, 1.2
        buckets.append(bucket)

    chart = build_calibration_chart(buckets)

    assert chart["has_points"] is True
    assert len(chart["points"]) == 1  # 空桶不画点
    point = chart["points"][0]
    assert point["n"] == 2
    assert point["hit_rate"] == 0.5
    # 0.6 置信度落在 x 轴的左 3/5 处，命中的点在 y 轴中点
    assert chart["x0"] < point["cx"] < chart["x1"]
    assert chart["y0"] > point["cy"] > chart["y1"]
    assert chart["polyline"] == f"{point['cx']},{point['cy']}"
    assert len(chart["ticks"]) == 5
    assert chart["diagonal"] == {
        "x1": chart["x0"],
        "y1": chart["y0"],
        "x2": chart["x1"],
        "y2": chart["y1"],
    }


def test_calibration_chart_zero_samples_is_empty():
    from aipulse.analysis.stats import CALIBRATION_BUCKETS, CalibrationBucket

    chart = build_calibration_chart(
        [CalibrationBucket(label=label) for label, _lo, _hi in CALIBRATION_BUCKETS]
    )

    assert chart["has_points"] is False
    assert chart["polyline"] == ""
    assert chart["points"] == []


def test_date_only_isoformat_used_in_report_index(tmp_path):
    """报告日期目录必须是 YYYY/MM/DD 三层，否则索引不到（与 FileNotifier 对齐）。"""
    reports = tmp_path / "reports"
    day = date(2026, 10, 15)
    _write_report(reports, day.isoformat(), headline="对齐检查")

    assert ReportIndex(reports).days() == ["2026-10-15"]


# ── CLI 入口 ───────────────────────────────────────────────────────


def test_serve_command_wires_uvicorn(monkeypatch):
    """`aipulse serve --port 8123` 必须把应用与端口交给 uvicorn（不真起服务）。"""
    from typer.testing import CliRunner

    from aipulse.cli.main import app as cli_app

    captured: dict[str, object] = {}

    def fake_run(application, **kwargs):  # noqa: ANN001, ANN003 - 测试替身
        captured["app"] = application
        captured.update(kwargs)

    monkeypatch.setattr("aipulse.cli.commands.serve.uvicorn.run", fake_run)

    result = CliRunner().invoke(cli_app, ["serve", "--port", "8123"])

    assert result.exit_code == 0, result.output
    assert captured["port"] == 8123
    assert captured["host"] == "127.0.0.1"
    assert captured["app"] is not None
    assert "AI 脉搏看板" in result.output
