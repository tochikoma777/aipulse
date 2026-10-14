"""schema/prediction.py 单测：模型校验 + 模糊措辞黑名单 + 硬校验红线。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aipulse.schema.prediction import (
    Prediction,
    PredictionBatch,
    find_vague_phrases,
    validate_prediction,
)


def _pred(**kwargs) -> Prediction:
    defaults = {
        "statement": "Qwen3 将在 30 天内开源",
        "category": "product",
        "confidence": 0.7,
        "horizon_days": 30,
        "falsifiable_criteria": "截至到期日，GitHub 上出现 Qwen3 官方仓库即命中",
        "evidence_item_ids": ["it_a", "it_b"],
    }
    defaults.update(kwargs)
    return Prediction(**defaults)


# ── 字段校验 ────────────────────────────────────────────────────────


def test_confidence_step_rejected():
    with pytest.raises(ValidationError):
        _pred(confidence=0.73)


def test_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        _pred(confidence=0.99)


def test_confidence_valid_steps_ok():
    for c in (0.05, 0.5, 0.75, 0.95):
        assert _pred(confidence=c).confidence == c


def test_horizon_invalid_rejected():
    with pytest.raises(ValidationError):
        _pred(horizon_days=60)


def test_category_invalid_rejected():
    with pytest.raises(ValidationError):
        _pred(category="science")


def test_due_date_computed():
    from datetime import date

    pred = _pred(horizon_days=90)
    assert pred.due_date(date(2026, 10, 14)) == date(2027, 1, 12)


# ── 模糊措辞黑名单（DoD：至少 5 种典型模糊句）──────────────────────


@pytest.mark.parametrize(
    "sentence",
    [
        "Qwen 未来可能会开源下一代模型",  # 可能
        "大模型也许会变得更强",  # 也许
        "多模态技术未来可期",  # 未来可期
        "这个方向值得关注",  # 值得关注
        "该框架有望成为主流",  # 有望
        "推理成本或将大幅下降",  # 或将
        "开源模型大概率会追上闭源",  # 大概率
        "算力瓶颈早晚会被突破",  # 早晚
    ],
)
def test_vague_phrases_intercepted(sentence):
    assert find_vague_phrases(sentence), f"应拦截：{sentence}"


def test_impossible_is_not_vague():
    # "不可能"是可证伪的否定断言，不应被"可能"黑名单误伤
    assert "可能" not in find_vague_phrases("该模型不可能在 30 天内发布")


def test_clear_statement_has_no_vague():
    assert find_vague_phrases("Qwen3 将在 30 天内开源并登上 HuggingFace 榜首") == []


# ── 硬校验红线 ──────────────────────────────────────────────────────


def test_missing_falsifiable_criteria_rejected():
    pred = _pred(falsifiable_criteria="")
    problems = validate_prediction(pred)
    assert any("falsifiable_criteria" in p for p in problems)


def test_vague_statement_rejected():
    pred = _pred(statement="Qwen 未来可能会开源")
    problems = validate_prediction(pred)
    assert any("模糊措辞" in p for p in problems)


def test_insufficient_evidence_rejected_for_llm():
    pred = _pred(evidence_item_ids=["it_a"])
    problems = validate_prediction(pred, require_evidence=True)
    assert any("证据" in p for p in problems)


def test_handwritten_not_required_evidence():
    pred = _pred(evidence_item_ids=[], origin="human")
    assert validate_prediction(pred, require_evidence=False) == []


def test_valid_prediction_passes():
    assert validate_prediction(_pred()) == []


def test_batch_parses_list():
    batch = PredictionBatch.model_validate(
        {
            "predictions": [
                {
                    "statement": "X 将在 30 天内发布",
                    "category": "product",
                    "confidence": 0.8,
                    "horizon_days": 30,
                    "falsifiable_criteria": "官方发布即命中",
                    "evidence_item_ids": ["it_1", "it_2"],
                }
            ]
        }
    )
    assert len(batch.predictions) == 1
