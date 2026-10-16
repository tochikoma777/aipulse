"""每日流水线端到端单测（--no-collect + --skip-llm，零网络零花费）。"""

from __future__ import annotations

import asyncio
import json as _json
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from aipulse.core.config import RunMode, load_settings
from aipulse.core.timeutil import today_local
from aipulse.pipeline.daily import analyze_day, run_daily
from aipulse.store.db import engine_for, init_db
from aipulse.store.models import Item, Prediction, Signal


def _seed(db_path):
    engine = init_db(db_path)
    now = datetime.now(tz=UTC)
    with Session(engine) as s:
        s.add(
            Item(
                id="a",
                source="github_trending",
                external_id="org/a",
                title="vLLM 发布 v1 加速推理",
                url="https://github.com/org/a",
                summary="vLLM 高性能推理",
                collected_at=now,
                published_at=now,
                metrics={"stars_total": 1000, "stars_in_window": 100},
                seen_in=["github_trending"],
                content_hash="h-a",
                hot_score=0.0,
            )
        )
        s.add(
            Item(
                id="b",
                source="hackernews",
                external_id="2",
                title="OpenAI GPT-5 讨论",
                url="https://news.ycombinator.com/item?id=2",
                summary="GPT-5 discussion",
                collected_at=now,
                published_at=now,
                metrics={"points": 200, "num_comments": 50},
                seen_in=["hackernews"],
                content_hash="h-b",
                hot_score=0.0,
            )
        )
        s.commit()
    engine.dispose()


def test_analyze_day_scores_and_writes(monkeypatch, tmp_path):
    monkeypatch.setenv("AIPULSE_ROOT", str(tmp_path))
    load_settings.cache_clear()
    db = tmp_path / "t.db"
    _seed(db)
    from aipulse.store.db import engine_for

    engine = engine_for(db)
    from aipulse.core.timeutil import today_local

    with Session(engine) as s:
        stats = analyze_day(s, day=today_local())
    engine.dispose()
    assert stats["items"] == 2
    assert stats["scored"] == 2


def test_run_daily_off_mode_produces_reports(monkeypatch, tmp_path):
    """DoD ★：aipulse daily --skip-llm 端到端跑通并产出 daily.json（零 API 花费）。"""
    monkeypatch.setenv("AIPULSE_ROOT", str(tmp_path))
    load_settings.cache_clear()
    db = tmp_path / "t.db"
    _seed(db)

    result = asyncio.run(run_daily(no_collect=True, skip_llm=True, db_path=str(db)))

    assert result.mode == RunMode.OFF
    assert result.report_dir is not None
    assert (result.report_dir / "brief.md").exists()
    assert (result.report_dir / "daily.json").exists()
    assert (result.report_dir / "meta.json").exists()

    daily = _json.loads((result.report_dir / "daily.json").read_text(encoding="utf-8"))
    assert daily["meta"]["mode"] == "off"
    assert len(daily["items"]) == 2


def test_run_daily_writes_scoreboard_and_signals(monkeypatch, tmp_path):
    """M4：记分板（v1.10）与 signals 快照必须随报告落盘，且进 meta 摘要。"""
    monkeypatch.setenv("AIPULSE_ROOT", str(tmp_path))
    load_settings.cache_clear()
    db = tmp_path / "t.db"
    _seed(db)
    today = today_local()
    engine = init_db(db)
    with Session(engine, expire_on_commit=False) as s:
        # 两次快照 → 可算 star 增速（跨天在 Actions 中由 cache 恢复得到）
        s.add(
            Signal(
                entity_type="repo",
                entity_key="org/a",
                metric="stars",
                value=1000,
                ts=datetime.now(tz=UTC) - timedelta(hours=24),
            )
        )
        s.add(
            Signal(
                entity_type="repo",
                entity_key="org/a",
                metric="stars",
                value=1200,
                ts=datetime.now(tz=UTC) - timedelta(hours=1),
            )
        )
        s.add(
            Prediction(
                id="pred_ok",
                date=today - timedelta(days=30),
                statement="acme 将出现新仓库",
                category="community",
                confidence=0.8,
                horizon_days=30,
                due_date=today - timedelta(days=1),
                falsifiable_criteria="窗口内 acme 出现新仓库即命中",
                status="pending",
                criteria="github_new_repo",
                criteria_params={"owner": "acme"},
            )
        )
        s.add(
            Signal(
                entity_type="repo",
                entity_key="acme/new",
                metric="stars",
                value=1,
                ts=datetime.now(tz=UTC) - timedelta(days=10),
            )
        )
        s.commit()
    engine.dispose()

    result = asyncio.run(run_daily(no_collect=True, skip_llm=True, db_path=str(db)))

    assert (result.report_dir / "scoreboard.md").exists()
    assert (result.report_dir / "signals.json").exists()
    assert (result.report_dir / "verdicts.md").exists()

    signals = _json.loads((result.report_dir / "signals.json").read_text(encoding="utf-8"))
    assert signals["date"] == result.day.isoformat()
    assert signals["with_velocity"] >= 1
    hot = next(s for s in signals["series"] if s["entity_key"] == "org/a")
    assert hot["points"] == 2
    assert hot["delta"] == 200.0
    assert hot["velocity_per_hour"] is not None

    # meta.json 里要有可直接比对的关键摘要
    assert result.meta["signals"]["with_velocity"] >= 1
    assert result.meta["predictions"]["verified"] == 1

    assert "🎯 预言记分板" in (result.report_dir / "scoreboard.md").read_text(encoding="utf-8")
    assert "命中" in (result.report_dir / "verdicts.md").read_text(encoding="utf-8")


def test_run_daily_auto_verify_off_mode(monkeypatch, tmp_path):
    """`daily` 在 off 档自动验证量化判据预言（零 LLM），并写进 meta。"""
    monkeypatch.setenv("AIPULSE_ROOT", str(tmp_path))
    load_settings.cache_clear()
    db = tmp_path / "t.db"
    _seed(db)
    today = today_local()
    engine = init_db(db)
    with Session(engine, expire_on_commit=False) as s:
        s.add(
            Prediction(
                id="pred_due",
                date=today - timedelta(days=30),
                statement="acme 将出现新仓库",
                category="community",
                confidence=0.7,
                horizon_days=30,
                due_date=today - timedelta(days=1),
                falsifiable_criteria="窗口内 acme 出现新仓库即命中",
                status="pending",
                criteria="github_new_repo",
                criteria_params={"owner": "acme"},
            )
        )
        s.add(
            Signal(
                entity_type="repo",
                entity_key="acme/new",
                metric="stars",
                value=1,
                ts=datetime.now(tz=UTC) - timedelta(days=10),
            )
        )
        s.commit()
    engine.dispose()

    result = asyncio.run(run_daily(no_collect=True, skip_llm=True, db_path=str(db)))

    assert result.meta["verify"]["verified"] == 1
    assert result.meta["verify"]["llm_calls"] == 0


def test_run_daily_hybrid_generates_and_stores_predictions(monkeypatch, tmp_path):
    """★ M4：`mode: hybrid` 下 daily 必须**真的生成预言并入库**。

    没有这条，配了 API key 记分板样本也不会增长——hybrid 檔的定义就是"预言生成 + 主编点评"。
    用桩 LLM（按 purpose 分发）验证，不碰网络。
    """
    import aipulse.pipeline.daily as daily_mod
    from aipulse.core.config import RunMode, Settings
    from aipulse.llm.base import LLMResult
    from aipulse.store.repo_predictions import list_predictions

    # 只把 data_dir 指到临时目录，**不动 AIPULSE_ROOT**——
    # prompts/ 与 configs/ 都按 project_root() 解析，改了 root 就找不到模板了。
    settings = Settings(
        app={"data_dir": str(tmp_path / "data")},
        mode="hybrid",
        llm={"api_key": "sk-test-key"},
    )
    monkeypatch.setattr(daily_mod, "load_settings", lambda *a, **k: settings)
    db = tmp_path / "t.db"
    _seed(db)

    brief_json = _json.dumps(
        {
            "headline": "hybrid 头条",
            "executive_summary": "总览",
            "editor_note": "主编点评",
            "sections": [],
            "contradictions": [],
            "underrated": [],
        },
        ensure_ascii=False,
    )
    predict_json = _json.dumps(
        {
            "predictions": [
                {
                    "statement": "vLLM 将在 30 天内发布 v2 并保持 star 增速领先",
                    "category": "capability",
                    "confidence": 0.75,
                    "horizon_days": 30,
                    "falsifiable_criteria": "到期日 vLLM 官方仓库 tag 出现 v2.* 即命中",
                    "rationale": "star 增速与主题热度支持。",
                    "evidence_item_ids": ["a", "b"],
                }
            ]
        },
        ensure_ascii=False,
    )

    class _StubClient:
        def __init__(self) -> None:
            self.purposes: list[str] = []

        async def chat(self, messages, **kwargs):  # noqa: ANN001, ANN003
            purpose = kwargs.get("purpose", "general")
            self.purposes.append(purpose)
            content = brief_json if purpose.startswith("brief") else predict_json
            return LLMResult(content=content, model="stub/strong")

    stub = _StubClient()
    monkeypatch.setattr(daily_mod, "build_client", lambda *a, **k: stub)

    result = asyncio.run(run_daily(no_collect=True, skip_llm=False, db_path=str(db)))

    assert result.mode == RunMode.HYBRID
    assert "predict_generate" in stub.purposes
    gen = result.meta["prediction_generation"]
    assert gen["mode"] == "hybrid"
    assert gen["generated"] == 1 and gen["inserted"] == 1
    assert gen["dropped"] == []

    engine = engine_for(db)
    with Session(engine, expire_on_commit=False) as s:
        rows = list_predictions(s)
    engine.dispose()
    assert len(rows) == 1
    assert rows[0].origin == "llm" and rows[0].status == "pending"

    # 预言的判定结果与列表都要落进报告（§11.1）
    preds_md = (result.report_dir / "predictions.md").read_text(encoding="utf-8")
    assert "今日新生成的预言" in preds_md
    assert "vLLM 将在 30 天内发布 v2" in preds_md

    scoreboard = (result.report_dir / "scoreboard.md").read_text(encoding="utf-8")
    assert "**1** 条预言" in scoreboard  # 0 样本→1 条待验证

    daily_json = _json.loads((result.report_dir / "daily.json").read_text(encoding="utf-8"))
    assert daily_json["meta"]["prediction_generation"]["generated"] == 1


def test_run_daily_off_mode_does_not_call_predictor(monkeypatch, tmp_path):
    """off 档禁止任何模型请求（红线 8）：预言生成必须完全不触发。"""
    monkeypatch.setenv("AIPULSE_ROOT", str(tmp_path))
    monkeypatch.delenv("AIPULSE_LLM__API_KEY", raising=False)
    load_settings.cache_clear()
    db = tmp_path / "t.db"
    _seed(db)

    import aipulse.pipeline.daily as daily_mod

    async def _boom(**kwargs):  # noqa: ANN003
        raise AssertionError("off 档不得触发预言生成（红线 8）")

    # off 档仍会构造 NullLLM（那本身不产生网络请求），关键是**预言生成整条路径不被触发**
    monkeypatch.setattr(daily_mod, "generate_predictions", _boom)

    result = asyncio.run(run_daily(no_collect=True, skip_llm=True, db_path=str(db)))

    assert result.meta["prediction_generation"] == {
        "mode": "off",
        "generated": 0,
        "inserted": 0,
        "dropped": [],
    }
    assert "本次运行没有新增预言" in (result.report_dir / "predictions.md").read_text(
        encoding="utf-8"
    )


def _seed_windowed(db_path):
    """窗口内 1 条 + 窗口外 1 条。

    窗口按 `collected_at` 过滤（不是 published_at）——窗口语义是"本次运行采集到的"，
    所以这里必须差的是 collected_at。
    """
    engine = init_db(db_path)
    now = datetime.now(tz=UTC)
    rows = [
        ("in_window", "窗口内的条目", now - timedelta(hours=1), "h-in"),
        ("out_window", "窗口外的条目", now - timedelta(hours=30), "h-out"),
    ]
    with Session(engine) as s:
        for item_id, title, collected, chash in rows:
            s.add(
                Item(
                    id=item_id,
                    source="github_trending",
                    external_id=item_id,
                    title=title,
                    url=f"https://example.com/{item_id}",
                    summary=title,
                    collected_at=collected,
                    published_at=collected,
                    metrics={"stars_total": 10},
                    seen_in=["github_trending"],
                    content_hash=chash,
                    hot_score=0.0,
                )
            )
        s.commit()
    engine.dispose()


def test_daily_passes_one_window_to_both_collect_and_analyze(monkeypatch, tmp_path):
    """★ 回归防线：collect 与 analyze 必须共用同一个窗口对象。

    之前两处独立计算（collect 按 `--since` 往前滚、analyze 按本地自然日切），
    定时在北京 07:00 跑时只重叠约 7 小时，实测当天 analysis.items=1——
    日报实际只覆盖 7 小时却自称"过去 24 小时"。
    """
    monkeypatch.setenv("AIPULSE_ROOT", str(tmp_path))
    load_settings.cache_clear()
    db = tmp_path / "t.db"
    _seed_windowed(db)

    import aipulse.pipeline.daily as daily_mod

    captured: dict[str, object] = {}

    async def _spy(**kwargs):  # noqa: ANN003
        captured["window"] = kwargs.get("window")
        return None

    monkeypatch.setattr(daily_mod, "run_collect", _spy)

    result = asyncio.run(run_daily(since="24h", skip_llm=True, db_path=str(db)))

    window = captured["window"]
    assert window is not None, "daily 必须把窗口显式传给 run_collect"
    start, end = window  # type: ignore[misc]
    assert end - start == timedelta(hours=24)

    # analyze 用的是同一个窗口：30 小时前的那条不能进来
    assert result.analysis["items"] == 1
    # 窗口要写进报告，且是滚动 24h 而不是"本地自然日"
    assert result.meta["window"]["hours"] == 24.0
    assert result.meta["window"]["since"] == start.isoformat()
    brief_md = (result.report_dir / "brief.md").read_text(encoding="utf-8")
    assert "覆盖窗口" in brief_md


def test_analyze_day_honors_explicit_window_over_local_day(monkeypatch, tmp_path):
    """显式传窗口时不得再退回 `day_window(day)`。"""
    monkeypatch.setenv("AIPULSE_ROOT", str(tmp_path))
    load_settings.cache_clear()
    db = tmp_path / "t.db"
    _seed_windowed(db)

    engine = engine_for(db)
    now = datetime.now(tz=UTC)
    with Session(engine) as s:
        # 只取最近 2 小时 → 两条都不在窗口内
        stats = analyze_day(s, day=today_local(), window=(now - timedelta(hours=2), now))
    engine.dispose()
    assert stats["items"] == 1  # 只有 1 小时前那条

    with Session(engine) as s:
        # 取最近 48 小时 → 两条都在
        stats_wide = analyze_day(s, day=today_local(), window=(now - timedelta(hours=48), now))
    engine.dispose()
    assert stats_wide["items"] == 2


def test_meta_analysis_entities_key_is_explicit(monkeypatch, tmp_path):
    """口径澄清：字段名必须是 `new_entity_mention_rows`（本次新增行数），不是"当日实体数"。"""
    monkeypatch.setenv("AIPULSE_ROOT", str(tmp_path))
    load_settings.cache_clear()
    db = tmp_path / "t.db"
    _seed(db)

    result = asyncio.run(run_daily(no_collect=True, skip_llm=True, db_path=str(db)))

    assert "new_entity_mention_rows" in result.analysis
    assert "entities" not in result.analysis
    assert result.meta["signals"]["min_window_hours"] == 6.0
    assert "insufficient" in result.meta["signals"]
