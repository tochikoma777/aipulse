"""多角色辩论（M5 S4）：四 persona 并行陈述 → 交叉质证 → 主持人收敛。

三条与 trend 一脉相承的口径：

1. **证据包只给 id + 标题 + 热度 + 板块**，绝不给摘要正文。
   v1.17 的事故就是 predict 把输入原文回显进输出，输出膨胀 10 倍撞 `max_tokens`，
   最后生成 0 条。debate 的每方输出都要带正文，回显风险只会更大。
2. **LLM 只解释已有证据**，不负责"发现议题"——议题由 `--topic` 给定。
3. **主库只读**：客户端由调用方以 `engine=None` 构造（同 `cli/commands/trend.py:81`），
   本模块不写库、不读库，只读 `data/reports/**/daily.json` 解析出的 `CrossPeriodIndex`。

并发（Round 1 / Round 2 均 `asyncio.gather`）：

- 结构化格式阶梯存在**模块级进程内记忆**（`llm/openai_compat.py:47`）。
  四个 persona 同时起跑、记忆为空时，每个都会从 `json_schema` 独立试错；
  strong 档实测三级全不支持（同文件 :39）→ 首跑最多 4×3=12 次请求。
  所以先跑一次极廉价的 `_probe_format()` 把阶梯探明白，再 gather。
- `finish_reason == "length"` 会抛 `LLMTruncationError`（`openai_compat.py:334`），
  而 `generate_structured` 不捕获它 → 必须 `return_exceptions=True` + 逐方捕获，
  否则一个 persona 截断会炸掉整轮。

TODO(auto)：从 trend 输出自动挑本周最大争议话题（需要 `TrendReport` 的分歧度打分），
本轮只做手动 `--topic`，auto 模式未开工。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from pydantic import BaseModel

from aipulse.analysis.cross_period import CrossPeriodIndex, PeriodItem
from aipulse.core.errors import LLMError, LLMTruncationError
from aipulse.core.logging import get_logger
from aipulse.llm.base import ChatMessage, LLMClient
from aipulse.llm.prompt import render_prompt
from aipulse.llm.structured import generate_structured
from aipulse.reasoning.trend import char_count
from aipulse.schema.debate import (
    ITEM_ID_RE,
    PERSONAS,
    CrossResponse,
    DebateReport,
    ModeratorOutput,
    PersonaStatement,
)

log = get_logger(__name__)

EVIDENCE_LIMIT = 15
EVIDENCE_LINE_CHARS = 60
DEFAULT_MAX_TOKENS = 10000

_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_ASCII_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.#\-]{1,}")


# ══════════════════════════════════════════════════════════════════════════
# 证据包
# ══════════════════════════════════════════════════════════════════════════


def _keywords(topic: str) -> tuple[str, ...]:
    """议题关键词：中文按 2-gram，英文按整词。用于挑相关条目。"""
    out: list[str] = []
    for run in _CJK_RUN_RE.findall(topic):
        out.extend(run[i : i + 2] for i in range(len(run) - 1))
    out.extend(word.lower() for word in _ASCII_WORD_RE.findall(topic))
    return tuple(dict.fromkeys(out))


def _relevance(title: str, keywords: tuple[str, ...]) -> int:
    lowered = title.lower()
    return sum(1 for kw in keywords if kw and kw in lowered)


@dataclass(frozen=True)
class EvidenceItem:
    """证据包里的一行：id + 标题 + 热度 + 板块，**不含摘要正文**。`"""

    item_id: str
    title: str
    hot_score: float
    section: str
    day: str

    @property
    def line(self) -> str:
        tail = f"｜热度 {self.hot_score:.1f}｜{self.section or '未分板块'}"
        head = f"{self.item_id}｜{self.title}"
        budget = EVIDENCE_LINE_CHARS - len(tail)
        if len(head) > budget:
            head = head[: max(1, budget - 1)] + "…"
        return head + tail


def _candidates(index: CrossPeriodIndex, window_days: int) -> tuple[PeriodItem, ...]:
    """窗口内按"最近一次出现"去重后的条目集合。"""
    days = index.days[-window_days:] if window_days > 0 else index.days
    seen: dict[str, PeriodItem] = {}
    for day in reversed(days):
        snapshot = index.snapshots.get(day)
        if snapshot is None:
            continue
        for item in snapshot.items.values():
            seen.setdefault(item.item_id, item)
    return tuple(seen.values())


def build_evidence(
    index: CrossPeriodIndex, topic: str, *, window_days: int = 7, limit: int = EVIDENCE_LIMIT
) -> tuple[EvidenceItem, ...]:
    """按板块轮转取 ≤limit 条证据（每板块 Top 3-4，议题相关者优先）。

    ★ 为什么要按板块均衡：S4 首跑的证据包 15 条里 14 条是「论文与研究」，
    结果四方全部收敛到"论文 vs 非论文"这一个框架上——辩论的丰富度被输入
    偏斜锁死了。均衡取材让每个板块都有代表，persona 才有真正的分歧空间。

    只带 id / 标题 / 热度 / 板块——**绝不把 summary 塞进 prompt**。
    """
    keywords = _keywords(topic)
    items = _candidates(index, window_days)
    scored = sorted(
        items,
        key=lambda it: (-_relevance(it.title, keywords), -it.hot_score, it.item_id),
    )

    buckets: dict[str, list[PeriodItem]] = {}
    for item in scored:
        buckets.setdefault(item.section or "未分板块", []).append(item)
    # 板块顺序：议题命中度高的板块先出，其次看该板块最高热度
    order = sorted(
        buckets,
        key=lambda name: (
            -_relevance(buckets[name][0].title, keywords),
            -buckets[name][0].hot_score,
            name,
        ),
    )

    picked: list[PeriodItem] = []
    round_index = 0
    while len(picked) < limit:
        added = False
        for name in order:
            bucket = buckets[name]
            if round_index >= len(bucket):
                continue
            picked.append(bucket[round_index])
            added = True
            if len(picked) >= limit:
                break
        if not added:
            break
        round_index += 1

    return tuple(
        EvidenceItem(
            item_id=item.item_id,
            title=item.title,
            hot_score=item.hot_score,
            section=item.section,
            day=item.day,
        )
        for item in picked
    )


def render_evidence(items: tuple[EvidenceItem, ...]) -> str:
    return "\n".join(f"{i}. {item.line}" for i, item in enumerate(items, 1))


# ══════════════════════════════════════════════════════════════════════════
# 单次调用
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class _Outcome:
    """一次结构化调用的结果（含失败时的 token 记账）。"""

    parsed: object | None
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    error: str = ""
    truncated: bool = False


async def _call(
    client: LLMClient,
    prompt_name: str,
    variables: dict[str, object],
    response_model: type[BaseModel],
    *,
    max_tokens: int,
    model_tier: str = "strong",
) -> _Outcome:
    """渲染 prompt → 一次结构化调用 → 统一成 `_Outcome`（不抛异常）。

    注意：结构化校验失败时 `generate_structured` 会自费重试一次，
    只回传最后一次 `LLMResult`，首次调用的 token 不在返回里——
    这条路径下成本会被低估，实测时以 `attempts` 是否大于 `calls` 识别。
    """
    prompt, template = render_prompt(prompt_name, **variables)
    tier = template.model_tier or model_tier
    try:
        parsed, result = await generate_structured(
            client,
            [ChatMessage(role="user", content=prompt)],
            response_model=response_model,
            temperature=template.temperature,
            max_tokens=max_tokens,
            purpose=template.purpose,
            model_tier=tier,
        )
    except LLMTruncationError as exc:
        # 截断也是真花钱：token 随异常带出，必须计入总成本
        log.warning("debate.truncated", prompt=prompt_name, error=str(exc))
        return _Outcome(
            None,
            prompt_tokens=exc.prompt_tokens,
            completion_tokens=exc.completion_tokens,
            error=f"输出被 max_tokens 截断（{exc}）",
            truncated=True,
        )
    except LLMError as exc:
        log.warning("debate.call_failed", prompt=prompt_name, error=str(exc))
        return _Outcome(None, error=f"LLM 调用失败：{exc}")
    except Exception as exc:  # noqa: BLE001 - 单环节失败不得炸掉整轮
        log.warning("debate.call_error", prompt=prompt_name, error=repr(exc))
        return _Outcome(None, error=f"调用异常：{exc}")

    if result is None:
        return _Outcome(None, error="无 LLM 返回结果")
    if parsed is None:
        return _Outcome(
            None,
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            error="结构化校验失败（已重试一次仍不合法）",
        )
    return _Outcome(
        parsed,
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        calls=1,
    )


async def _probe_format(client: LLMClient, *, model_tier: str = "strong") -> tuple[int, int]:
    """预热探测：一次极廉价调用把结构化格式阶梯写进进程内记忆。

    不做这一步，4 个 persona 并行起跑时每个都会独立走完三级降级。
    返回 (prompt_tokens, completion_tokens)——探测也是真花钱，
    虽然它不计入 `llm_calls`（不是辩论环节），但必须计入总成本。
    """
    try:
        result = await client.chat(
            [ChatMessage(role="user", content="只回复 OK 两个字。")],
            temperature=0.0,
            max_tokens=16,
            purpose="debate_probe",
            model_tier=model_tier,
            json_schema=PersonaStatement.model_json_schema(),
        )
    except LLMTruncationError as exc:
        # 探测被截断也说明阶梯已探完（记忆在抛错前就写好了）
        return exc.prompt_tokens, exc.completion_tokens
    except Exception:  # noqa: BLE001 - 探测目的只是写入格式记忆，成败无所谓
        log.debug("debate.probe_done")
        return 0, 0
    return result.prompt_tokens, result.completion_tokens


# ══════════════════════════════════════════════════════════════════════════
# 三轮
# ══════════════════════════════════════════════════════════════════════════


def _cited_ids(*texts: str, allowed: set[str] | None = None) -> list[str]:
    ids: list[str] = []
    for text in texts:
        ids.extend(ITEM_ID_RE.findall(text or ""))
    uniq = sorted(set(ids))
    if allowed is None:
        return uniq
    return [i for i in uniq if i in allowed]


async def _round1(
    client: LLMClient,
    persona: str,
    label: str,
    *,
    topic: str,
    evidence_text: str,
    allowed: set[str],
    window_start: str,
    window_end: str,
    window_days: int,
    max_tokens: int,
) -> PersonaStatement:
    outcome = await _call(
        client,
        "debate/round1",
        {
            "topic": topic,
            "persona": persona,
            "persona_label": label,
            "window_start": window_start,
            "window_end": window_end,
            "window_days": window_days,
            "evidence": evidence_text,
            "max_chars": 600,
        },
        PersonaStatement,
        max_tokens=max_tokens,
    )
    stmt = PersonaStatement(
        persona=persona,
        persona_label=label,
        model=outcome.model,
        prompt_tokens=outcome.prompt_tokens,
        completion_tokens=outcome.completion_tokens,
        llm_calls=outcome.calls,
        attempts=1,
    )
    if outcome.error or outcome.parsed is None:
        stmt.invalid_reason = outcome.error or "无有效输出"
        return stmt

    parsed: PersonaStatement = outcome.parsed  # type: ignore[assignment]
    stmt.stance = parsed.stance
    stmt.key_points = [p.strip() for p in parsed.key_points if p.strip()][:3]
    stmt.reasoning = parsed.reasoning
    stmt.falsification = parsed.falsification
    stmt.cited_item_ids = _cited_ids(
        parsed.reasoning, parsed.stance, " ".join(parsed.cited_item_ids), allowed=allowed
    )
    stmt.char_count = char_count(parsed.reasoning)
    stmt.falsification.selfcheck()

    # 硬判据：任何 persona 未引用具体 item_id → 该轮无效
    if not stmt.cited_item_ids:
        stmt.invalid_reason = "未引用任何证据包内的 item_id"
    return stmt


async def _round2(
    client: LLMClient,
    persona: str,
    label: str,
    *,
    topic: str,
    own_stance: str,
    others_text: str,
    evidence_text: str,
    allowed: set[str],
    max_tokens: int,
) -> CrossResponse:
    outcome = await _call(
        client,
        "debate/round2",
        {
            "topic": topic,
            "persona": persona,
            "persona_label": label,
            "own_stance": own_stance,
            "others": others_text,
            "evidence": evidence_text,
        },
        CrossResponse,
        max_tokens=max_tokens,
    )
    resp = CrossResponse(
        persona=persona,
        persona_label=label,
        model=outcome.model,
        prompt_tokens=outcome.prompt_tokens,
        completion_tokens=outcome.completion_tokens,
        llm_calls=outcome.calls,
        attempts=1,
    )
    if outcome.error or outcome.parsed is None:
        resp.invalid_reason = outcome.error or "无有效输出"
        return resp

    parsed: CrossResponse = outcome.parsed  # type: ignore[assignment]
    resp.challenges = [c for c in parsed.challenges if c.point.strip() or c.target.strip()]
    resp.concessions = [c.strip() for c in parsed.concessions if c.strip()]
    resp.revised_stance = parsed.revised_stance
    cited_source = [c.point for c in resp.challenges]
    cited_source.extend(i for c in resp.challenges for i in c.cited_item_ids)
    cited_source.extend(resp.concessions)
    cited_source.extend(parsed.cited_item_ids)
    resp.cited_item_ids = _cited_ids(*cited_source, allowed=allowed)
    resp.char_count = char_count(" ".join(cited_source) + " " + resp.revised_stance)

    if not resp.cited_item_ids:
        resp.invalid_reason = "质证未引用任何证据包内的 item_id"
    elif not resp.challenges:
        resp.invalid_reason = "未提出任何实质质证（这一轮等于没发生）"
    return resp


def _others_text(statements: list[PersonaStatement], persona: str) -> str:
    blocks: list[str] = []
    for stmt in statements:
        if stmt.persona == persona:
            continue
        if not stmt.valid:
            blocks.append(
                f"【{stmt.persona_label or stmt.persona}】本方陈述无效：{stmt.invalid_reason}"
            )
            continue
        blocks.append(
            f"【{stmt.persona_label or stmt.persona}】\n"
            f"立场：{stmt.stance.strip()}\n"
            f"论述：{stmt.reasoning.strip()}\n"
            f"证伪条件：{stmt.falsification.observable.strip()}"
        )
    return "\n\n".join(blocks) or "（其他三方均无有效陈述）"


def _rounds_text(statements: list[PersonaStatement]) -> str:
    blocks: list[str] = []
    for stmt in statements:
        if not stmt.valid:
            blocks.append(f"【{stmt.persona_label or stmt.persona}】无效：{stmt.invalid_reason}")
            continue
        blocks.append(
            f"【{stmt.persona_label or stmt.persona}】\n"
            f"立场：{stmt.stance.strip()}\n"
            f"论述：{stmt.reasoning.strip()}"
        )
    return "\n\n".join(blocks) or "（Round 1 无有效陈述）"


def _cross_text(cross: list[CrossResponse]) -> str:
    blocks: list[str] = []
    for resp in cross:
        if not resp.valid:
            blocks.append(f"【{resp.persona_label or resp.persona}】无效：{resp.invalid_reason}")
            continue
        body = "\n".join(f"- 对【{c.target}】：{c.point}（{c.outcome}）" for c in resp.challenges)
        concede = "\n".join(f"- {c}" for c in resp.concessions) or "- （无让步）"
        blocks.append(
            f"【{resp.persona_label or resp.persona}】\n"
            f"质证：\n{body}\n让步：\n{concede}\n修正后立场：{resp.revised_stance.strip()}"
        )
    return "\n\n".join(blocks) or "（Round 2 无有效质证）"


# ══════════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════════


async def run_debate(
    index: CrossPeriodIndex,
    client: LLMClient,
    *,
    topic: str,
    max_tokens: int = 0,
    price_strong_cny_per_1m: float = 4.0,
    window_days: int = 7,
) -> DebateReport:
    """跑一场完整辩论。单环节失败只判该环节无效，不影响其余环节。"""
    if not index.days:
        return DebateReport(topic=topic, failures=["没有任何日报可取材"])

    days = index.days[-window_days:] if window_days > 0 else index.days
    evidence = build_evidence(index, topic, window_days=window_days)
    evidence_text = render_evidence(evidence)
    allowed = {item.item_id for item in evidence}
    budget_tokens = max_tokens if max_tokens > 0 else DEFAULT_MAX_TOKENS

    report = DebateReport(
        topic=topic,
        window_start=days[0],
        window_end=days[-1],
        window_days=len(days),
        evidence_lines=[item.line for item in evidence],
    )

    # 探测的 token 计入总成本，但不计入 llm_calls（它不是辩论环节）
    probe_prompt, probe_completion = await _probe_format(client)

    # ── Round 1：四方并行 ────────────────────────────────────────────
    results = await asyncio.gather(
        *(
            _round1(
                client,
                key,
                label,
                topic=topic,
                evidence_text=evidence_text,
                allowed=allowed,
                window_start=days[0],
                window_end=days[-1],
                window_days=len(days),
                max_tokens=budget_tokens,
            )
            for key, label in PERSONAS
        ),
        return_exceptions=True,
    )
    for key_label, result in zip(PERSONAS, results, strict=True):
        key, label = key_label
        if isinstance(result, BaseException):
            stmt = PersonaStatement(persona=key, persona_label=label, attempts=1)
            stmt.invalid_reason = f"并发执行异常：{result}"
        else:
            stmt = result
        report.statements.append(stmt)

    # ── Round 2：交叉质证（同样并行）────────────────────────────────
    cross_results = await asyncio.gather(
        *(
            _round2(
                client,
                stmt.persona,
                stmt.persona_label,
                topic=topic,
                own_stance=stmt.stance,
                others_text=_others_text(report.statements, stmt.persona),
                evidence_text=evidence_text,
                allowed=allowed,
                max_tokens=budget_tokens,
            )
            for stmt in report.statements
            if stmt.valid
        ),
        return_exceptions=True,
    )
    valid_keys = [s.persona for s in report.statements if s.valid]
    for key, outcome2 in zip(valid_keys, cross_results, strict=True):
        if isinstance(outcome2, BaseException):
            resp = CrossResponse(persona=key, attempts=1)
            resp.invalid_reason = f"并发执行异常：{outcome2}"
        else:
            resp = outcome2
        label = next((lb for k, lb in PERSONAS if k == key), key)
        resp.persona_label = resp.persona_label or label
        report.cross.append(resp)

    # ── 主持人收敛 ───────────────────────────────────────────────────
    mod_outcome = await _call(
        client,
        "debate/moderator",
        {
            "topic": topic,
            "evidence": evidence_text,
            "round1": _rounds_text(report.statements),
            "round2": _cross_text(report.cross),
        },
        ModeratorOutput,
        max_tokens=budget_tokens,
    )
    moderator = ModeratorOutput(
        model=mod_outcome.model,
        prompt_tokens=mod_outcome.prompt_tokens,
        completion_tokens=mod_outcome.completion_tokens,
        llm_calls=mod_outcome.calls,
        attempts=1,
    )
    if mod_outcome.error or mod_outcome.parsed is None:
        moderator.invalid_reason = mod_outcome.error or "无有效输出"
    else:
        parsed_mod: ModeratorOutput = mod_outcome.parsed  # type: ignore[assignment]
        moderator.consensus = [c.strip() for c in parsed_mod.consensus if c.strip()]
        moderator.key_disagreements = [d.strip() for d in parsed_mod.key_disagreements if d.strip()]
        moderator.actionable_conclusions = [
            c.strip() for c in parsed_mod.actionable_conclusions if c.strip()
        ]
        moderator.overall_confidence = max(0.0, min(1.0, float(parsed_mod.overall_confidence)))
        moderator.falsifications = parsed_mod.falsifications
        moderator.cited_item_ids = _cited_ids(
            *(moderator.key_disagreements + moderator.consensus), allowed=allowed
        )
        moderator.char_count = char_count(" ".join(moderator.key_disagreements))
        for f in moderator.falsifications:
            f.selfcheck()
    report.moderator = moderator

    # ── 记账 ─────────────────────────────────────────────────────────
    parts: list[PersonaStatement | CrossResponse | ModeratorOutput] = [
        *report.statements,
        *report.cross,
        moderator,
    ]
    report.llm_calls = sum(p.llm_calls for p in parts)
    report.attempts = sum(p.attempts for p in parts)
    report.prompt_tokens = sum(p.prompt_tokens for p in parts) + probe_prompt
    report.completion_tokens = sum(p.completion_tokens for p in parts) + probe_completion
    report.cost_cny = (
        (report.prompt_tokens + report.completion_tokens) * price_strong_cny_per_1m / 1_000_000
    )
    report.truncated = [
        f"{s.persona_label or s.persona}(R1)"
        for s in report.statements
        if not s.valid and "截断" in s.invalid_reason
    ]

    # ── 失败判据 ─────────────────────────────────────────────────────
    failures: list[str] = []
    if moderator.invalid_reason:
        failures.append(f"主持人收敛失败：{moderator.invalid_reason}")
    if not moderator.key_disagreements:
        failures.append(
            "key_disagreements 为空：四方收敛成了 bland 共识，本次辩论没有信息增量（判失败）"
        )
    for stmt in report.statements:
        if not stmt.valid:
            failures.append(
                f"{stmt.persona_label or stmt.persona} Round 1 无效：{stmt.invalid_reason}"
            )
    for resp in report.cross:
        if not resp.valid:
            failures.append(
                f"{resp.persona_label or resp.persona} Round 2 无效：{resp.invalid_reason}"
            )
    # 证伪条件不合格：只把该条标记为不可用，**不判整场失败**——
    # 用"整场失败"换掉"过度声称"是同一种错误的另一个方向（同 S2.6 斜率口径：
    # 当时拒绝"斜率唯一"，理由正是它用过度保守换掉了有效结论）。
    # 只有可用证伪数为 0 时，才是真的没有可判定结论。
    if report.falsification_usable == 0:
        failures.append("可用证伪条件为 0：没有任何一条满足互斥且穷尽，本次结论不可判定")
    report.failures = failures
    return report


__all__ = [
    "EVIDENCE_LIMIT",
    "EVIDENCE_LINE_CHARS",
    "EvidenceItem",
    "build_evidence",
    "render_evidence",
    "run_debate",
]
