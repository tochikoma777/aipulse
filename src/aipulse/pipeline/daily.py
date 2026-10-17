"""每日流水线编排（设计方案 §2.1 L6 / §12）。

`collect → analyze(打分+聚类+实体) → brief(推演) → render(渲染) → notify(落盘)`。

三档模式贯穿整条链路：off 档零 LLM 调用（client 注入 NullLLM），
hybrid/full 才真正发请求。`--skip-llm` / `--no-llm` 强制本运行按 off 走。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlmodel import Session

from aipulse.analysis.cluster import cluster_items
from aipulse.analysis.entities import build_entity_rows, count_entities
from aipulse.analysis.score import score_items
from aipulse.analysis.signals import build_signals_summary, trending_streak_days
from aipulse.analysis.stats import PredictionStats, compute_prediction_stats
from aipulse.core.config import RunMode, Settings, load_settings, load_sources
from aipulse.core.logging import get_logger
from aipulse.core.timeutil import day_window, today_local, utcnow, window_since
from aipulse.llm.base import LLMClient, build_client
from aipulse.notify.base import RenderedReport
from aipulse.notify.file import FileNotifier
from aipulse.pipeline.collect import CollectResult, run_collect
from aipulse.reasoning.brief import BriefOutput, generate_brief
from aipulse.reasoning.predictor import PredictOutput, generate_predictions
from aipulse.reasoning.verifier import verify_due_predictions
from aipulse.render.json_out import render_json
from aipulse.render.markdown import render_markdown
from aipulse.render.predictions import render_predictions_markdown
from aipulse.render.scoreboard import render_scoreboard_markdown
from aipulse.render.verdicts import render_verdicts_markdown
from aipulse.schema.brief import DailyBrief
from aipulse.store.db import engine_for, ensure_schema
from aipulse.store.models import Item, Topic
from aipulse.store.repo_items import (
    apply_hot_scores,
    apply_topic_ids,
    list_entities,
    list_items_in_window,
    list_signals,
    list_topics,
    upsert_entities,
    upsert_topics,
)
from aipulse.store.repo_predictions import (
    insert_predictions,
    list_predictions,
    list_verified_since,
)
from aipulse.store.repo_runs import record_pipeline_run

log = get_logger(__name__)


@dataclass
class DailyResult:
    day: date
    mode: RunMode
    collected: CollectResult | None
    analysis: dict[str, Any]
    brief: DailyBrief
    items: dict[str, Item] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    report_dir: Path | None = None
    files: list[str] = field(default_factory=list)


def report_dir_for(settings: Settings, day: date) -> Path:
    parts = day.isoformat().split("-")
    return settings.data_dir() / "reports" / parts[0] / parts[1] / parts[2]


def window_digest(window: tuple[datetime, datetime], tz_name: str) -> dict[str, Any]:
    """把窗口写成报告可读的摘要（UTC 原值 + 本地展示串）。"""
    start, end = window
    zone = ZoneInfo(tz_name)
    local = end.astimezone(zone)
    return {
        "since": start.isoformat(),
        "until": end.isoformat(),
        "hours": round((end - start).total_seconds() / 3600, 1),
        # 展示用本地时区：UTC 串会让"覆盖哪一天"看起来对不上
        "since_local": start.astimezone(zone).isoformat(timespec="minutes"),
        "until_local": local.isoformat(timespec="minutes"),
        "tz": tz_name,
    }


def analyze_day(
    session: Session,
    *,
    day: date,
    window: tuple[datetime, datetime] | None = None,
    state_sources: set[str] | None = None,
    discovery_sources: set[str] | None = None,
) -> dict[str, Any]:
    """打分 + 聚类 + 实体统计，落库。返回本次运行的落库增量统计。

    `window` 为 None 时退回 `day_window(day)`（本地自然日，CLI `analyze --date` 用）；
    `daily` 必须显式传入与 collect 共用的滚动窗口。

    窗口过滤按源的时间语义分流（v1.15 三态）：event 看 `published_at`，
    state 看 `last_seen_at`，discovery 看 `first_seen_at`（arXiv/HF 索引滞后）。

    注意口径：`new_entity_mention_rows` 是**本次运行新增的实体提及行数**，不是当日实体总数——
    同一天内同一实体的重复提及会被 `upsert_entities` 去重（这是对的），
    所以同一天第二次运行时该值会显著变小。要看"当日实体总览"请查库（Web `/topics` 就是这么做的）。
    """
    start, end = window if window is not None else day_window(day)
    sources_cfg = load_sources()
    states = sources_cfg.state_sources() if state_sources is None else state_sources
    discoveries = (
        sources_cfg.discovery_sources() if discovery_sources is None else discovery_sources
    )
    items = list_items_in_window(
        session,
        since=start,
        until=end,
        state_sources=states,
        discovery_sources=discoveries,
    )
    if not items:
        log.warning("pipeline.analyze.empty", day=day.isoformat())
        return {"items": 0, "scored": 0, "topics": 0, "new_entity_mention_rows": 0}

    scores = score_items(session, items)
    apply_hot_scores(session, scores)

    topics, mapping = cluster_items(items, day=day)
    upsert_topics(session, topics)
    apply_topic_ids(session, mapping)

    entity_rows = build_entity_rows(items, day=day)
    n_entities = upsert_entities(session, entity_rows)

    # ★ 状态型源附带信号：连续在榜 N 天（比单日热度更能说明"真火"）。
    #   写入 metrics 是为了让渲染层零额外查询即可展示，并随 daily.json 留档。
    state_items = 0
    for item in items:
        if item.source not in states:
            continue
        streak = trending_streak_days(session, item, anchor=day)
        if streak > 0:
            item.metrics = {**(item.metrics or {}), "streak_days": streak}
            state_items += 1
    if state_items:
        session.commit()

    log.info(
        "pipeline.analyze.done",
        items=len(items),
        scored=len(scores),
        topics=len(topics),
        new_entity_mention_rows=n_entities,
        state_items=state_items,
    )
    return {
        "items": len(items),
        "scored": len(scores),
        "topics": len(topics),
        "new_entity_mention_rows": n_entities,
        "state_items": state_items,
    }


async def _auto_verify(
    session: Session,
    *,
    client: LLMClient,
    settings: Settings,
    day: date,
    mode: RunMode,
) -> dict[str, Any]:
    """每日自动验证到期的预言；任何异常都降级为一条 meta 记录，绝不中断日报。"""
    try:
        outcome = await verify_due_predictions(
            session=session, client=client, settings=settings, today=day, mode=mode
        )
    except Exception as exc:  # 验证是增强，不允许拖垮主流程
        log.error("pipeline.verify.failed", error=repr(exc))
        return {"error": repr(exc)}
    return {
        "verified": outcome.verified,
        "unverifiable": outcome.unverifiable,
        "deferred": outcome.deferred,
        "failed": outcome.failed,
        "llm_calls": outcome.llm_calls,
    }


async def _generate_daily_predictions(
    session: Session,
    *,
    client: LLMClient,
    settings: Settings,
    day: date,
    mode: RunMode,
    items: list[Item],
    topics: list[Topic],
    entity_counts: dict[str, dict[str, Any]],
    skip_llm: bool,
) -> tuple[PredictOutput | None, dict[str, Any]]:
    """★ hybrid/full 档：自动生成当日预言并入库（§8.5 三档模式里 hybrid 的核心动作）。

    **为什么必须接进 daily**：`mode: hybrid` 的定义是"自动预言生成 + 主编点评"，
    若只生成简报不生成预言，配置 key 也不会让记分板样本增长——那就等于白配。
    任何异常都降级为一条 meta 记录，绝不中断日报（与 `_auto_verify` 同一策略）。
    """
    if mode == RunMode.OFF or skip_llm:
        return None, {"mode": mode.value, "generated": 0, "inserted": 0, "dropped": []}
    try:
        output = await generate_predictions(
            client=client,
            settings=settings,
            items=items,
            topics=topics,
            entity_counts=entity_counts,
            day=day,
            mode=mode,
            skip_llm=skip_llm,
        )
        inserted = insert_predictions(session, output.predictions)
    except Exception as exc:  # 预言生成是增强，不允许拖垮主流程
        log.error("pipeline.predict.failed", error=repr(exc))
        return None, {"mode": mode.value, "error": repr(exc)}
    summary = {
        "mode": mode.value,
        "generated": len(output.predictions),
        "inserted": inserted,
        "dropped": output.meta.get("dropped", []),
        "llm_calls": output.meta.get("llm_calls", 0),
    }
    log.info("pipeline.predict.done", **{k: v for k, v in summary.items() if k != "dropped"})
    return output, summary


def _stats_digest(stats: PredictionStats) -> dict[str, Any]:
    """记分板关键指标的精简摘要（写进 meta.json，便于跨天对比与 Web 首页）。"""
    return {
        "total": stats.total,
        "verified": stats.verified,
        "pending": stats.pending,
        "unverifiable": stats.unverifiable,
        "hit_rate": stats.hit_rate,
        "weighted_score": stats.weighted_score,
        "brier": stats.brier,
    }


async def run_daily(
    *,
    since: str = "24h",
    day: date | None = None,
    skip_llm: bool = False,
    no_collect: bool = False,
    db_path: str | Path | None = None,
) -> DailyResult:
    """执行一次完整日报流程。"""
    settings = load_settings()
    mode = RunMode.OFF if skip_llm else settings.effective_mode()
    report_day = day or today_local(settings.app.timezone)
    target_db = Path(db_path) if db_path else settings.db_path()
    ensure_schema(target_db)
    engine = engine_for(target_db)

    # ★ 窗口只在这里算一次，collect / analyze / brief / predict 全部共用。
    #   之前 collect 按 `--since 24h` 往前滚、analyze 按本地自然日切，两处独立计算：
    #   定时在北京 07:00 跑时窗口只重叠约 7 小时（实测当天 analysis.items=1），
    #   日报实际只覆盖 7 小时而不是"过去 24 小时"。
    window = window_since(since)
    sources_cfg = load_sources()
    state_sources = sources_cfg.state_sources()
    discovery_sources = sources_cfg.discovery_sources()

    collected: CollectResult | None = None
    if not no_collect:
        collected = await run_collect(since=since, window=window, db_path=str(target_db))
        # 状态型源的 `last_seen_at` 是"本次采集时刻"，必然晚于采集前算出的 window.until
        # （采集耗时几十秒）。不把右界推到采集结束，trending 条目会被自己的窗口过滤掉。
        # 事件型源不受影响（它们的 published_at 早已固定）。
        window = (window[0], max(window[1], utcnow()))

    analysis: dict[str, Any] = {}
    brief_out: BriefOutput | None = None
    verify_summary: dict[str, Any] | None = None
    pred_stats: PredictionStats | None = None
    verdicts_md = ""
    signals_summary: dict[str, Any] = {}
    # expire_on_commit=False：提交后实例属性不过期，session 关闭后仍可安全渲染 items
    with Session(engine, expire_on_commit=False) as session:
        analysis = analyze_day(
            session,
            day=report_day,
            window=window,
            state_sources=state_sources,
            discovery_sources=discovery_sources,
        )

        # 简报与预言的条目也取自同一个窗口，否则"分析过的"和"拿去生成预言的"不是一批
        start, end = window
        items = list_items_in_window(
            session,
            since=start,
            until=end,
            state_sources=state_sources,
            discovery_sources=discovery_sources,
        )
        topics = list_topics(session, report_day)
        entity_rows = list_entities(session, report_day)
        entity_counts = count_entities(entity_rows)

        client = build_client(settings, engine=engine)
        brief_out = await generate_brief(
            client=client,
            settings=settings,
            items=items,
            topics=topics,
            entity_counts=entity_counts,
            day=report_day,
            mode=mode,
            skip_llm=skip_llm,
        )
        # ★ hybrid/full：生成当日预言（off 档直接返回 None，零网络）
        predict_output, predict_summary = await _generate_daily_predictions(
            session,
            client=client,
            settings=settings,
            day=report_day,
            mode=mode,
            items=items,
            topics=topics,
            entity_counts=entity_counts,
            skip_llm=skip_llm,
        )
        if settings.pipeline.auto_verify:
            verify_started = utcnow()
            verify_summary = await _auto_verify(
                session, client=client, settings=settings, day=report_day, mode=mode
            )
            # 本次运行产生的判定结果 → verdicts.md（§11.1）
            verdicts_md = render_verdicts_markdown(
                list_verified_since(session, verify_started), generated_at=utcnow()
            )
        # ★ v1.10：记分板由 daily 自动产出，因此 Actions 每天 commit 的报告天然含记分板
        pred_stats = compute_prediction_stats(list_predictions(session))
        # ★ M4：signals 快照 + 增速随报告落盘（Actions 无持久化时的跨天佐证）
        signals_summary = build_signals_summary(
            list_signals(session),
            min_window_hours=settings.signals.min_velocity_window_hours,
        )
        record_pipeline_run(
            session,
            day=report_day,
            stage="daily",
            status="ok",
            stats={"mode": mode.value, **analysis, "verify": verify_summary},
        )
    engine.dispose()

    assert brief_out is not None
    assert pred_stats is not None
    meta: dict[str, Any] = {
        "mode": mode.value,
        "day": report_day.isoformat(),
        "generated_at": utcnow().isoformat(),
        # ★ 日报现在跨两个自然日，不标窗口会让人以为漏采了半天
        "window": window_digest(window, settings.app.timezone),
        "analysis": analysis,
        "llm": {
            "degraded": brief_out.meta.get("degraded", False),
            "degraded_reason": brief_out.meta.get("degraded_reason", ""),
            "calls": brief_out.meta.get("llm_calls", 0),
        },
    }
    if collected is not None:
        meta["collect"] = {
            "ok_sources": len(collected.ok_sources),
            "failed_sources": len(collected.failed_sources),
            "skipped": len(collected.skipped),
            "total_items": len(collected.items),
        }
    meta["verify"] = verify_summary
    meta["predictions"] = _stats_digest(pred_stats)
    meta["prediction_generation"] = predict_summary
    meta["brief"] = {"max_items_per_section": settings.brief.max_items_per_section}
    meta["signals"] = {
        "entities": signals_summary.get("entity_count", 0),
        "points": signals_summary.get("point_count", 0),
        "with_velocity": signals_summary.get("with_velocity", 0),
        "insufficient": signals_summary.get("insufficient", 0),
        "cold_start": signals_summary.get("cold_start", 0),
        "min_window_hours": signals_summary.get("min_window_hours"),
    }

    # ── 渲染 + 落盘（走 FileNotifier，符合 §11.2 的 Notifier 抽象）──
    generated_at = utcnow()
    report_dir = report_dir_for(settings, report_day)
    report = RenderedReport(
        date=report_day.isoformat(),
        files={
            "brief.md": render_markdown(
                brief_out.brief,
                brief_out.items,
                meta,
                generated_at=generated_at,
                max_items_per_section=settings.brief.max_items_per_section,
            ),
            "daily.json": render_json(
                brief_out.brief, brief_out.items, meta, generated_at=generated_at
            ),
            "meta.json": json.dumps(meta, ensure_ascii=False, indent=2),
            "scoreboard.md": render_scoreboard_markdown(pred_stats),
            "verdicts.md": verdicts_md,
            "predictions.md": render_predictions_markdown(
                predict_output.predictions if predict_output else [],
                dropped=predict_summary.get("dropped") or [],
                generated_at=generated_at,
                # 证据 id 翻成标题写进报告：库里看得到 ≠ 报告里审得了
                items=brief_out.items,
            ),
            "signals.json": json.dumps(
                {
                    "date": report_day.isoformat(),
                    "generated_at": generated_at.isoformat(),
                    **signals_summary,
                },
                ensure_ascii=False,
                indent=2,
            ),
        },
    )
    notifier = FileNotifier(str(settings.data_dir() / "reports"))
    notify_result = await notifier.send(report)
    if not notify_result.ok:
        log.warning("pipeline.notify.failed", detail=notify_result.detail)

    return DailyResult(
        day=report_day,
        mode=mode,
        collected=collected,
        analysis=analysis,
        brief=brief_out.brief,
        items=brief_out.items,
        meta=meta,
        report_dir=report_dir,
        files=list(report.files.keys()),
    )


__all__ = ["DailyResult", "analyze_day", "report_dir_for", "run_daily"]
