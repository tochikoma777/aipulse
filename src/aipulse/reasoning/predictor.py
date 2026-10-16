"""预言生成（设计方案 §10.2.1，M3a）。

流程：当日 Top 条目 + 主题演化 + 实体增速组装上下文 → `prompts/predict/generate.j2` →
结构化输出（`PredictionBatch`）→ 硬校验（模糊措辞 / confidence 步长 / horizon /
falsifiable_criteria / 证据 ≥2）→ 不合法触发**一次**语义重写 → 仍不合法则丢弃并记录。

红线：任何缺 `falsifiable_criteria` 或含模糊措辞的预言不得入库。
"""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import date
from typing import Any, cast

import httpx

from aipulse.core.config import RunMode, Settings
from aipulse.core.logging import get_logger
from aipulse.llm.base import ChatMessage, LLMClient
from aipulse.llm.prompt import render_prompt
from aipulse.llm.structured import generate_structured
from aipulse.schema.prediction import Prediction, PredictionBatch, validate_prediction
from aipulse.store.models import Item, Topic
from aipulse.store.models import Prediction as PredictionRow
from aipulse.store.repo_predictions import prediction_id
from aipulse.utils.text import estimate_tokens, truncate_summary

log = get_logger(__name__)

_MAX_CONTEXT_TOKENS = 12000


@dataclass
class PredictOutput:
    predictions: list[PredictionRow] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def _topic_name_map(topics: list[Topic]) -> dict[str, str]:
    return {t.id: t.name for t in topics}


def _item_context(item: Item, topic_name: str | None) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "source": item.source,
        "hot_score": round(float(item.hot_score or 0.0), 1),
        "topic": topic_name or "",
        "summary": truncate_summary(item.summary or "", 300),
    }


def _trim_to_budget(
    contexts: list[dict[str, Any]], budget: int = _MAX_CONTEXT_TOKENS
) -> list[dict[str, Any]]:
    """总量超预算时从尾部丢弃（已按 hot_score 降序，丢的是最不重要的）。"""
    kept: list[dict[str, Any]] = []
    total = 0
    for ctx in contexts:
        total += estimate_tokens(json.dumps(ctx, ensure_ascii=False))
        if total > budget:
            break
        kept.append(ctx)
    return kept


def _validate_batch(
    drafts: list[Prediction],
    *,
    require_evidence: bool,
    known_item_ids: Collection[str] | None = None,
) -> tuple[list[Prediction], list[dict[str, Any]]]:
    """拆成 (合法, 不合法)。不合法项附带 reason 供重写与日志。"""
    valid: list[Prediction] = []
    dropped: list[dict[str, Any]] = []
    for draft in drafts:
        problems = validate_prediction(
            draft, require_evidence=require_evidence, known_item_ids=known_item_ids
        )
        if problems:
            dropped.append({"statement": draft.statement, "problems": problems})
        else:
            valid.append(draft)
    return valid, dropped


def _to_prediction_row(
    draft: Prediction, *, day: date, model: str, prompt_version: str, origin: str
) -> PredictionRow:
    return PredictionRow(
        id=prediction_id(day, draft.statement, origin),
        date=day,
        statement=draft.statement,
        category=draft.category,
        confidence=draft.confidence,
        horizon_days=draft.horizon_days,
        due_date=draft.due_date(day),
        falsifiable_criteria=draft.falsifiable_criteria,
        rationale=draft.rationale,
        evidence_item_ids=draft.evidence_item_ids,
        model=model,
        prompt_version=prompt_version,
        status="pending",
        origin=origin,
        criteria=draft.criteria,
        criteria_params=draft.criteria_params,
    )


def _rewrite_user_message(raw: str, dropped: list[dict[str, Any]]) -> str:
    lines = [
        "你上一次输出的部分预言未通过可证伪校验，请修正后**只**重新输出完整合法 JSON：",
    ]
    for item in dropped:
        lines.append(f"- 预言「{item['statement']}」：{'；'.join(item['problems'])}")
    lines.append("要求：改掉模糊措辞、补上明确的 falsifiable_criteria，并保留合法条目。")
    return "\n".join(lines)


async def generate_predictions(
    *,
    client: LLMClient,
    settings: Settings,
    items: list[Item],
    topics: list[Topic],
    entity_counts: dict[str, dict[str, Any]],
    day: date,
    mode: RunMode,
    skip_llm: bool = False,
) -> PredictOutput:
    """生成当日预言。off 档 / skip_llm 直接返回空（手写预言才是 off 档核心）。"""
    if mode == RunMode.OFF or skip_llm:
        return PredictOutput(meta={"mode": "off", "generated": 0})

    topic_names = _topic_name_map(topics)
    ranked = sorted(items, key=lambda it: -(float(it.hot_score or 0.0)))[
        : settings.pipeline.daily_top_n
    ]
    contexts = _trim_to_budget(
        [_item_context(it, topic_names.get(it.topic_id or "")) for it in ranked]
    )
    # ★ 候选证据池 == 注入 prompt 的那批条目。注入什么就只允许引用什么，
    #   事后校验才有可判定的依据（否则"证据真实存在"这句话无从核实）。
    known_item_ids = {c["id"] for c in contexts}
    if len(known_item_ids) < 2:
        # 池子凑不出 2 条证据时别浪费一次 LLM 调用：生成出来也必然被拒收。
        log.warning("predict.evidence_pool_too_small", pool=len(known_item_ids))
        return PredictOutput(
            meta={
                "mode": mode.value,
                "generated": 0,
                "llm_calls": 0,
                "dropped": [],
                "degraded": True,
                "degraded_reason": (
                    f"候选证据池不足 2 条（实际 {len(known_item_ids)}），本次未生成预言"
                ),
            }
        )

    rendered, template = render_prompt(
        "predict/generate",
        items_json=json.dumps(contexts, ensure_ascii=False),
        evidence_pool="\n".join(f"- [{c['id']}] {c['title']}" for c in contexts),
        topics_json=json.dumps(
            [{"name": t.name, "keywords": t.keywords, "item_count": t.item_count} for t in topics],
            ensure_ascii=False,
        ),
        entities_json=json.dumps(
            [
                {"name": n, "type": v["type"], "count": v["count"]}
                for n, v in sorted(entity_counts.items(), key=lambda kv: -kv[1]["count"])[:20]
            ],
            ensure_ascii=False,
        ),
        horizons=list(settings.pipeline.prediction_horizons),
    )

    meta: dict[str, Any] = {"mode": mode.value, "generated": 0, "llm_calls": 0, "dropped": []}
    try:
        parsed, result = await generate_structured(
            client,
            [ChatMessage(role="system", content=rendered)],
            response_model=PredictionBatch,
            temperature=template.temperature,
            max_tokens=4000,
            purpose="predict_generate",
            model_tier=template.model_tier,
        )
    except httpx.TimeoutException as exc:
        # ★ 超时只是"这一次没等到结果"，不是模型判错了：预言按天生成，明天会自然重跑，
        #   记成 llm_failed 会把一次网络抖动混进失败口径，污染对预言系统的判断。
        log.warning("predict.llm_timeout", error=repr(exc))
        meta["degraded"] = True
        meta["degraded_reason"] = "LLM 调用超时：本次未生成预言"
        return PredictOutput(meta=meta)
    except Exception as exc:  # 其余网络/预算异常：降级，不中断
        log.error("predict.llm_failed", error=repr(exc))
        meta["degraded"] = True
        meta["degraded_reason"] = f"LLM 调用失败：{type(exc).__name__}"
        return PredictOutput(meta=meta)

    meta["llm_calls"] += 1
    if parsed is None:
        meta["degraded"] = True
        meta["degraded_reason"] = "LLM 结构化输出失败，无可解析预言"
        return PredictOutput(meta=meta)
    assert result is not None  # parsed 非 None 时 result 必非 None（同一调用返回）

    batch = cast(PredictionBatch, parsed)
    valid, dropped = _validate_batch(
        batch.predictions, require_evidence=True, known_item_ids=known_item_ids
    )

    # ── 一次语义重写：把问题回传，要求修正 ──────────────────────────
    if dropped:
        log.warning("predict.rewrite", n=len(dropped))
        repair = [
            ChatMessage(role="system", content=rendered),
            ChatMessage(role="assistant", content=result.content),
            ChatMessage(role="user", content=_rewrite_user_message(result.content, dropped)),
        ]
        try:
            reparsed, _ = await generate_structured(
                client,
                repair,
                response_model=PredictionBatch,
                temperature=template.temperature,
                max_tokens=4000,
                purpose="predict_generate",
                model_tier=template.model_tier,
            )
            meta["llm_calls"] += 1
            if reparsed is not None:
                valid, dropped = _validate_batch(
                    cast(PredictionBatch, reparsed).predictions,
                    require_evidence=True,
                    known_item_ids=known_item_ids,
                )
        except Exception as exc:  # 重写失败：保留第一轮结果，不中断
            log.warning("predict.rewrite_failed", error=repr(exc))

    for item in dropped:
        meta["dropped"].append(item)
        log.warning("predict.dropped", statement=item["statement"], problems=item["problems"])

    model = result.model or settings.llm.strong_model
    rows = [
        _to_prediction_row(
            d, day=day, model=model, prompt_version=template.version_hash, origin="llm"
        )
        for d in valid
    ]
    meta["generated"] = len(rows)
    log.info("predict.done", generated=len(rows), dropped=len(dropped))
    return PredictOutput(predictions=rows, meta=meta)


__all__ = ["PredictOutput", "generate_predictions"]
