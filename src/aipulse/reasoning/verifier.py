"""到期验证（设计方案 §10.2.2 / §10.2.3 v1.9，M3b）。

双路径：
1. **量化判据**（`prediction.criteria` 非空）→ 查 `signals` / `entities` / `items` **直接判定**，
   零 LLM（off 档闭环的基础，设计方案 §11.5）。
2. **语义判据**（无 criteria）→ 证据检索 → 充分度门槛 → LLM 按 `prompts/predict/verify.j2`
   判定 `hit` / `partial` / `miss`。

铁律（v1.9，违反即返工）：
- `unverifiable` **只由系统的证据门槛产生**，LLM 不得输出该值（否则成为逃避 miss 的软出口）。
- 证据不足 → **不调用 LLM**，走 grace（保留 pending ≤ grace_days）或转 `unverifiable`。
- LLM 调用失败 → 保持 `pending`，**绝不**当 miss。
- miss 的前提是"证据覆盖已充分"：查不到 ≠ 没发生。
"""

from __future__ import annotations

import ast
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlmodel import Session

from aipulse.analysis.cluster import tokenize
from aipulse.analysis.entities import extract_entities
from aipulse.core.config import RunMode, Settings, VerifySettings
from aipulse.core.logging import get_logger
from aipulse.llm.base import ChatMessage, LLMClient
from aipulse.llm.prompt import render_prompt
from aipulse.llm.structured import generate_structured
from aipulse.schema.prediction import Verdict
from aipulse.store.models import Item, Prediction, Topic
from aipulse.store.repo_items import (
    count_entities_in_range,
    items_by_source,
    list_items,
    signal_first_seen_map,
    signals_for_entity,
    signals_max_value,
)
from aipulse.store.repo_predictions import list_pending_due, save_verdict
from aipulse.utils.text import estimate_tokens, truncate_summary

log = get_logger(__name__)

# verdict → 分数（设计方案 §7.5 / §10.2.3）
VERDICT_SCORES: dict[str, float] = {"hit": 1.0, "partial": 0.5, "miss": 0.0}


# ── 数据结构 ─────────────────────────────────────────────────────────


@dataclass
class CriterionOutcome:
    """量化判据的判定结果。`determined=False` 表示**覆盖不足**（不是 miss）。"""

    determined: bool
    verdict: str | None  # hit / partial / miss
    score: float | None
    note: str
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class EvidenceHit:
    item: Item
    cosine: float
    relevance: float


@dataclass
class EvidenceResult:
    hits: list[EvidenceHit]
    sufficient: bool
    generation_items: list[Item]
    window_start: datetime
    window_end: datetime


@dataclass
class _Decision:
    """单条预言的判定决策（尚未写库）。"""

    status: str  # verified | unverifiable | deferred | failed
    verdict: str | None = None
    note: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    source: str = "semantic"  # quantified | semantic | gate
    llm_calls: int = 0


@dataclass
class VerifyOutcome:
    day: date
    verified: int = 0
    unverifiable: int = 0
    deferred: int = 0
    failed: int = 0
    llm_calls: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


# ── 时间窗 ───────────────────────────────────────────────────────────


def _evidence_window(pred: Prediction, cfg: VerifySettings) -> tuple[datetime, datetime]:
    """判定窗口 `[生成日 00:00, due_date + 宽限 23:59:59]`（设计方案 §10.2.2 v1.9）。"""
    start = datetime.combine(pred.date, time.min, tzinfo=UTC)
    end_day = pred.due_date + timedelta(days=cfg.evidence_window_grace_days)
    end = datetime.combine(end_day, time.max, tzinfo=UTC)
    return start, end


def _day_bounds(since_day: date, until_day: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(since_day, time.min, tzinfo=UTC),
        datetime.combine(until_day, time.max, tzinfo=UTC),
    )


# ── 小工具 ───────────────────────────────────────────────────────────


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _contains(item: Item, keyword: str) -> bool:
    kw = (keyword or "").strip().lower()
    if not kw:
        return True
    haystack = f"{item.title or ''} {item.summary or ''}".lower()
    return kw in haystack


def _undetermined(note: str) -> CriterionOutcome:
    return CriterionOutcome(determined=False, verdict=None, score=None, note=note)


def _outcome(verdict: str, note: str, evidence_ids: list[str] | None = None) -> CriterionOutcome:
    score = VERDICT_SCORES[verdict]
    return CriterionOutcome(
        determined=True,
        verdict=verdict,
        score=score,
        note=note,
        evidence_ids=list(evidence_ids or []),
    )


def _threshold_verdict(value: float, threshold: float, tolerance: float) -> str:
    """阈值型判据：达标 hit / 容差带 partial / 否则 miss。"""
    if value >= threshold:
        return "hit"
    if threshold > 0 and value >= threshold * (1.0 - tolerance):
        return "partial"
    return "miss"


# ── 量化判据：6 个模板（严禁调 LLM）──────────────────────────────────


def _judge_github_new_repo(
    session: Session,
    pred: Prediction,
    params: dict[str, Any],
    cfg: VerifySettings,
    window: tuple[datetime, datetime],
) -> CriterionOutcome:
    owner = str(params.get("owner", "")).strip().rstrip("/")
    if not owner:
        return _undetermined("github_new_repo 缺 owner 参数")
    first_seen = signal_first_seen_map(session, entity_type="repo", key_prefix=f"{owner}/")
    if not first_seen:
        return _undetermined(f"库中无 owner={owner} 的任何 repo 观测，覆盖不足")
    since, until = window
    new_repos = sorted(k for k, ts in first_seen.items() if since <= ts <= until)
    if new_repos:
        sample = ", ".join(new_repos[:5])
        return _outcome("hit", f"窗口内出现 {len(new_repos)} 个新仓库：{sample}")
    return _outcome("miss", f"窗口内 {owner} 无新仓库（已有观测 {len(first_seen)} 个）")


def _judge_github_stars_reach(
    session: Session,
    pred: Prediction,
    params: dict[str, Any],
    cfg: VerifySettings,
    window: tuple[datetime, datetime],
) -> CriterionOutcome:
    repo = str(params.get("repo", "")).strip()
    threshold = _to_float(params.get("threshold"))
    if not repo or threshold is None:
        return _undetermined("github_stars_reach 需要 repo 与 threshold 参数")
    since, until = window
    value = signals_max_value(
        session, entity_type="repo", entity_key=repo, metric="stars", since=since, until=until
    )
    evidence: list[str] = []
    if value is None:
        # 退路：从窗口内的 github 条目 metric 里取
        items = items_by_source(session, source="github_trending", since=since, until=until)
        matched = [it for it in items if (it.external_id or "") == repo]
        raw_values = [it.metrics.get("stars_total") for it in matched]
        values = [float(v) for v in raw_values if v is not None]
        if values:
            value = max(values)
            evidence = [matched[0].id]
        elif signals_for_entity(session, "repo", repo, "stars"):
            # 有过历史观测但窗口内没有 → 窗口内无法核实
            return _undetermined(f"repo={repo} 窗口内无 star 观测，无法核实")
        else:
            return _undetermined(f"库中无 repo={repo} 的任何 star 观测，覆盖不足")
    verdict = _threshold_verdict(value, threshold, cfg.partial_tolerance)
    note = f"repo={repo} 窗口内最大 stars={value:.0f}，阈值 {threshold:.0f}"
    return _outcome(verdict, note, evidence)


def _judge_hn_story_points(
    session: Session,
    pred: Prediction,
    params: dict[str, Any],
    cfg: VerifySettings,
    window: tuple[datetime, datetime],
) -> CriterionOutcome:
    keyword = str(params.get("keyword", "")).strip()
    threshold = _to_float(params.get("threshold"))
    if not keyword or threshold is None:
        return _undetermined("hn_story_points 需要 keyword 与 threshold 参数")
    since, until = window
    hn_items = items_by_source(session, source="hackernews", since=since, until=until)
    if not hn_items:
        return _undetermined("窗口内无 HN 条目，覆盖不足")
    matched = [it for it in hn_items if _contains(it, keyword)]
    if not matched:
        return _outcome("miss", f"窗口内 {len(hn_items)} 条 HN 条目均不含关键词 {keyword!r}")
    best = max(matched, key=lambda it: float(it.metrics.get("points") or 0))
    points = float(best.metrics.get("points") or 0)
    verdict = _threshold_verdict(points, threshold, cfg.partial_tolerance)
    note = f"HN 关键词 {keyword!r} 最高 points={points:.0f}（阈值 {threshold:.0f}）"
    return _outcome(verdict, note, [best.id])


def _judge_entity_mentions(
    session: Session,
    pred: Prediction,
    params: dict[str, Any],
    cfg: VerifySettings,
    window: tuple[datetime, datetime],
) -> CriterionOutcome:
    entity = str(params.get("entity", "")).strip()
    threshold = _to_float(params.get("threshold"))
    window_days = _to_int(params.get("window_days")) or 7
    if not entity or threshold is None:
        return _undetermined("entity_mentions 需要 entity 与 threshold 参数")
    until_day = pred.due_date
    since_day = until_day - timedelta(days=max(1, window_days) - 1)
    total = count_entities_in_range(session, since_day=since_day, until_day=until_day)
    if total == 0:
        return _undetermined(f"{since_day}~{until_day} 窗口内无任何实体记录，覆盖不足")
    count = count_entities_in_range(session, since_day=since_day, until_day=until_day, name=entity)
    verdict = _threshold_verdict(float(count), threshold, cfg.partial_tolerance)
    note = f"实体 {entity!r} 在 {since_day}~{until_day} 提及 {count} 次（阈值 {threshold:.0f}）"
    return _outcome(verdict, note)


def _judge_arxiv_paper_count(
    session: Session,
    pred: Prediction,
    params: dict[str, Any],
    cfg: VerifySettings,
    window: tuple[datetime, datetime],
) -> CriterionOutcome:
    keyword = str(params.get("keyword", "")).strip()
    threshold = _to_float(params.get("threshold"))
    window_days = _to_int(params.get("window_days")) or 7
    if not keyword or threshold is None:
        return _undetermined("arxiv_paper_count 需要 keyword 与 threshold 参数")
    until_day = pred.due_date
    since_day = until_day - timedelta(days=max(1, window_days) - 1)
    start_dt, end_dt = _day_bounds(since_day, until_day)
    papers = items_by_source(session, source="arxiv", since=start_dt, until=end_dt)
    if not papers:
        return _undetermined(f"{since_day}~{until_day} 窗口内无 arXiv 条目，覆盖不足")
    matched = [it for it in papers if _contains(it, keyword)]
    verdict = _threshold_verdict(float(len(matched)), threshold, cfg.partial_tolerance)
    note = (
        f"arXiv 关键词 {keyword!r} 在 {since_day}~{until_day} "
        f"命中 {len(matched)} 篇（阈值 {threshold:.0f}）"
    )
    return _outcome(verdict, note, [it.id for it in matched[:5]])


_CriteriaHandler = Callable[
    [Session, Prediction, dict[str, Any], VerifySettings, tuple[datetime, datetime]],
    CriterionOutcome,
]

_CRITERIA_HANDLERS: dict[str, _CriteriaHandler] = {
    "github_new_repo": _judge_github_new_repo,
    "github_stars_reach": _judge_github_stars_reach,
    "hn_story_points": _judge_hn_story_points,
    "entity_mentions": _judge_entity_mentions,
    "arxiv_paper_count": _judge_arxiv_paper_count,
}


# ── custom 判据：受限表达式求值（不用 eval，白名单 AST）───────────────


class _CustomError(Exception):
    """custom 表达式不合法（非致命：回退为覆盖不足）。"""


_CUSTOM_FUNCS: dict[str, tuple[str, set[str]]] = {
    "new_repo": ("github_new_repo", {"owner"}),
    "stars": ("github_stars_reach", {"repo", "threshold"}),
    "points": ("hn_story_points", {"keyword", "threshold"}),
    "mentions": ("entity_mentions", {"entity", "threshold", "window_days"}),
    "papers": ("arxiv_paper_count", {"keyword", "threshold", "window_days"}),
}


@dataclass
class _CustomCtx:
    session: Session
    pred: Prediction
    cfg: VerifySettings
    window: tuple[datetime, datetime]


def _as_bool(outcome: CriterionOutcome) -> bool | None:
    if not outcome.determined:
        return None
    return outcome.verdict in ("hit", "partial")


def _eval_custom_node(node: ast.AST, ctx: _CustomCtx) -> tuple[bool | None, list[str], list[str]]:
    if isinstance(node, ast.BoolOp):
        results = [_eval_custom_node(v, ctx) for v in node.values]
        vals = [r[0] for r in results]
        notes = [n for r in results for n in r[1]]
        evidence = [e for r in results for e in r[2]]
        if isinstance(node.op, ast.And):
            if any(v is False for v in vals):
                return False, notes, evidence
            if any(v is None for v in vals):
                return None, notes, evidence
            return True, notes, evidence
        if isinstance(node.op, ast.Or):
            if any(v is True for v in vals):
                return True, notes, evidence
            if any(v is None for v in vals):
                return None, notes, evidence
            return False, notes, evidence
        raise _CustomError("不支持的布尔运算")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        val, notes, evidence = _eval_custom_node(node.operand, ctx)
        return (None if val is None else (not val)), notes, evidence
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return _eval_custom_call(node, ctx)
    raise _CustomError(f"不支持的表达式节点：{type(node).__name__}")


def _eval_custom_call(node: ast.Call, ctx: _CustomCtx) -> tuple[bool | None, list[str], list[str]]:
    assert isinstance(node.func, ast.Name)
    name = node.func.id
    spec = _CUSTOM_FUNCS.get(name)
    if spec is None:
        raise _CustomError(f"未知函数 {name!r}")
    if node.args:
        raise _CustomError(f"{name} 只接受关键字参数")
    handler_name, allowed = spec
    kwargs: dict[str, Any] = {}
    for kw in node.keywords:
        if kw.arg is None:
            raise _CustomError(f"{name} 不支持 **kwargs")
        if kw.arg not in allowed:
            raise _CustomError(f"{name} 不支持的参数 {kw.arg!r}")
        if not isinstance(kw.value, ast.Constant):
            raise _CustomError(f"{name}.{kw.arg} 必须是字面量")
        kwargs[kw.arg] = kw.value.value
    handler = _CRITERIA_HANDLERS[handler_name]
    outcome: CriterionOutcome = handler(ctx.session, ctx.pred, kwargs, ctx.cfg, ctx.window)
    return _as_bool(outcome), [outcome.note], list(outcome.evidence_ids)


def _judge_custom(
    session: Session,
    pred: Prediction,
    params: dict[str, Any],
    cfg: VerifySettings,
    window: tuple[datetime, datetime],
) -> CriterionOutcome:
    expr = str(params.get("expr", "")).strip()
    if not expr:
        return _undetermined("custom 缺 expr 参数")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        return _undetermined(f"custom 表达式语法错误：{exc.msg}")
    ctx = _CustomCtx(session=session, pred=pred, cfg=cfg, window=window)
    try:
        value, notes, evidence = _eval_custom_node(tree.body, ctx)
    except _CustomError as exc:
        return _undetermined(f"custom 表达式无法求值：{exc}")
    detail = "；".join(n for n in notes if n)
    if value is None:
        return _undetermined(f"custom 表达式覆盖不足：{expr}（{detail}）")
    verdict = "hit" if value else "miss"
    return _outcome(verdict, f"custom 表达式 {expr} → {value}（{detail}）", evidence)


def judge_criteria(
    session: Session, pred: Prediction, cfg: VerifySettings
) -> CriterionOutcome | None:
    """量化判据判定。无 criteria 返回 None；未知模板也返回 None（由调用方回退语义路径）。"""
    name = pred.criteria
    if not name:
        return None
    params = dict(pred.criteria_params or {})
    window = _evidence_window(pred, cfg)
    if name == "custom":
        return _judge_custom(session, pred, params, cfg, window)
    handler = _CRITERIA_HANDLERS.get(name)
    if handler is None:
        return None
    return handler(session, pred, params, cfg, window)


# ── 语义路径：证据检索 ───────────────────────────────────────────────


def _topic_texts(session: Session, items: list[Item]) -> list[str]:
    texts: list[str] = []
    for item in items:
        if not item.topic_id:
            continue
        topic = session.get(Topic, item.topic_id)
        if topic is None:
            continue
        texts.append(f"{topic.name or ''} {' '.join(topic.keywords or [])}")
    return texts


def _build_query(pred: Prediction, gen_items: list[Item], topic_texts: list[str]) -> str:
    """按字段权重拼查询文档并分词（设计方案 §3.2）。"""
    parts: list[str] = [pred.statement] * 3 + [pred.falsifiable_criteria] * 3
    if pred.rationale:
        parts.append(pred.rationale)
    for item in gen_items:
        if item.title:
            parts += [item.title, item.title]
        if item.tags:
            parts += [", ".join(item.tags)] * 2
    for text in topic_texts:
        parts += [text, text]
    entity_text = f"{pred.statement} {pred.falsifiable_criteria} {pred.rationale}"
    for ent_name, _etype in extract_entities(entity_text):
        parts += [ent_name, ent_name]
    return tokenize(" ".join(p for p in parts if p))


def _generation_items(session: Session, pred: Prediction) -> list[Item]:
    items: list[Item] = []
    for item_id in pred.evidence_item_ids or []:
        item = session.get(Item, item_id)
        if item is not None:
            items.append(item)
    return items


def retrieve_evidence(session: Session, pred: Prediction, settings: Settings) -> EvidenceResult:
    """检索到期窗口内的证据并按相关度排序（设计方案 §3.3 / §3.4）。"""
    cfg = settings.verify
    since, until = _evidence_window(pred, cfg)
    gen_items = _generation_items(session, pred)
    query = _build_query(pred, gen_items, _topic_texts(session, gen_items))

    candidates = list_items(session, since=since, until=until)
    if not query or not candidates:
        return EvidenceResult([], False, gen_items, since, until)

    corpus = [query] + [f"{it.title or ''} {it.summary or ''}"[:1500] for it in candidates]
    vectorizer = TfidfVectorizer(max_features=20000)
    matrix = vectorizer.fit_transform(corpus)
    sims = cosine_similarity(matrix[0:1], matrix[1:]).ravel()

    scored: list[EvidenceHit] = []
    for item, cosine in zip(candidates, sims, strict=True):
        cos = float(cosine)
        if cos < cfg.similarity_threshold:
            continue
        relevance = 0.7 * cos + 0.3 * min(float(item.hot_score or 0.0) / 100.0, 1.0)
        scored.append(EvidenceHit(item=item, cosine=cos, relevance=relevance))
    scored.sort(key=lambda h: (-h.relevance, -h.cosine))

    max_cos = max((h.cosine for h in scored), default=0.0)
    sufficient = len(scored) >= cfg.min_evidence or max_cos >= cfg.strong_similarity
    hits = scored[: cfg.evidence_top_k]
    return EvidenceResult(hits, sufficient, gen_items, since, until)


def _evidence_payload(hits: list[EvidenceHit], cfg: VerifySettings) -> list[dict[str, Any]]:
    """把命中证据转成注入 prompt 的 JSON（带 token 预算裁剪，从尾部丢弃）。"""
    payload: list[dict[str, Any]] = []
    total = 0
    for hit in hits:
        entry = {
            "id": hit.item.id,
            "title": hit.item.title,
            "source": hit.item.source,
            "published_at": hit.item.published_at.isoformat() if hit.item.published_at else None,
            "relevance": round(hit.relevance, 3),
            "summary": truncate_summary(hit.item.summary or "", 300),
        }
        total += estimate_tokens(json.dumps(entry, ensure_ascii=False))
        if total > cfg.max_context_tokens:
            break
        payload.append(entry)
    return payload


async def _llm_verdict(
    client: LLMClient, pred: Prediction, evidence: EvidenceResult, cfg: VerifySettings
) -> tuple[Verdict | None, int]:
    """调用 `verify.j2` 做三值判定。返回 (Verdict | None, llm_calls)。"""
    payload = _evidence_payload(evidence.hits, cfg)
    rendered, template = render_prompt(
        "predict/verify",
        generated_date=pred.date.isoformat(),
        due_date=pred.due_date.isoformat(),
        horizon_days=pred.horizon_days,
        window_start=evidence.window_start.date().isoformat(),
        window_end=evidence.window_end.date().isoformat(),
        category=pred.category,
        confidence=pred.confidence,
        statement=pred.statement,
        falsifiable_criteria=pred.falsifiable_criteria,
        rationale=pred.rationale,
        criteria=pred.criteria,
        criteria_params=pred.criteria_params,
        evidence_count=len(payload),
        evidence_json=json.dumps(payload, ensure_ascii=False, indent=2),
    )
    try:
        parsed, _result = await generate_structured(
            client,
            [ChatMessage(role="system", content=rendered)],
            response_model=Verdict,
            temperature=template.temperature,
            max_tokens=1200,
            purpose=template.purpose,
            model_tier=template.model_tier,
        )
    except Exception as exc:  # 网络/预算异常：保持 pending，绝不写 miss
        log.error("verify.llm_failed", error=repr(exc))
        return None, 0
    if parsed is None:
        return None, 1
    return cast(Verdict, parsed), 1


# ── 单条判定与编排 ───────────────────────────────────────────────────


def _insufficient(
    pred: Prediction, cfg: VerifySettings, today: date, note: str, *, source: str
) -> _Decision:
    if today <= pred.due_date + timedelta(days=cfg.grace_days):
        return _Decision(
            status="deferred",
            note=f"{note}；仍在 {cfg.grace_days} 天宽限期内，保持 pending",
            source=source,
        )
    return _Decision(
        status="unverifiable",
        note=f"{note}；宽限期已过，标记 unverifiable",
        source=source,
    )


async def _verify_one(
    session: Session,
    pred: Prediction,
    *,
    client: LLMClient,
    settings: Settings,
    mode: RunMode,
    today: date,
) -> _Decision:
    cfg = settings.verify
    # ── 路径 1：量化判据（零 LLM）──
    if pred.criteria:
        outcome = judge_criteria(session, pred, cfg)
        if outcome is not None:
            if outcome.determined:
                return _Decision(
                    status="verified",
                    verdict=outcome.verdict,
                    note=outcome.note,
                    evidence_ids=list(outcome.evidence_ids),
                    source="quantified",
                )
            return _insufficient(pred, cfg, today, outcome.note, source="quantified")
        # 未知模板 → 回退语义路径（记录，便于排查配置漂移）
        log.warning("verify.unknown_criteria", prediction=pred.id, criteria=pred.criteria)

    # ── 路径 2：语义判据 ──
    if mode == RunMode.OFF:
        return _insufficient(pred, cfg, today, "off 档不做 LLM 语义判定", source="gate")
    evidence = retrieve_evidence(session, pred, settings)
    if not evidence.sufficient:
        gate_note = (
            f"到期窗口内仅检索到 {len(evidence.hits)} 条达标证据"
            f"（门槛 {cfg.min_evidence} 条 / 强相关 {cfg.strong_similarity}）"
        )
        return _insufficient(pred, cfg, today, gate_note, source="gate")
    verdict, llm_calls = await _llm_verdict(client, pred, evidence, cfg)
    if verdict is None:
        return _Decision(
            status="failed",
            note="LLM 判定失败，保持 pending 下轮重试",
            source="semantic",
            llm_calls=llm_calls,
        )
    return _Decision(
        status="verified",
        verdict=verdict.verdict,
        note=verdict.verdict_note or "",
        evidence_ids=list(verdict.verdict_evidence_ids),
        source="semantic",
        llm_calls=llm_calls,
    )


async def verify_due_predictions(
    *,
    session: Session,
    client: LLMClient,
    settings: Settings,
    today: date,
    mode: RunMode | None = None,
    limit: int | None = None,
) -> VerifyOutcome:
    """验证所有 `status=pending AND due_date <= today` 的预言。"""
    run_mode = mode or settings.effective_mode()
    rows = list_pending_due(session, today)
    if limit is not None:
        rows = rows[:limit]
    out = VerifyOutcome(day=today, meta={"mode": run_mode.value, "due": len(rows)})

    for pred in rows:
        try:
            decision = await _verify_one(
                session, pred, client=client, settings=settings, mode=run_mode, today=today
            )
        except Exception as exc:  # 单条失败不得中断整批（红线 5）
            log.error("verify.failed", prediction=pred.id, error=repr(exc))
            out.failed += 1
            out.details.append({"id": pred.id, "status": "failed", "note": repr(exc)})
            continue

        out.llm_calls += decision.llm_calls
        if decision.status == "verified":
            score = VERDICT_SCORES.get(decision.verdict or "")
            save_verdict(
                session,
                pred,
                status="verified",
                verdict=decision.verdict,
                verdict_score=score,
                note=decision.note,
                evidence_ids=decision.evidence_ids,
                verified_by="auto",
            )
            out.verified += 1
        elif decision.status == "unverifiable":
            save_verdict(
                session,
                pred,
                status="unverifiable",
                verdict=None,
                verdict_score=None,
                note=decision.note,
                evidence_ids=None,
                verified_by="auto",
            )
            out.unverifiable += 1
        elif decision.status == "deferred":
            out.deferred += 1
        else:
            out.failed += 1
        out.details.append(
            {
                "id": pred.id,
                "status": decision.status,
                "verdict": decision.verdict,
                "source": decision.source,
                "note": decision.note,
            }
        )

    out.meta["llm_calls"] = out.llm_calls
    log.info(
        "verify.done",
        due=len(rows),
        verified=out.verified,
        unverifiable=out.unverifiable,
        deferred=out.deferred,
        failed=out.failed,
    )
    return out


__all__ = [
    "CriterionOutcome",
    "EvidenceResult",
    "VerifyOutcome",
    "judge_criteria",
    "retrieve_evidence",
    "verify_due_predictions",
]
