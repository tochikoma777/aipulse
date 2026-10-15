"""`predictions.md` 渲染单测（设计方案 §11）。"""

from __future__ import annotations

from datetime import date

from aipulse.render.predictions import render_predictions_markdown
from aipulse.store.models import Prediction


def _row(**kwargs) -> Prediction:
    base = {
        "id": "pred_1",
        "date": date(2026, 10, 15),
        "statement": "vLLM 将在 30 天内发布 v2",
        "category": "capability",
        "confidence": 0.75,
        "horizon_days": 30,
        "due_date": date(2026, 11, 14),
        "falsifiable_criteria": "到期日官方仓库出现 v2 tag 即命中",
        "origin": "llm",
    }
    return Prediction(**{**base, **kwargs})


def test_render_predictions_lists_rows():
    out = render_predictions_markdown([_row()])

    assert "今日新生成的预言" in out
    assert "vLLM 将在 30 天内发布 v2" in out
    assert "| 0.75 |" in out
    assert "2026-11-14" in out
    assert "到期日官方仓库出现 v2 tag 即命中" in out
    assert "verdicts.md" in out  # 告诉读者判定结果去哪看


def test_render_predictions_zero_is_explicit_not_blank():
    out = render_predictions_markdown([])

    assert "本次运行没有新增预言" in out
    assert "off" in out  # 说明 off 档不生成
    assert "拒收" in out  # 说明也可能因校验为 0


def test_render_predictions_surfaces_dropped_drafts():
    """被拒收的草案要写进报告——否则会让人误以为每天都能稳定产出 5 条。"""
    out = render_predictions_markdown(
        [],
        dropped=[
            {
                "statement": "某模型可能会在近期变得更强",
                "problems": ["statement 含模糊措辞 ['可能']，须改写为可证伪表述"],
            }
        ],
    )

    assert "被可证伪校验拒收（1 条）" in out
    assert "含模糊措辞" in out


def test_render_predictions_escapes_pipes():
    out = render_predictions_markdown([_row(statement="A | B")])
    assert "A \\| B" in out
