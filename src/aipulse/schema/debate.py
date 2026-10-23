"""debate（多角色辩论）的数据结构（M5 S4）。

设计上唯一要死守的一条：**证伪条件必须可判定**。

M5 S3 的 watchlist 出过一次悬空判定（`data/reports/trend/watchlist.json`）：

    "若 10-22 仍在榜且热度 ≥82.89 → 证伪"
    "若跌出或 <82.06 → 维持单日"

实际热度 82.82：不满足 ≥82.89，也不满足 <82.06 → **两个分支都不触发**。
根因是用"点值区间"构造互斥条件——而"仍在榜"本身已经是判定延续的充分条件，
热度阈值纯属多余，只制造灰色地带。

因此本模块的 `Falsification` 在结构上就不允许出现灰色地带：
一个**二元可观测状态** + 两个分支（成立 / 不成立），天然互斥且穷尽。
校验器 `falsification_violations()` 会把点值阈值、分支同义等问题写进
`violations`，由上层判该条无效。
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

# 四个 persona 的（key, 中文名）。任务描述一律放 prompts/debate/*.j2，不写进 Python。
PERSONAS: tuple[tuple[str, str], ...] = (
    ("optimist", "乐观派"),
    ("skeptic", "怀疑派"),
    ("engineer", "工程派"),
    ("investor", "投资派"),
)

ITEM_ID_RE = re.compile(r"it_[0-9a-f]{6,}")

# 日期不是阈值，检测前先摘掉，避免把 "2026-10-23" 误判成点值
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?:\s*(?:至|~|-|到)\s*\d{4}-\d{2}-\d{2})?")

# 点值阈值的形态（两种语序都要拦）：
#   >=82.89 / <82.06 / 增长 20% / 热度 82 以上 / 不低于 82.89 / 超过 3 天
_THRESHOLD_WORDS = r"(?:以上|以下|高于|低于|超过|达到|不低于|不超过|至少|最多|少于|多于)"
_THRESHOLD_RE = re.compile(
    rf"(?:[<>≥≤]=?\s*\d"
    rf"|\d+(?:\.\d+)?\s*(?:%|％)"
    rf"|\d+(?:\.\d+)?\s*{_THRESHOLD_WORDS}"
    rf"|{_THRESHOLD_WORDS}\s*\d+(?:\.\d+)?)"
)


# 独立问句的引导词。出现两次以上 = 把多个可观测状态合取成一个条件，
# 组合状态数 ≥4 而分支只有 2 个 → 必然覆盖不全。
# 注意"是否同时公开 A、B、C 三项"只算一次：它是单一问句，仍是二元可判定的。
_QUESTION_MARKERS = ("是否", "能否")


def falsification_violations(
    *, observable: str, if_observed: str, if_not_observed: str, claim: str = ""
) -> list[str]:
    """证伪条件的自查：任意实际值都必须必然落入某一分支。"""
    out: list[str] = []
    if not claim.strip():
        out.append("claim 为空：没有可被检验的断言")
    if not observable.strip():
        out.append("observable 为空：没有可观测状态")
    if not if_observed.strip() or not if_not_observed.strip():
        out.append("分支缺失：观测成立/不成立两侧都必须写出结论")
        return out

    # 去掉日期后仍出现数值阈值 → 用点值构造分支，必然出现灰色地带
    probe = _DATE_RE.sub("", observable)
    if _THRESHOLD_RE.search(probe) or _THRESHOLD_RE.search(_DATE_RE.sub("", if_observed)):
        out.append(
            "证伪条件用了点值阈值（如热度≥X / 跌幅超过 Y%）；"
            "必须改成二元可观测状态（如'某日是否仍在 Top30'），否则会出现两个分支都不触发的悬空判定"
        )
    if if_observed.strip() == if_not_observed.strip():
        out.append("两个分支结论相同：等于没有给出判定")
    if sum(observable.count(marker) for marker in _QUESTION_MARKERS) >= 2:
        out.append(
            "observable 含两个以上独立问句（如『是否出现新条目，同时 X 是否仍在榜』）："
            "组合状态有 4 种而分支只有 2 个，必然覆盖不全；必须拆成单一问句"
        )
    if len(observable.strip()) < 6:
        out.append("observable 过短，无法判定（要写清'观测什么、在哪一天/哪个集合上观测'）")
    return out


class Falsification(BaseModel):
    """一条可判定的证伪条件：一个二元可观测状态 + 互斥且穷尽的两个分支。"""

    claim: str = ""
    """被检验的断言（一句话）。"""

    observable: str = ""
    """可观测状态，写成二元问句，如「2026-10-23 该条目是否仍在 Top30」。
    必须是能直接查出来的状态，不能是程度、不能带阈值。"""

    if_observed: str = ""
    """观测成立 → 断言得到支持（或维持）。"""

    if_not_observed: str = ""
    """观测不成立 → 断言被证伪（或翻转）。"""

    target_item_ids: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)

    def selfcheck(self) -> list[str]:
        found = falsification_violations(
            claim=self.claim,
            observable=self.observable,
            if_observed=self.if_observed,
            if_not_observed=self.if_not_observed,
        )
        self.violations = sorted(set(self.violations) | set(found))
        return self.violations

    @property
    def ok(self) -> bool:
        return not self.violations


class Challenge(BaseModel):
    """Round 2 的一条质证：点名对象 + 核心一击 + 结果。

    结构化是为了能渲染成交锋矩阵（谁质疑谁 / 要点 / 是否让步）——
    纯文本列表做不到"按对被分组"。
    """

    target: str = ""
    """被质疑方（persona key 或中文名）。"""

    point: str = ""
    """核心一击：一句话，不带 ID（ID 放 cited_item_ids）。"""

    outcome: str = ""
    """结果：让步 / 部分让步 / 坚持。"""

    cited_item_ids: list[str] = Field(default_factory=list)


class PersonaStatement(BaseModel):
    """Round 1：某个 persona 的独立陈述。"""

    persona: str = ""
    persona_label: str = ""
    stance: str = ""
    """一句话立场。"""

    key_points: list[str] = Field(default_factory=list)
    """核心论据 3 条（人类层）；论述全文留在 `reasoning`，进折叠块。"""

    reasoning: str = ""
    """论述正文。"""

    cited_item_ids: list[str] = Field(default_factory=list)
    falsification: Falsification = Field(default_factory=Falsification)
    invalid_reason: str = ""
    """非空表示该陈述无效（未引用 item_id / 调用失败 / 截断）。"""

    char_count: int = 0
    llm_calls: int = 0
    attempts: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""

    @property
    def valid(self) -> bool:
        return not self.invalid_reason


class CrossResponse(BaseModel):
    """Round 2：交叉质证（能看到其他三方观点后给出的回应）。"""

    persona: str = ""
    persona_label: str = ""
    challenges: list[Challenge] = Field(default_factory=list)
    """对他方观点的质证；每条必须点名 persona 并引用 item_id。"""

    concessions: list[str] = Field(default_factory=list)
    """被说服后的让步/修正。"""

    revised_stance: str = ""
    cited_item_ids: list[str] = Field(default_factory=list)
    invalid_reason: str = ""
    char_count: int = 0
    llm_calls: int = 0
    attempts: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""

    @property
    def valid(self) -> bool:
        return not self.invalid_reason


class ModeratorOutput(BaseModel):
    """主持人收敛：五项输出。"""

    consensus: list[str] = Field(default_factory=list)
    key_disagreements: list[str] = Field(default_factory=list)
    """为空 = 四个 persona 收敛成了 bland 共识，判失败。"""

    actionable_conclusions: list[str] = Field(default_factory=list)
    overall_confidence: float = 0.0
    falsifications: list[Falsification] = Field(default_factory=list)
    """「什么证据会让我改变判断」：每条都是一个二元可判定条件。"""

    cited_item_ids: list[str] = Field(default_factory=list)
    invalid_reason: str = ""
    char_count: int = 0
    llm_calls: int = 0
    attempts: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""


class DebateReport(BaseModel):
    """一次辩论的完整产物。"""

    topic: str = ""
    window_start: str = ""
    window_end: str = ""
    window_days: int = 0
    evidence_lines: list[str] = Field(default_factory=list)
    """实际喂给模型的证据包（≤15 条，每条 ≤60 字，带 item_id，不含原文）。"""

    statements: list[PersonaStatement] = Field(default_factory=list)
    cross: list[CrossResponse] = Field(default_factory=list)
    moderator: ModeratorOutput = Field(default_factory=ModeratorOutput)

    llm_calls: int = 0
    attempts: int = 0
    truncated: list[str] = Field(default_factory=list)
    """被 max_tokens 截断的环节名。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_cny: float = 0.0
    model_tier: str = "strong"
    failures: list[str] = Field(default_factory=list)
    """失败判据的命中项；非空 = 本次辩论不合格。"""

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def falsification_total(self) -> int:
        """写出来的证伪条件总数（四方各 1 + 主持人若干）。"""
        return sum(1 for s in self.statements if s.falsification.observable) + len(
            self.moderator.falsifications
        )

    @property
    def falsification_usable(self) -> int:
        """通过互斥且穷尽自查的证伪条件数。

        不合格的条目**只标记、不判整场失败**——用"整场失败"换"过度声称"
        是同一种错误的两个方向（同 S2.6 斜率口径：当时拒绝"斜率唯一"的理由
        正是它用过度保守换掉了有效结论）。只有可用数为 0 才真的没有可判定结论。
        """
        usable = sum(
            1
            for s in self.statements
            if s.falsification.observable and not s.falsification.violations
        )
        usable += sum(1 for f in self.moderator.falsifications if not f.violations)
        return usable

    def to_markdown(self) -> str:
        lines = [
            f"# AI 脉搏 · 多角色辩论：{self.topic}",
            "",
            f"> 取数窗口 {self.window_start} → {self.window_end}（{self.window_days} 天）"
            f"　证据 {len(self.evidence_lines)} 条　调用 {self.llm_calls}/{self.attempts}"
            f"　成本 ¥{self.cost_cny:.4f}"
            f"　可用证伪 {self.falsification_usable}/{self.falsification_total}",
            "",
        ]
        if self.failures:
            lines.append("## ⛔ 本次辩论判失败")
            lines.append("")
            for item in self.failures:
                lines.append(f"- {item}")
            lines.append("")

        lines.append("## 一、Round 1 各方陈述")
        lines.append("")
        for st in self.statements:
            lines.append(f"### {st.persona_label or st.persona}")
            lines.append("")
            if st.invalid_reason:
                lines.append(f"> 本方陈述无效：{st.invalid_reason}")
                lines.append("")
                continue
            lines.append(f"**立场**：{st.stance.strip()}")
            lines.append("")
            lines.append(st.reasoning.strip())
            lines.append("")
            lines.append(f"- 引用：{', '.join(st.cited_item_ids) or '（无）'}")
            lines.append(
                f"- 证伪条件：观测『{st.falsification.observable.strip()}』；"
                f"成立 → {st.falsification.if_observed.strip()}；"
                f"不成立 → {st.falsification.if_not_observed.strip()}"
            )
            if st.falsification.violations:
                lines.append(
                    "- ⚠ 证伪条件不可用（已从可判定清单排除）："
                    + "；".join(st.falsification.violations)
                )
            lines.append("")

        lines.append("## 二、Round 2 交叉质证")
        lines.append("")
        for cr in self.cross:
            lines.append(f"### {cr.persona_label or cr.persona}")
            lines.append("")
            if cr.invalid_reason:
                lines.append(f"> 本方质证无效：{cr.invalid_reason}")
                lines.append("")
                continue
            for ch in cr.challenges:
                lines.append(f"- 质证（→ {ch.target}）：{ch.point.strip()}（{ch.outcome}）")
            for item in cr.concessions:
                lines.append(f"- 让步：{item.strip()}")
            lines.append("")
            lines.append(f"**修正后立场**：{cr.revised_stance.strip()}")
            lines.append("")

        lines.append("## 三、主持人收敛")
        lines.append("")
        mod = self.moderator
        if mod.invalid_reason:
            lines.append(f"> 收敛失败：{mod.invalid_reason}")
            lines.append("")
        else:
            lines.append("**已达成共识**")
            lines.append("")
            for item in mod.consensus:
                lines.append(f"- {item.strip()}")
            lines.append("")
            lines.append("**关键分歧**")
            lines.append("")
            for item in mod.key_disagreements:
                lines.append(f"- {item.strip()}")
            lines.append("")
            lines.append("**可执行结论**")
            lines.append("")
            for item in mod.actionable_conclusions:
                lines.append(f"- {item.strip()}")
            lines.append("")
            lines.append(f"**整体置信度**：{mod.overall_confidence:.2f}")
            lines.append("")
            lines.append("**什么证据会让我改变判断**")
            lines.append("")
            for f in mod.falsifications:
                lines.append(
                    f"- 断言：{f.claim.strip()}\n"
                    f"  - 观测：{f.observable.strip()}\n"
                    f"  - 成立 → {f.if_observed.strip()}\n"
                    f"  - 不成立 → {f.if_not_observed.strip()}"
                )
                if f.violations:
                    lines.append(
                        "  - ⚠ 本条不可用（已从可判定清单排除）：" + "；".join(f.violations)
                    )
            lines.append("")

        lines.append("## 四、证据包（喂给模型的原文，不含摘要正文）")
        lines.append("")
        for line in self.evidence_lines:
            lines.append(f"- {line}")
        return "\n".join(lines).rstrip() + "\n"

    def summary(self) -> dict[str, object]:
        """给 --json 的指标摘要（不含正文，避免刷屏）。"""
        return {
            "topic": self.topic,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "window_days": self.window_days,
            "evidence_count": len(self.evidence_lines),
            "llm_calls": self.llm_calls,
            "attempts": self.attempts,
            "truncated": self.truncated,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_cny": round(self.cost_cny, 6),
            "failures": self.failures,
            "falsification_usable": self.falsification_usable,
            "falsification_total": self.falsification_total,
            "statements": [
                {
                    "persona": s.persona,
                    "invalid_reason": s.invalid_reason,
                    "key_points": len(s.key_points),
                    "cited_item_ids": len(s.cited_item_ids),
                    "char_count": s.char_count,
                    "falsification_violations": s.falsification.violations,
                }
                for s in self.statements
            ],
            "cross": [
                {
                    "persona": c.persona,
                    "invalid_reason": c.invalid_reason,
                    "challenges": len(c.challenges),
                    "concessions": len(c.concessions),
                    "cited_item_ids": len(c.cited_item_ids),
                }
                for c in self.cross
            ],
            "moderator": {
                "invalid_reason": self.moderator.invalid_reason,
                "consensus": len(self.moderator.consensus),
                "key_disagreements": len(self.moderator.key_disagreements),
                "actionable_conclusions": len(self.moderator.actionable_conclusions),
                "overall_confidence": self.moderator.overall_confidence,
                "falsifications": len(self.moderator.falsifications),
                "falsification_violations": [
                    v for f in self.moderator.falsifications for v in f.violations
                ],
            },
        }


__all__ = [
    "Challenge",
    "CrossResponse",
    "DebateReport",
    "Falsification",
    "ITEM_ID_RE",
    "ModeratorOutput",
    "PERSONAS",
    "PersonaStatement",
    "falsification_violations",
]
