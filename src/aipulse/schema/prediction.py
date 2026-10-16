"""预言的结构化模型与硬校验（设计方案 §7.5 / §10.2 / §11.4-11.5）。

- `Prediction`：完整预言记录（含 v1.3 的 `origin` / `criteria*` 字段），既是
  `prompts/predict/generate.j2` 的结构化输出契约（结构化生成时 LLM 只填核心字段），
  也是手写预言入库前的校验模型。
- `PredictionBatch`：`generate.j2` 输出的批量包装。
- `Verdict`：到期判定结果（M3b 消费，本阶段先定义模型）。

硬校验（红线：预言必须可证伪）：
1. confidence 步长 0.05、取值范围 0.05-0.95；
2. horizon_days ∈ {7, 30, 90, 180}；
3. category ∈ 预定义集合；
4. 模糊措辞黑名单拦截（"可能/也许/未来可期/值得关注"等）——宁可错得明确，不要对得含糊；
5. `falsifiable_criteria` 不得为空；
6. LLM 生成的预言证据条数 ≥2。
"""

from __future__ import annotations

import math
import re
from collections.abc import Collection
from datetime import date as date_type
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# 预定义枚举（§7.5 / §10.2.1）
CATEGORIES: tuple[str, ...] = (
    "capability",
    "product",
    "research",
    "business",
    "policy",
    "hardware",
    "community",
)
HORIZONS: tuple[int, ...] = (7, 30, 90, 180)
CONFIDENCE_MIN = 0.05
CONFIDENCE_MAX = 0.95
CONFIDENCE_STEP = 0.05

# ── 模糊措辞黑名单（§10.2.1 #5）────────────────────────────────────────
# 典型模糊句（单测覆盖 ≥5 种）："可能""也许会变得更""未来值得期待""值得关注"…
# 注意："不可能"是**可证伪**的否定断言，故"可能"用负向断言排除"不可能"。
_VAGUE_PHRASES: tuple[str, ...] = (
    "未来可期",
    "值得期待",
    "值得关注",
    "拭目以待",
    "一定程度上",
    "渐成趋势",
    "也许",
    "或许",
    "有望",
    "或将",
    "大概率",
    "早晚",
    "迟早",
)
_VAGUE_ALT = "|".join(re.escape(p) for p in sorted(_VAGUE_PHRASES, key=len, reverse=True))
_VAGUE_RE = re.compile(_VAGUE_ALT)
_POSSIBLE_RE = re.compile(r"(?<!不)可能")


def find_vague_phrases(text: str) -> list[str]:
    """在文本中找出命中的模糊措辞（用于拦截与日志，不区分大小写）。"""
    source = text or ""
    found = list(_VAGUE_RE.findall(source))
    if _POSSIBLE_RE.search(source):
        found.append("可能")
    return found


class Prediction(BaseModel):
    """完整预言记录（校验/入库契约）。"""

    statement: str = Field(..., min_length=1)
    category: str = Field(default="capability")
    confidence: float = Field(..., ge=CONFIDENCE_MIN, le=CONFIDENCE_MAX)
    horizon_days: int = Field(default=30)
    falsifiable_criteria: str = Field(default="")
    rationale: str = Field(default="")
    evidence_item_ids: list[str] = Field(default_factory=list)
    # v1.3：来源与可选量化判据
    origin: Literal["human", "llm"] = "llm"
    criteria: str | None = None
    criteria_params: dict[str, Any] | None = None

    @field_validator("category")
    @classmethod
    def _check_category(cls, value: str) -> str:
        if value not in CATEGORIES:
            raise ValueError(f"category 必须是 {CATEGORIES} 之一，收到：{value!r}")
        return value

    @field_validator("confidence")
    @classmethod
    def _check_confidence_step(cls, value: float) -> float:
        # 步长 0.05：换算成"0.05 的整数倍"后必须能还原（浮点用容差比较）
        steps = round(value / CONFIDENCE_STEP)
        if not math.isclose(value, steps * CONFIDENCE_STEP, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(f"confidence 必须是 0.05 的整数倍（0.05-0.95），收到：{value}")
        return value

    @field_validator("horizon_days")
    @classmethod
    def _check_horizon(cls, value: int) -> int:
        if value not in HORIZONS:
            raise ValueError(f"horizon_days 必须是 {HORIZONS} 之一，收到：{value}")
        return value

    def due_date(self, day: date_type) -> date_type:
        """由生成日期与 horizon_days 推算到期日。"""
        from datetime import timedelta

        return day + timedelta(days=self.horizon_days)


class PredictionBatch(BaseModel):
    """`generate.j2` 的批量输出契约。"""

    predictions: list[Prediction] = Field(default_factory=list)


class Verdict(BaseModel):
    """到期判定结果（M3b 使用；本阶段先定义契约）。"""

    verdict: Literal["hit", "partial", "miss"]
    verdict_note: str = Field(default="")
    verdict_evidence_ids: list[str] = Field(default_factory=list)


def validate_prediction(
    pred: Prediction,
    *,
    require_evidence: bool = True,
    known_item_ids: Collection[str] | None = None,
) -> list[str]:
    """硬校验（红线拦截）。返回问题清单；空列表表示通过。

    - `require_evidence=True`：LLM 生成要求 ≥2 条证据；手写预言传 False（§11.4 不强求证据）。
    - 缺 `falsifiable_criteria` 一律拒收（红线，手写/LLM 均适用）。
    - `known_item_ids`：候选证据池。给了就必须全在里面——**只校验数量是不够的**：
      prompt 里写"只能引用输入中的 id"，模型照样会编出看着合理的 id，
      于是预言挂着一串查不到的证据进了记分板，整个项目唯一的可信度资产被架空。
      手写预言不传（那时条目可能还没入库）。
    """
    problems: list[str] = []
    vague = find_vague_phrases(pred.statement)
    if vague:
        problems.append(f"statement 含模糊措辞 {vague}，须改写为可证伪表述")
    if not (pred.falsifiable_criteria or "").strip():
        problems.append("缺少 falsifiable_criteria（红线：不得入库）")
    if require_evidence and len(pred.evidence_item_ids) < 2:
        problems.append(f"证据条目不足：需 ≥2 条，实际 {len(pred.evidence_item_ids)}")
    if known_item_ids is not None:
        unknown = [i for i in pred.evidence_item_ids if i not in known_item_ids]
        if unknown:
            problems.append(
                f"证据 id 不在候选池内（疑似编造）：{', '.join(unknown[:3])}"
                f"——只能引用输入中列出的条目 id"
            )
    return problems


__all__ = [
    "CATEGORIES",
    "CONFIDENCE_MAX",
    "CONFIDENCE_MIN",
    "CONFIDENCE_STEP",
    "HORIZONS",
    "Prediction",
    "PredictionBatch",
    "Verdict",
    "find_vague_phrases",
    "validate_prediction",
]
