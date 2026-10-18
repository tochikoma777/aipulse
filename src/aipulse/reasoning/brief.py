"""每日简报推演层（设计方案 §10.1）。

- 组装上下文：Top N 条目（含 hot_score / topic / 摘要）+ 主题 + 实体频次。
- 三档模式：
  - off：数据版简报（无 LLM，零网络）；hybrid：daily_brief（主编点评）；
  - full：daily_brief + 每条 item_comment（单条点评）。
- 任何 LLM 失败（网络 / 非法 JSON 降级）都回落到数据版简报，绝不中断流水线。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, cast

from sqlalchemy import func
from sqlmodel import Session, select

from aipulse.analysis.signals import item_signal_key
from aipulse.core.config import RunMode, Settings
from aipulse.core.logging import get_logger
from aipulse.core.timeutil import ensure_utc, utcnow
from aipulse.llm.base import ChatMessage, LLMClient, LLMResult
from aipulse.llm.prompt import load_prompt, render_prompt
from aipulse.llm.structured import generate_structured
from aipulse.schema.brief import (
    DailyBrief,
    EditorNote,
    EnhancesOut,
    ItemComment,
    ItemComments,
    OneLinersOut,
    OverviewBullet,
    Section,
)
from aipulse.store.models import Item, ItemEnhance, Signal, Topic
from aipulse.utils.text import estimate_tokens, truncate_summary

log = get_logger(__name__)

# 源 → 板块映射（off 档数据版简报用；LLM 档由模型自行归组）
_SOURCE_SECTION = {
    "github_trending": "开源项目",
    "arxiv": "论文与研究",
    "hf_papers": "论文与研究",
    "hackernews": "社区舆论",
    "reddit": "社区舆论",
    "rss": "产业与新闻",
    "inbox": "产业与新闻",
}

# 与 render/markdown.py 的图标体系保持一致（v1.14）
_SECTION_ICONS = {
    "开源项目": "🛠️",
    "论文与研究": "📄",
    "社区舆论": "💬",
    "产业与新闻": "🏢",
}

_MAX_CONTEXT_TOKENS = 12000


@dataclass
class BriefOutput:
    brief: DailyBrief
    items: dict[str, Item] = field(default_factory=dict)  # item_id → Item（渲染用）
    meta: dict[str, Any] = field(default_factory=dict)


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


def _topic_name_map(topics: list[Topic]) -> dict[str, str]:
    return {t.id: t.name for t in topics}


def _ensure_single_section(sections: list[Section], items: dict[str, Item]) -> None:
    """同一 item 只保留主板块（v1.16）。

    主板块由源决定（`_SOURCE_SECTION`），而不是"LLM 先写到哪个板块"——
    Apple 的 RSS 条目同时被放进社区舆论/产业与新闻时，应保留产业与新闻。
    源映射不存在或不在本次板块清单里时，退回它第一次出现的板块。
    """
    names = {section.name for section in sections}
    owners: dict[str, str] = {}
    order: list[str] = []
    for section in sections:
        for item_id in section.item_ids:
            if item_id in owners:
                continue
            item = items.get(item_id)
            primary = _SOURCE_SECTION.get(item.source) if item is not None else None
            owners[item_id] = primary if primary in names else section.name
            order.append(item_id)

    buckets: dict[str, list[str]] = {name: [] for name in names}
    for item_id in order:
        buckets[owners[item_id]].append(item_id)
    for section in sections:
        section.item_ids = buckets[section.name]


def _data_brief(
    items: list[Item],
    topics: list[Topic],
    entity_counts: dict[str, dict[str, Any]],
    day: date,
    sections: list[str],
) -> DailyBrief:
    """off 档 / 降级兜底：纯数据版简报（§8.5.3 的替代方案）。"""
    top = items[0] if items else None
    headline = top.title if top else "今日无数据"

    grouped: dict[str, list[str]] = {s: [] for s in sections}
    for it in items:
        grouped.setdefault(_SOURCE_SECTION.get(it.source, "其他"), []).append(it.id)

    section_models = [
        Section(name=s, item_ids=grouped.get(s, [])) for s in sections if grouped.get(s)
    ]

    # v1.14：总览必须分条（每条一个主题图标 + 小标题 + 一句话），不再挤成一整段
    bullets: list[OverviewBullet] = []
    for section in section_models:
        members = [it for it in items if it.id in set(section.item_ids)]
        if not members:
            continue
        best = max(members, key=lambda it: float(it.hot_score or 0.0))
        bullets.append(
            OverviewBullet(
                icon=_SECTION_ICONS.get(section.name, "🧩"),
                topic=section.name,
                text=f"{len(members)} 条；热度最高：{best.title}",
            )
        )

    top_entities = sorted(entity_counts.items(), key=lambda kv: -kv[1]["count"])[:10]
    source_counts: dict[str, int] = {}
    for it in items:
        source_counts[it.source] = source_counts.get(it.source, 0) + 1

    summary = (
        f"今日共采集 {len(items)} 条，覆盖 {len(topics)} 个主题、{len(source_counts)} 个来源；"
        + (f"热度最高：{headline}。" if top else "")
    )
    if not bullets:
        bullets = [OverviewBullet(icon="📭", topic="今日无数据", text=summary)]
    stats: dict[str, Any] = {
        "total_items": len(items),
        "topics": len(topics),
        "sources": source_counts,
        "top_entities": [
            {"name": n, "type": v["type"], "count": v["count"]} for n, v in top_entities
        ],
    }
    return DailyBrief(
        date=day,
        headline=headline,
        headline_item_id=top.id if top else "",
        overview_bullets=bullets,
        executive_summary=summary,
        sections=section_models,
        editor_note=EditorNote(core="off 档：未启用 LLM，本简报为数据版（无点评）。"),
        contradictions=[],
        underrated=[],
        comments=[],
        stats=stats,
    )


# ── M6b：条目增强（one_liner / why / stance）─────────────────────────
#
# 两个独立批量调用 + 条目级缓存 + 独立预算：
# - one_liner：要点（一律中文），由 `brief/item_comment.j2` 产出；
# - why / stance：为什么重要 / 立场，由 `brief/item_enhance.j2` 产出。
# 缓存键是**单条目**（item_id），不是批次——批次只是失败隔离与预算的控制单位。


def _render_ids(brief: DailyBrief, max_per_section: int) -> list[str]:
    """渲染层实际会展示的条目 id（板块顺序 → 板块内顺序，每板块截断）。

    必须与 `render/markdown.py` 的 `section.item_ids[:limit]` 严格一致：
    多算会为看不见的条目付费，少算会让表格出现 `—`。
    """
    limit = max(0, max_per_section)
    ordered: list[str] = []
    for section in brief.sections:
        for item_id in section.item_ids[:limit]:
            if item_id not in ordered:
                ordered.append(item_id)
    return ordered


def _signals_count(session: Session | None, item: Item) -> int:
    """该条目在 `signals` 表中的快照条数（无可追踪实体的条目恒为 0）。"""
    if session is None:
        return 0
    key = item_signal_key(item)
    if key is None:
        return 0
    entity_type, entity_key, _metric = key
    total = session.exec(
        select(func.count())
        .select_from(Signal)
        .where(Signal.entity_type == entity_type, Signal.entity_key == entity_key)
    ).one()
    return int(total or 0)


def _load_enhance_rows(session: Session | None, item_ids: Sequence[str]) -> dict[str, ItemEnhance]:
    if session is None or not item_ids:
        return {}
    rows = session.exec(
        select(ItemEnhance).where(ItemEnhance.item_id.in_(item_ids))  # type: ignore[attr-defined]
    ).all()
    return {row.item_id: row for row in rows}


def _cache_fresh(
    row: ItemEnhance,
    item: Item,
    *,
    settings: Settings,
    one_liner_ver: str,
    enhance_ver: str,
    signals_count: int,
    now: datetime,
    require_fields: bool = False,
) -> bool:
    """条目级缓存判定（红线 23）：四条全满足才算命中。

    `require_fields=True`（hybrid 档）额外要求三个文本字段都非空——
    否则"版本号对得上但 why 为空"会被误判为命中，缺口永远补不上。
    """
    if require_fields and not (row.one_liner.strip() and row.why.strip() and row.stance.strip()):
        return False
    if row.content_hash != (item.content_hash or ""):
        return False
    if row.one_liner_ver != one_liner_ver or row.enhance_ver != enhance_ver:
        return False
    if row.updated_at is None:
        return False
    if now - ensure_utc(row.updated_at) > timedelta(days=settings.brief.enhance_ttl_days):
        return False
    if (
        abs(float(item.hot_score or 0.0) - float(row.last_hot_score or 0.0))
        >= settings.brief.enhance_refresh_hot_delta
    ):
        return False
    return not (
        settings.brief.enhance_refresh_on_new_signals and row.signals_count != signals_count
    )


def _call_cost(settings: Settings, *, model_tier: str, result: LLMResult | None) -> float:
    """本地估算单次调用成本（与 BudgetTracker 同一单价口径）。"""
    if result is None or result.cached:
        return 0.0
    price = (
        settings.budget.price_strong_cny_per_1m
        if model_tier == "strong"
        else settings.budget.price_fast_cny_per_1m
    )
    return (result.prompt_tokens + result.completion_tokens) * price / 1_000_000


async def _enhance_one_batch(
    client: LLMClient,
    items: Sequence[Item],
    settings: Settings,
) -> tuple[dict[str, str], dict[str, tuple[str, str]], float, str, list[str]]:
    """单批两次调用。返回 (one_liners, why/stance, cost, model, failures)。

    任何一次调用失败只记入 `failures`，**不抛异常**——批次是失败隔离的最小单位。
    """
    contexts = [
        {
            "id": it.id,
            "title": it.title,
            "source": it.source,
            "summary": truncate_summary(it.summary or "", 300),
        }
        for it in items
    ]
    payload = json.dumps(contexts, ensure_ascii=False)
    item_count = len(contexts)
    # 输出预算按批大小给：老版本硬编码 3000 会让 30 条的批注定截断。
    max_tokens = max(1200, item_count * 150)
    valid_ids = {it.id for it in items}

    one_liners: dict[str, str] = {}
    whys: dict[str, tuple[str, str]] = {}
    failures: list[str] = []
    cost = 0.0
    model = ""

    rendered, template = render_prompt(
        "brief/item_comment", items_json=payload, item_count=item_count
    )
    parsed, result = await generate_structured(
        client,
        [ChatMessage(role="system", content=rendered)],
        response_model=OneLinersOut,
        temperature=template.temperature,
        max_tokens=max_tokens,
        purpose="brief_item_comment",
        model_tier=template.model_tier,
    )
    cost += _call_cost(settings, model_tier=template.model_tier, result=result)
    if result is not None and result.model:
        model = result.model
    if isinstance(parsed, OneLinersOut):
        for liner in parsed.one_liners:
            if liner.item_id in valid_ids:
                one_liners[liner.item_id] = liner.one_liner
    else:
        failures.append("one_liner")

    rendered, template = render_prompt(
        "brief/item_enhance", items_json=payload, item_count=item_count
    )
    parsed, result = await generate_structured(
        client,
        [ChatMessage(role="system", content=rendered)],
        response_model=EnhancesOut,
        temperature=template.temperature,
        max_tokens=max_tokens,
        purpose="brief_item_enhance",
        model_tier=template.model_tier,
    )
    cost += _call_cost(settings, model_tier=template.model_tier, result=result)
    if result is not None and result.model:
        model = result.model
    if isinstance(parsed, EnhancesOut):
        for enh in parsed.comments:
            if enh.item_id in valid_ids:
                whys[enh.item_id] = (enh.why, enh.stance)
    else:
        failures.append("why_stance")

    return one_liners, whys, cost, model, failures


def _write_enhance(
    session: Session,
    item: Item,
    *,
    one_liner: str | None,
    why: str | None,
    stance: str | None,
    one_liner_ver: str,
    enhance_ver: str,
    signals_count: int,
    model: str,
    now: datetime,
) -> None:
    """写一行 item_enhance：只有拿到的字段才更新，另一路保留旧值。"""
    row = session.get(ItemEnhance, item.id)
    if row is None:
        row = ItemEnhance(item_id=item.id, created_at=now)
    if one_liner is not None:
        row.one_liner = one_liner
        row.one_liner_ver = one_liner_ver
    if why is not None:
        row.why = why
        row.stance = stance or ""
        row.enhance_ver = enhance_ver
    row.content_hash = item.content_hash or ""
    row.last_hot_score = float(item.hot_score or 0.0)
    row.signals_count = signals_count
    if model:
        row.model = model
    row.updated_at = now
    session.add(row)


async def _enhance_comments(
    *,
    client: LLMClient,
    session: Session | None,
    settings: Settings,
    brief: DailyBrief,
    items: dict[str, Item],
    mode: RunMode,
    meta: dict[str, Any],
) -> list[ItemComment]:
    """为**渲染集**产出 comments。三档语义（S4.0，挂既有 mode，无新开关）：

    - **off**：不调用 LLM，只读 `item_enhance` 表；读不到就留空（零花费）。
    - **hybrid（生产默认）**：只补缺失——渲染集中**尚无 one_liner / why / stance**
      的条目才调用；已有完整值的条目走缓存，允许跨日收敛到全覆盖。
    - **full**：强制全刷——**忽略缓存**，渲染集全部重算（换 prompt / 改模型后的一致性重跑）。

    hybrid 与 full 的差异是「认不认缓存」，不是「做不做增强」；两档都以全覆盖为目标。
    另外：单批失败只丢该批并标 degraded，其余批照常产出；
    超 `brief.enhance_budget_cny` 立即停止后续批次，已完成的保留。
    """
    render_ids = _render_ids(brief, settings.brief.max_items_per_section)
    # 成本闸门：enhance_top_n 只决定"增强多少条"，不参与"渲染哪些条"。
    render_ids = render_ids[: max(0, settings.brief.enhance_top_n)]
    if not render_ids or session is None:
        return []

    rows = _load_enhance_rows(session, render_ids)
    # off 档且库里一条可复用值都没有 → 不必读 prompt。
    # （测试里改 AIPULSE_ROOT 后 prompts/ 不在该 root 下，off 档不该因此崩。）
    if mode == RunMode.OFF and not rows:
        return []

    one_liner_ver = load_prompt("brief/item_comment").version_hash
    enhance_ver = load_prompt("brief/item_enhance").version_hash
    now = utcnow()

    cached: dict[str, ItemComment] = {}
    missing: list[Item] = []
    signals_counts: dict[str, int] = {}
    # full：忽略缓存，渲染集全部重算；hybrid / off：按条目级缓存判定。
    for item_id in render_ids:
        item = items.get(item_id)
        if item is None:
            continue
        signals_count = (
            _signals_count(session, item) if settings.brief.enhance_refresh_on_new_signals else 0
        )
        signals_counts[item_id] = signals_count
        if mode == RunMode.FULL:
            missing.append(item)
            continue
        row = rows.get(item_id)
        if row is not None and _cache_fresh(
            row,
            item,
            settings=settings,
            one_liner_ver=one_liner_ver,
            enhance_ver=enhance_ver,
            signals_count=signals_count,
            now=now,
            require_fields=(mode == RunMode.HYBRID),
        ):
            cached[item_id] = ItemComment(
                item_id=item_id,
                one_liner=row.one_liner,
                why=row.why,
                stance=row.stance,
            )
        else:
            missing.append(item)

    one_liners: dict[str, str] = {}
    whys: dict[str, tuple[str, str]] = {}
    spent = 0.0
    if missing and mode != RunMode.OFF and session is not None:
        batch_size = max(1, settings.brief.enhance_batch_size)
        for start in range(0, len(missing), batch_size):
            if spent >= settings.brief.enhance_budget_cny:
                log.warning(
                    "brief.enhance_budget_exhausted",
                    spent=round(spent, 4),
                    limit=settings.brief.enhance_budget_cny,
                )
                break
            batch = missing[start : start + batch_size]
            try:
                got_liners, got_whys, cost, model, failures = await _enhance_one_batch(
                    client, batch, settings
                )
            except Exception as exc:  # 网络/预算异常：丢该批，不拖垮日报
                log.warning("brief.enhance_batch_failed", error=repr(exc))
                meta["degraded"] = True
                meta.setdefault("degraded_reason", f"增强批次失败：{type(exc).__name__}")
                continue
            spent += cost
            one_liners.update(got_liners)
            whys.update(got_whys)
            if failures:
                meta["degraded"] = True
                meta.setdefault("degraded_reason", "增强调用失败：" + "、".join(failures))
            if session is not None:
                for item in batch:
                    pair = got_whys.get(item.id)
                    _write_enhance(
                        session,
                        item,
                        one_liner=got_liners.get(item.id),
                        why=pair[0] if pair else None,
                        stance=pair[1] if pair else None,
                        one_liner_ver=one_liner_ver,
                        enhance_ver=enhance_ver,
                        signals_count=signals_counts.get(item.id, 0),
                        model=model,
                        now=now,
                    )
                session.commit()

    merged: list[ItemComment] = []
    for item_id in render_ids:
        if item_id in cached:
            merged.append(cached[item_id])
            continue
        if item_id not in items:
            continue
        pair = whys.get(item_id)
        merged.append(
            ItemComment(
                item_id=item_id,
                one_liner=one_liners.get(item_id, ""),
                why=pair[0] if pair else "",
                stance=pair[1] if pair else "",
            )
        )

    total = sum(1 for item_id in render_ids if item_id in items)
    enhanced = sum(1 for comment in merged if comment.why.strip() and comment.stance.strip())
    meta.update(
        {
            "enhance_total": total,
            "enhanced": enhanced,
            "enhance_skipped_count": total - enhanced,
            "enhance_cache_hit": len(cached),
            "enhance_cost_cny": round(spent, 6),
        }
    )
    return merged


async def generate_brief(
    *,
    client: LLMClient,
    settings: Settings,
    items: list[Item],
    topics: list[Topic],
    entity_counts: dict[str, dict[str, Any]],
    day: date,
    mode: RunMode,
    skip_llm: bool = False,
    top_n: int | None = None,
    session: Session | None = None,
) -> BriefOutput:
    """生成每日简报。返回 BriefOutput（brief + 渲染用的 items + meta）。"""
    top_n = int(top_n) if top_n is not None else int(settings.pipeline.daily_top_n)
    sections = list(settings.pipeline.brief_sections)
    topic_names = _topic_name_map(topics)

    # 按热度排序，取 Top N
    ranked = sorted(items, key=lambda it: -(float(it.hot_score or 0.0)))[:top_n]
    contexts = _trim_to_budget(
        [_item_context(it, topic_names.get(it.topic_id or "")) for it in ranked]
    )
    chosen_ids = [c["id"] for c in contexts]
    chosen_items = {it.id: it for it in ranked if it.id in chosen_ids}
    ordered_items = [chosen_items[cid] for cid in chosen_ids]

    if mode == RunMode.OFF or skip_llm:
        off_brief = _data_brief(ordered_items, topics, entity_counts, day, sections)
        # S3.6：off 档不发任何请求，只回读 item_enhance 里已有的值（读不到就留空）。
        off_brief.comments = await _enhance_comments(
            client=client,
            session=session,
            settings=settings,
            brief=off_brief,
            items=chosen_items,
            mode=RunMode.OFF,
            meta={"mode": "off"},
        )
        return BriefOutput(brief=off_brief, items=chosen_items, meta={"mode": "off"})

    # ── hybrid / full：调 LLM ──────────────────────────────────────
    meta: dict[str, Any] = {"mode": mode.value, "degraded": False, "llm_calls": 0}
    brief: DailyBrief | None = None
    try:
        rendered, template = render_prompt(
            "brief/daily_brief",
            items_json=json.dumps(contexts, ensure_ascii=False),
            entities_json=json.dumps(
                [
                    {"name": n, "type": v["type"], "count": v["count"]}
                    for n, v in sorted(entity_counts.items(), key=lambda kv: -kv[1]["count"])[:20]
                ],
                ensure_ascii=False,
            ),
            sections_json=json.dumps(sections, ensure_ascii=False),
        )
        parsed, _ = await generate_structured(
            client,
            [ChatMessage(role="system", content=rendered)],
            response_model=DailyBrief,
            temperature=template.temperature,
            max_tokens=settings.llm.max_tokens_for(template.model_tier),
            purpose="brief_daily",
            model_tier=template.model_tier,
        )
        meta["llm_calls"] += 1
        if parsed is not None:
            daily = cast(DailyBrief, parsed)
            daily.date = day
            # v1.16：LLM 可能把同一条同时放进多个板块 → 按源归一到主板块
            _ensure_single_section(daily.sections, chosen_items)
            brief = daily
    except Exception as exc:  # 网络/预算等异常：降级不中断
        log.error("brief.llm_failed", error=repr(exc))
        meta["degraded"] = True
        meta["degraded_reason"] = f"LLM 调用失败：{type(exc).__name__}"

    if brief is None:
        brief = _data_brief(ordered_items, topics, entity_counts, day, sections)
        meta["degraded"] = True
        meta.setdefault("degraded_reason", "LLM 结构化输出失败，已降级为数据版")

    # ── M6b：条目增强（hybrid / full）──────────────────────────────
    # 只覆盖渲染集（sections 截断后），两次调用分字段产出，条目级缓存复用。
    if session is not None:
        brief.comments = await _enhance_comments(
            client=client,
            session=session,
            settings=settings,
            brief=brief,
            items=chosen_items,
            mode=mode,
            meta=meta,
        )

    return BriefOutput(brief=brief, items=chosen_items, meta=meta)


async def _item_comments(
    client: LLMClient, items: list[Item], meta: dict[str, Any]
) -> list[ItemComment]:
    """full 档：对 Top N 条目生成单条点评（一条批量调用）。"""
    contexts = [
        {
            "id": it.id,
            "title": it.title,
            "source": it.source,
            "summary": truncate_summary(it.summary or "", 300),
        }
        for it in items
    ]
    rendered, template = render_prompt(
        "brief/item_comment",
        items_json=json.dumps(contexts, ensure_ascii=False),
    )
    parsed, _ = await generate_structured(
        client,
        [ChatMessage(role="system", content=rendered)],
        response_model=ItemComments,
        temperature=template.temperature,
        max_tokens=3000,
        purpose="brief_item_comment",
        model_tier=template.model_tier,
    )
    meta["llm_calls"] += 1
    if parsed is None:
        return []
    return cast(ItemComments, parsed).comments


__all__ = ["BriefOutput", "generate_brief"]
