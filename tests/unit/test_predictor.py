"""reasoning/predictor.py 单测：off 档、合法批量入库、模糊措辞触发重写、仍不合法丢弃。"""

from __future__ import annotations

import json
from datetime import date

from aipulse.core.config import RunMode, Settings
from aipulse.llm.base import ChatMessage, LLMResult
from aipulse.reasoning.predictor import generate_predictions
from aipulse.store.models import Item, Topic


class _StubClient:
    """顺序返回预置内容（JSON 字符串），记录调用次数。"""

    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.calls = 0

    async def chat(self, messages: list[ChatMessage], **kwargs) -> LLMResult:
        content = self.contents[min(self.calls, len(self.contents) - 1)]
        self.calls += 1
        return LLMResult(content=content, model="deepseek-reasoner")


def _item(item_id: str, title: str, hot: float) -> Item:
    return Item(
        id=item_id,
        source="github_trending",
        content_hash=f"h-{item_id}",
        title=title,
        hot_score=hot,
    )


def _items() -> list[Item]:
    return [_item("it_1", "开源推理框架爆发", 95.0), _item("it_2", "某模型发布", 90.0)]


def _topics() -> list[Topic]:
    return [Topic(id="tp_1", name="推理", date=date(2026, 10, 14), item_count=2)]


def _batch(statement: str, evidence: list[str] | None = None) -> str:
    return json.dumps(
        {
            "predictions": [
                {
                    "statement": statement,
                    "category": "product",
                    "confidence": 0.75,
                    "horizon_days": 30,
                    "falsifiable_criteria": "截至到期日，GitHub 出现 ≥2 个 star>2000 的实现即命中",
                    "rationale": "证据充分。",
                    "evidence_item_ids": evidence or ["it_1", "it_2"],
                }
            ]
        },
        ensure_ascii=False,
    )


async def test_off_mode_returns_empty_without_llm():
    client = _StubClient(["{}"])
    settings = Settings()
    out = await generate_predictions(
        client=client,
        settings=settings,
        items=_items(),
        topics=_topics(),
        entity_counts={},
        day=date(2026, 10, 14),
        mode=RunMode.OFF,
    )
    assert out.predictions == []
    assert out.meta["mode"] == "off"
    assert client.calls == 0


async def test_valid_batch_generates_rows():
    client = _StubClient([_batch("推理框架将在 30 天内全面超越闭源")])
    settings = Settings()
    out = await generate_predictions(
        client=client,
        settings=settings,
        items=_items(),
        topics=_topics(),
        entity_counts={},
        day=date(2026, 10, 14),
        mode=RunMode.HYBRID,
    )
    assert len(out.predictions) == 1
    row = out.predictions[0]
    assert row.origin == "llm"
    assert row.status == "pending"
    assert row.confidence == 0.75
    assert row.horizon_days == 30
    assert row.due_date == date(2026, 11, 13)
    assert row.prompt_version  # 模板 hash 已写入
    assert len(row.evidence_item_ids) == 2


async def test_vague_statement_triggers_rewrite_and_recovers():
    client = _StubClient(
        [
            _batch("推理框架未来可能会超越闭源"),  # 第一轮：含"可能"
            _batch("推理框架将在 30 天内全面超越闭源"),  # 重写后：合法
        ]
    )
    settings = Settings()
    out = await generate_predictions(
        client=client,
        settings=settings,
        items=_items(),
        topics=_topics(),
        entity_counts={},
        day=date(2026, 10, 14),
        mode=RunMode.HYBRID,
    )
    assert client.calls == 2  # 原始 + 一次重写
    assert len(out.predictions) == 1
    assert out.meta["dropped"] == []


async def test_still_invalid_after_rewrite_is_dropped():
    client = _StubClient([_batch("推理框架未来可能会超越闭源"), _batch("多模态技术未来可期")])
    settings = Settings()
    out = await generate_predictions(
        client=client,
        settings=settings,
        items=_items(),
        topics=_topics(),
        entity_counts={},
        day=date(2026, 10, 14),
        mode=RunMode.HYBRID,
    )
    assert client.calls == 2
    assert out.predictions == []
    assert len(out.meta["dropped"]) == 1


async def test_missing_falsifiable_criteria_dropped():
    # 缺 falsifiable_criteria 的条目（红线）必须被拦截，即便触发重写也丢弃
    bad = json.dumps(
        {
            "predictions": [
                {
                    "statement": "推理框架将全面超越闭源",
                    "category": "product",
                    "confidence": 0.7,
                    "horizon_days": 30,
                    "falsifiable_criteria": "",
                    "evidence_item_ids": ["it_1", "it_2"],
                }
            ]
        },
        ensure_ascii=False,
    )
    client = _StubClient([bad, bad])
    settings = Settings()
    out = await generate_predictions(
        client=client,
        settings=settings,
        items=_items(),
        topics=_topics(),
        entity_counts={},
        day=date(2026, 10, 14),
        mode=RunMode.HYBRID,
    )
    assert out.predictions == []
    assert len(out.meta["dropped"]) == 1
