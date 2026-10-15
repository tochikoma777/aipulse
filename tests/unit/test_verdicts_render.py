"""到期验证结果渲染单测（`verdicts.md`，设计方案 §11）。"""

from __future__ import annotations

from datetime import date

from aipulse.render.verdicts import render_verdicts_markdown
from aipulse.store.models import Prediction


def _pred(**kwargs) -> Prediction:
    base = {
        "id": "p1",
        "date": date(2026, 9, 1),
        "statement": "acme 将在 30 天内发布新仓库",
        "category": "community",
        "confidence": 0.7,
        "due_date": date(2026, 10, 1),
    }
    return Prediction(**{**base, **kwargs})


def test_render_verdicts_empty_state():
    out = render_verdicts_markdown([])
    assert "没有到期的预言" in out


def test_render_verdicts_marks_each_outcome():
    out = render_verdicts_markdown(
        [
            _pred(
                id="a",
                status="verified",
                verdict="hit",
                verdict_score=1.0,
                verdict_note="已发布",
            ),
            _pred(
                id="b",
                status="verified",
                verdict="miss",
                verdict_score=0.0,
                verified_by="human",
            ),
            _pred(id="c", status="unverifiable", verdict=None),
        ]
    )
    assert "✅ 命中" in out
    assert "❌ 落空" in out
    assert "⏭ 无法验证" in out
    assert "人工" in out
    assert "| 0.70 |" in out


def test_render_verdicts_escapes_pipes_and_truncates_note():
    out = render_verdicts_markdown(
        [
            _pred(
                id="a",
                statement="A | B",
                status="verified",
                verdict="partial",
                verdict_score=0.5,
                verdict_note="x" * 200,
            )
        ]
    )
    assert "A \\| B" in out
    assert "x" * 120 + "…" in out
