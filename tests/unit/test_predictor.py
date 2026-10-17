"""reasoning/predictor.py 单测：off 档、合法批量入库、模糊措辞触发重写、仍不合法丢弃。"""

from __future__ import annotations

import json
from datetime import date

import httpx

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


class _TimeoutClient:
    """模拟 LLM 读超时（Actions 首跑 hybrid 时的真实故障）。"""

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages: list[ChatMessage], **kwargs) -> LLMResult:
        self.calls += 1
        raise httpx.ReadTimeout("")


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


async def test_timeout_is_degraded_not_failed():
    """读超时 = 本次未生成（warning），不能记成 llm_failed（error）。

    超时是网络抖动 / 模型慢，不是模型判错；预言按天生成，明天会自然重跑。
    混进失败口径会让记分板的"生成失败率"看起来像模型问题。
    """
    client = _TimeoutClient()
    out = await generate_predictions(
        client=client,
        settings=Settings(),
        items=_items(),
        topics=_topics(),
        entity_counts={},
        day=date(2026, 10, 14),
        mode=RunMode.HYBRID,
    )
    assert out.predictions == []
    assert out.meta["degraded"] is True
    assert "超时" in out.meta["degraded_reason"]
    assert "失败" not in out.meta["degraded_reason"]


async def test_evidence_pool_injected_into_prompt():
    """预防层：候选池必须真的出现在 prompt 里，否则"只能引用这些 id"是空话。"""

    class _CaptureClient(_StubClient):
        def __init__(self, contents: list[str]) -> None:
            super().__init__(contents)
            self.messages: list[str] = []

        async def chat(self, messages, **kwargs):  # noqa: ANN001, ANN003
            self.messages = [m.content for m in messages]
            return await super().chat(messages, **kwargs)

    client = _CaptureClient([_batch("推理框架将在 30 天内全面超越闭源")])
    await generate_predictions(
        client=client,
        settings=Settings(),
        items=_items(),
        topics=_topics(),
        entity_counts={},
        day=date(2026, 10, 14),
        mode=RunMode.HYBRID,
    )
    rendered = client.messages[0]
    assert "候选证据池" in rendered
    assert "[it_1]" in rendered and "[it_2]" in rendered


async def test_fabricated_evidence_id_is_dropped_after_rewrite():
    """兜底层：模型编了池外 id → 一次重写 → 仍不改 → 拒收并记录理由。"""
    client = _StubClient(
        [
            _batch("推理框架将在 30 天内全面超越闭源", evidence=["it_1", "it_fake"]),
            _batch("推理框架将在 30 天内全面超越闭源", evidence=["it_1", "it_fake2"]),
        ]
    )
    out = await generate_predictions(
        client=client,
        settings=Settings(),
        items=_items(),
        topics=_topics(),
        entity_counts={},
        day=date(2026, 10, 14),
        mode=RunMode.HYBRID,
    )
    assert out.predictions == []
    assert len(out.meta["dropped"]) == 1
    problems = " ".join(out.meta["dropped"][0]["problems"])
    assert "不在候选池" in problems


async def test_tiny_evidence_pool_skips_llm_call():
    """池子凑不出 2 条证据时别浪费调用：生成出来也必然被拒收。"""
    client = _StubClient([_batch("推理框架将在 30 天内全面超越闭源")])
    out = await generate_predictions(
        client=client,
        settings=Settings(),
        items=[_item("it_1", "只有一条", 10.0)],
        topics=_topics(),
        entity_counts={},
        day=date(2026, 10, 14),
        mode=RunMode.HYBRID,
    )
    assert client.calls == 0
    assert out.predictions == []
    assert "候选证据池不足" in out.meta["degraded_reason"]


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


async def test_candidate_pool_is_capped_and_title_only():
    """v1.16：候选池 Top 20，且只给 id+标题（不注入摘要）。"""
    items = []
    for i in range(30):
        item = _item(f"it_{i}", f"title {i}", 100.0 - i)
        item.summary = "SECRET_SUMMARY_SHOULD_NOT_BE_IN_PROMPT"
        items.append(item)

    class _Capture(_StubClient):
        def __init__(self) -> None:
            super().__init__(
                [_batch("推理框架将在 30 天内全面超越闭源", evidence=["it_0", "it_1"])]
            )
            self.rendered = ""

        async def chat(self, messages, **kwargs):  # noqa: ANN001, ANN003
            self.rendered = messages[0].content
            return await super().chat(messages, **kwargs)

    client = _Capture()
    out = await generate_predictions(
        client=client,
        settings=Settings(),
        items=items,
        topics=_topics(),
        entity_counts={},
        day=date(2026, 10, 14),
        mode=RunMode.HYBRID,
    )
    assert out.meta["candidate_pool"] == 20
    assert "it_19" in client.rendered
    assert "it_20" not in client.rendered
    assert "SECRET_SUMMARY_SHOULD_NOT_BE_IN_PROMPT" not in client.rendered


async def test_predict_passes_tiered_max_tokens_to_client():
    """v1.16：配置的 strong max_tokens 必须真的透传（不能变成死配置）。"""
    settings = Settings(llm={"max_tokens_strong": 9999})

    class _Capture(_StubClient):
        def __init__(self) -> None:
            super().__init__([_batch("推理框架将在 30 天内全面超越闭源")])
            self.max_tokens: int | None = None

        async def chat(self, messages, **kwargs):  # noqa: ANN001, ANN003
            self.max_tokens = kwargs.get("max_tokens")
            return await super().chat(messages, **kwargs)

    client = _Capture()
    await generate_predictions(
        client=client,
        settings=settings,
        items=_items(),
        topics=_topics(),
        entity_counts={},
        day=date(2026, 10, 14),
        mode=RunMode.HYBRID,
    )
    assert client.max_tokens == 9999
