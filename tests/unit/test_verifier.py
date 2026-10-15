"""reasoning/verifier.py 编排单测：双路径、off 档零 LLM、证据门槛、grace、LLM 失败保持 pending。"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from sqlmodel import Session

from aipulse.core.config import RunMode, Settings
from aipulse.llm.base import ChatMessage, LLMResult
from aipulse.reasoning.verifier import verify_due_predictions
from aipulse.store.db import init_db
from aipulse.store.models import Item, Prediction, Signal

TODAY = date(2026, 6, 1)
_VERDICT_JSON = json.dumps(
    {"verdict": "hit", "verdict_note": "证据 it_q1 显示已发布", "verdict_evidence_ids": ["it_q1"]},
    ensure_ascii=False,
)


class _StubClient:
    def __init__(self, content: str = _VERDICT_JSON) -> None:
        self.content = content
        self.calls = 0

    async def chat(self, messages: list[ChatMessage], **kwargs: object) -> LLMResult:
        self.calls += 1
        return LLMResult(content=self.content, model="stub")


class _BoomClient:
    async def chat(self, messages: list[ChatMessage], **kwargs: object) -> LLMResult:
        raise RuntimeError("boom")


def _session(tmp_path) -> tuple[Session, object]:
    engine = init_db(tmp_path / "t.db")
    session = Session(engine, expire_on_commit=False)
    return session, engine


def _seed_semantic_items(session: Session, published: datetime) -> None:
    for i in range(3):
        session.add(
            Item(
                id=f"it_q{i}",
                source="rss",
                title="Qwen3 开源发布引发讨论",
                summary="Qwen3 开源权重已发布",
                url=f"https://example.com/q{i}",
                content_hash=f"hq{i}",
                published_at=published,
                collected_at=published,
                hot_score=50.0,
            )
        )
    session.commit()


def _add_pred(session: Session, **kw) -> Prediction:
    base: dict = {
        "id": "pred_1",
        "date": date(2026, 5, 1),
        "statement": "Qwen3 开源发布",
        "category": "product",
        "confidence": 0.8,
        "horizon_days": 30,
        "due_date": date(2026, 5, 31),
        "falsifiable_criteria": "官方发布 Qwen3 权重即命中",
        "status": "pending",
    }
    base.update(kw)
    pred = Prediction(**base)
    session.add(pred)
    session.commit()
    return pred


async def test_quantified_path_is_zero_llm(tmp_path):
    session, engine = _session(tmp_path)
    _add_pred(
        session,
        id="pred_q",
        due_date=date(2026, 5, 31),
        criteria="github_new_repo",
        criteria_params={"owner": "acme"},
    )
    session.add(
        Signal(
            entity_type="repo",
            entity_key="acme/new",
            metric="stars",
            value=10,
            ts=datetime(2026, 5, 20, tzinfo=UTC),
        )
    )
    session.commit()

    client = _StubClient()
    out = await verify_due_predictions(
        session=session, client=client, settings=Settings(), today=TODAY, mode=RunMode.HYBRID
    )
    assert client.calls == 0  # 量化判据严禁调 LLM
    assert out.verified == 1
    row = session.get(Prediction, "pred_q")
    assert row is not None
    assert row.status == "verified"
    assert row.verdict == "hit"
    assert row.verdict_score == 1.0
    assert row.verified_by == "auto"
    session.close()
    engine.dispose()


async def test_semantic_path_hit_with_llm(tmp_path):
    session, engine = _session(tmp_path)
    _add_pred(session, id="pred_s")
    _seed_semantic_items(session, datetime(2026, 5, 20, tzinfo=UTC))

    client = _StubClient()
    out = await verify_due_predictions(
        session=session, client=client, settings=Settings(), today=TODAY, mode=RunMode.HYBRID
    )
    assert client.calls == 1
    assert out.verified == 1
    row = session.get(Prediction, "pred_s")
    assert row is not None and row.verdict == "hit" and row.verified_by == "auto"
    session.close()
    engine.dispose()


async def test_llm_failure_keeps_pending(tmp_path):
    session, engine = _session(tmp_path)
    _add_pred(session, id="pred_f")
    _seed_semantic_items(session, datetime(2026, 5, 20, tzinfo=UTC))

    out = await verify_due_predictions(
        session=session, client=_BoomClient(), settings=Settings(), today=TODAY, mode=RunMode.HYBRID
    )
    assert out.failed == 1
    assert out.verified == 0
    row = session.get(Prediction, "pred_f")
    assert row is not None
    assert row.status == "pending"  # 绝不把 LLM 失败当 miss
    assert row.verdict is None
    session.close()
    engine.dispose()


async def test_off_mode_semantic_defers_within_grace(tmp_path):
    session, engine = _session(tmp_path)
    _add_pred(session, id="pred_off", due_date=date(2026, 5, 31))  # today <= due+7

    client = _StubClient()
    out = await verify_due_predictions(
        session=session, client=client, settings=Settings(), today=TODAY, mode=RunMode.OFF
    )
    assert client.calls == 0  # off 档零 LLM
    assert out.deferred == 1
    row = session.get(Prediction, "pred_off")
    assert row is not None and row.status == "pending"
    session.close()
    engine.dispose()


async def test_off_mode_semantic_unverifiable_after_grace(tmp_path):
    session, engine = _session(tmp_path)
    _add_pred(session, id="pred_old", due_date=date(2026, 5, 1))  # today > due+7

    out = await verify_due_predictions(
        session=session, client=_StubClient(), settings=Settings(), today=TODAY, mode=RunMode.OFF
    )
    assert out.unverifiable == 1
    row = session.get(Prediction, "pred_old")
    assert row is not None
    assert row.status == "unverifiable"
    assert row.verdict is None  # unverifiable 不是 verdict
    assert row.verified_by == "auto"
    session.close()
    engine.dispose()


async def test_evidence_gate_blocks_llm(tmp_path):
    session, engine = _session(tmp_path)
    _add_pred(session, id="pred_bare", due_date=date(2026, 5, 31))  # 无任何 items

    client = _StubClient()
    out = await verify_due_predictions(
        session=session, client=client, settings=Settings(), today=TODAY, mode=RunMode.HYBRID
    )
    assert client.calls == 0  # 证据不足不得调 LLM
    assert out.deferred == 1
    row = session.get(Prediction, "pred_bare")
    assert row is not None and row.status == "pending"
    session.close()
    engine.dispose()
