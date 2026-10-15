"""量化判据 6 模板的判定单测（zero-LLM，设计方案 §11.5 / §10.2.2）。

覆盖：命中 / 落空 / 容差带 partial / 覆盖不足（undetermined，不得当成 miss）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlmodel import Session

from aipulse.core.config import Settings
from aipulse.reasoning.verifier import judge_criteria
from aipulse.store.db import init_db
from aipulse.store.models import Entity, Item, Prediction, Signal

CFG = Settings().verify
DATE = date(2026, 1, 1)
DUE = date(2026, 1, 31)


def _pred(criteria: str, params: dict, **kw) -> Prediction:
    base: dict = {
        "id": "pred_x",
        "date": DATE,
        "statement": "s",
        "category": "product",
        "confidence": 0.7,
        "horizon_days": 30,
        "due_date": DUE,
        "falsifiable_criteria": "c",
        "status": "pending",
        "criteria": criteria,
        "criteria_params": params,
    }
    base.update(kw)
    return Prediction(**base)


def _item(
    item_id: str, *, source: str, title: str, ts: datetime, points: int | None = None
) -> Item:
    metrics = {"points": points} if points is not None else {}
    return Item(
        id=item_id,
        source=source,
        title=title,
        url=f"https://example.com/{item_id}",
        content_hash=f"h-{item_id}",
        published_at=ts,
        collected_at=ts,
        metrics=metrics,
    )


@pytest.fixture
def session(tmp_path):
    engine = init_db(tmp_path / "t.db")
    with Session(engine, expire_on_commit=False) as s:
        yield s
    engine.dispose()


# ── github_new_repo ──────────────────────────────────────────────────


def test_github_new_repo_hit(session: Session):
    session.add(
        Signal(
            entity_type="repo",
            entity_key="acme/new",
            metric="stars",
            value=5,
            ts=datetime(2026, 1, 10, tzinfo=UTC),
        )
    )
    session.commit()
    out = judge_criteria(session, _pred("github_new_repo", {"owner": "acme"}), CFG)
    assert out is not None and out.determined
    assert out.verdict == "hit"


def test_github_new_repo_miss_when_only_old_repos(session: Session):
    session.add(
        Signal(
            entity_type="repo",
            entity_key="acme/old",
            metric="stars",
            value=5,
            ts=datetime(2025, 12, 1, tzinfo=UTC),  # 窗口前
        )
    )
    session.commit()
    out = judge_criteria(session, _pred("github_new_repo", {"owner": "acme"}), CFG)
    assert out is not None and out.determined
    assert out.verdict == "miss"


def test_github_new_repo_undetermined_without_coverage(session: Session):
    out = judge_criteria(session, _pred("github_new_repo", {"owner": "ghost"}), CFG)
    assert out is not None and not out.determined


# ── github_stars_reach ───────────────────────────────────────────────


def _stars(session: Session, repo: str, value: float, ts: datetime) -> None:
    session.add(Signal(entity_type="repo", entity_key=repo, metric="stars", value=value, ts=ts))
    session.commit()


def test_github_stars_reach_hit(session: Session):
    _stars(session, "acme/x", 95000, datetime(2026, 1, 5, tzinfo=UTC))
    out = judge_criteria(
        session, _pred("github_stars_reach", {"repo": "acme/x", "threshold": 90000}), CFG
    )
    assert out is not None and out.verdict == "hit"


def test_github_stars_reach_partial_in_tolerance_band(session: Session):
    _stars(session, "acme/x", 88000, datetime(2026, 1, 5, tzinfo=UTC))
    out = judge_criteria(
        session, _pred("github_stars_reach", {"repo": "acme/x", "threshold": 90000}), CFG
    )
    assert out is not None and out.verdict == "partial"


def test_github_stars_reach_miss_below_tolerance(session: Session):
    _stars(session, "acme/x", 50000, datetime(2026, 1, 5, tzinfo=UTC))
    out = judge_criteria(
        session, _pred("github_stars_reach", {"repo": "acme/x", "threshold": 90000}), CFG
    )
    assert out is not None and out.verdict == "miss"


def test_github_stars_reach_undetermined_without_coverage(session: Session):
    out = judge_criteria(
        session, _pred("github_stars_reach", {"repo": "ghost/x", "threshold": 1}), CFG
    )
    assert out is not None and not out.determined


# ── hn_story_points ──────────────────────────────────────────────────


def test_hn_story_points_hit(session: Session):
    session.add(
        _item(
            "it_hn",
            source="hackernews",
            title="Qwen3 开源引发热议",
            ts=datetime(2026, 1, 10, tzinfo=UTC),
            points=500,
        )
    )
    session.commit()
    out = judge_criteria(
        session, _pred("hn_story_points", {"keyword": "Qwen3", "threshold": 300}), CFG
    )
    assert out is not None and out.verdict == "hit"
    assert out.evidence_ids == ["it_hn"]


def test_hn_story_points_miss_when_no_keyword(session: Session):
    session.add(
        _item(
            "it_hn",
            source="hackernews",
            title="无关话题",
            ts=datetime(2026, 1, 10, tzinfo=UTC),
            points=500,
        )
    )
    session.commit()
    out = judge_criteria(
        session, _pred("hn_story_points", {"keyword": "Qwen3", "threshold": 300}), CFG
    )
    assert out is not None and out.verdict == "miss"


def test_hn_story_points_undetermined_without_hn(session: Session):
    out = judge_criteria(
        session, _pred("hn_story_points", {"keyword": "Qwen3", "threshold": 300}), CFG
    )
    assert out is not None and not out.determined


# ── entity_mentions ──────────────────────────────────────────────────


def test_entity_mentions_hit(session: Session):
    for i in range(3):
        session.add(Entity(name="Qwen", type="model", item_id=f"it_{i}", date=date(2026, 1, 26)))
    session.commit()
    out = judge_criteria(session, _pred("entity_mentions", {"entity": "Qwen", "threshold": 3}), CFG)
    assert out is not None and out.verdict == "hit"


def test_entity_mentions_miss(session: Session):
    session.add(Entity(name="Qwen", type="model", item_id="it_1", date=date(2026, 1, 26)))
    session.commit()
    out = judge_criteria(session, _pred("entity_mentions", {"entity": "Qwen", "threshold": 5}), CFG)
    assert out is not None and out.verdict == "miss"


def test_entity_mentions_undetermined_without_coverage(session: Session):
    out = judge_criteria(session, _pred("entity_mentions", {"entity": "Qwen", "threshold": 1}), CFG)
    assert out is not None and not out.determined


# ── arxiv_paper_count ────────────────────────────────────────────────


def test_arxiv_paper_count_hit(session: Session):
    for i in range(2):
        session.add(
            _item(
                f"it_ax{i}",
                source="arxiv",
                title=f"关于 Qwen3 的研究 {i}",
                ts=datetime(2026, 1, 26, tzinfo=UTC),
            )
        )
    session.commit()
    out = judge_criteria(
        session, _pred("arxiv_paper_count", {"keyword": "Qwen3", "threshold": 2}), CFG
    )
    assert out is not None and out.verdict == "hit"


def test_arxiv_paper_count_miss(session: Session):
    session.add(
        _item("it_ax", source="arxiv", title="无关研究", ts=datetime(2026, 1, 26, tzinfo=UTC))
    )
    session.commit()
    out = judge_criteria(
        session, _pred("arxiv_paper_count", {"keyword": "Qwen3", "threshold": 1}), CFG
    )
    assert out is not None and out.verdict == "miss"


def test_arxiv_paper_count_undetermined_without_arxiv(session: Session):
    out = judge_criteria(
        session, _pred("arxiv_paper_count", {"keyword": "Qwen3", "threshold": 1}), CFG
    )
    assert out is not None and not out.determined


# ── custom（受限表达式）─────────────────────────────────────────────


def test_custom_hit_with_and_composition(session: Session):
    _stars(session, "acme/x", 200, datetime(2026, 1, 5, tzinfo=UTC))
    for i in range(3):
        session.add(Entity(name="Qwen", type="model", item_id=f"it_{i}", date=date(2026, 1, 26)))
    session.commit()
    expr = "stars(repo='acme/x', threshold=100) and mentions(entity='Qwen', threshold=3)"
    out = judge_criteria(session, _pred("custom", {"expr": expr}), CFG)
    assert out is not None and out.determined and out.verdict == "hit"


def test_custom_miss_when_false(session: Session):
    _stars(session, "acme/x", 200, datetime(2026, 1, 5, tzinfo=UTC))
    session.commit()
    expr = "stars(repo='acme/x', threshold=999999)"
    out = judge_criteria(session, _pred("custom", {"expr": expr}), CFG)
    assert out is not None and out.determined and out.verdict == "miss"


def test_custom_undetermined_when_coverage_missing(session: Session):
    out = judge_criteria(
        session, _pred("custom", {"expr": "stars(repo='nope/x', threshold=1)"}), CFG
    )
    assert out is not None and not out.determined


def test_custom_syntax_error_is_undetermined(session: Session):
    out = judge_criteria(session, _pred("custom", {"expr": "stars("}), CFG)
    assert out is not None and not out.determined


def test_custom_unknown_function_is_undetermined(session: Session):
    out = judge_criteria(session, _pred("custom", {"expr": "wipe()"}), CFG)
    assert out is not None and not out.determined


def test_unknown_template_returns_none(session: Session):
    assert judge_criteria(session, _pred("does_not_exist", {}), CFG) is None
