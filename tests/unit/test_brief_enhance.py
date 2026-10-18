"""M6b 条目增强单测：缓存命中 / 版本失效 / 渲染集对齐 / 批次失败隔离。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from aipulse.core.config import RunMode, Settings
from aipulse.llm.base import ChatMessage, LLMResult
from aipulse.llm.prompt import load_prompt
from aipulse.reasoning.brief import _enhance_comments, _render_ids
from aipulse.schema.brief import DailyBrief, Section
from aipulse.store.models import Item, ItemEnhance


def _item(item_id: str, hot_score: float = 50.0) -> Item:
    return Item(
        id=item_id,
        source="github_trending",
        external_id=f"owner/{item_id}",
        title=f"title-{item_id}",
        url=f"https://example.com/{item_id}",
        summary="summary",
        content_hash=f"hash-{item_id}",
        hot_score=hot_score,
        published_at=datetime.now(tz=UTC),
        metrics={},
        seen_in=["github_trending"],
    )


def _settings(tmp_path: Any, **brief: Any) -> Settings:
    return Settings(
        mode=RunMode.FULL,
        llm={"api_key": "sk-test", "base_url": "https://api.example.com/v1"},
        app={"data_dir": str(tmp_path / "data")},
        brief=brief,
    )


def _session(tmp_path: Any) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'enhance.db'}")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


class ScriptedLLM:
    """按 purpose 返回合法 JSON 的桩；可指定前 N 次调用故意失败。"""

    def __init__(self, ids: list[str], *, fail_first: dict[str, int] | None = None) -> None:
        self.ids = ids
        self.fail_first = fail_first or {}
        self.calls: list[str] = []

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int = 2000,
        purpose: str = "general",
        model_tier: str = "fast",
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        self.calls.append(purpose)
        seen = self.calls.count(purpose)
        if seen <= self.fail_first.get(purpose, 0):
            return LLMResult(content="这不是 JSON", model="fake")
        if purpose == "brief_item_comment":
            payload = {"one_liners": [{"item_id": i, "one_liner": f"要点-{i}"} for i in self.ids]}
        else:
            payload = {
                "comments": [{"item_id": i, "why": f"重要-{i}", "stance": "看好"} for i in self.ids]
            }
        return LLMResult(
            content=json.dumps(payload, ensure_ascii=False),
            model="fake",
            prompt_tokens=100,
            completion_tokens=50,
        )


def _fresh_row(item: Item, *, one_liner_ver: str | None = None) -> ItemEnhance:
    return ItemEnhance(
        item_id=item.id,
        one_liner=f"缓存要点-{item.id}",
        why=f"缓存理由-{item.id}",
        stance="缓存立场",
        content_hash=item.content_hash,
        last_hot_score=item.hot_score,
        signals_count=0,
        model="fake",
        one_liner_ver=one_liner_ver or load_prompt("brief/item_comment").version_hash,
        enhance_ver=load_prompt("brief/item_enhance").version_hash,
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )


async def test_cache_hit_makes_no_llm_calls(tmp_path):
    """① 四条缓存条件全满足 → 0 次模型调用，值直接来自库。"""
    items = {i: _item(i) for i in ("a", "b")}
    brief = DailyBrief(sections=[Section(name="开源项目", item_ids=["a", "b"])])
    settings = _settings(tmp_path)
    session = _session(tmp_path)
    for item in items.values():
        session.add(_fresh_row(item))
    session.commit()

    llm = ScriptedLLM(list(items))
    meta: dict[str, Any] = {}
    comments = await _enhance_comments(
        client=llm,
        session=session,
        settings=settings,
        brief=brief,
        items=items,
        mode=RunMode.HYBRID,
        meta=meta,
    )

    assert llm.calls == []
    assert meta == {
        "enhance_total": 2,
        "enhanced": 2,
        "enhance_skipped_count": 0,
        "enhance_cache_hit": 2,
        "enhance_cost_cny": 0.0,
    }
    assert [(c.item_id, c.one_liner, c.why, c.stance) for c in comments] == [
        ("a", "缓存要点-a", "缓存理由-a", "缓存立场"),
        ("b", "缓存要点-b", "缓存理由-b", "缓存立场"),
    ]


async def test_prompt_version_change_invalidates_cache(tmp_path):
    """② prompt 版本变化 → 缓存失效，两次调用重新生成。"""
    items = {"a": _item("a")}
    brief = DailyBrief(sections=[Section(name="开源项目", item_ids=["a"])])
    settings = _settings(tmp_path)
    session = _session(tmp_path)
    session.add(_fresh_row(items["a"], one_liner_ver="stale000"))
    session.commit()

    llm = ScriptedLLM(list(items))
    comments = await _enhance_comments(
        client=llm,
        session=session,
        settings=settings,
        brief=brief,
        items=items,
        mode=RunMode.HYBRID,
        meta={},
    )

    assert llm.calls == ["brief_item_comment", "brief_item_enhance"]
    assert comments[0].one_liner == "要点-a"
    assert comments[0].why == "重要-a"


async def test_render_set_matches_section_slices(tmp_path):
    """③ 增强覆盖的条目 == 各板块 item_ids[:limit] 的顺序拼接（含跨板块去重）。"""
    brief = DailyBrief(
        sections=[
            Section(name="开源项目", item_ids=["a", "b", "c"]),
            Section(name="社区舆论", item_ids=["c", "d"]),
        ]
    )
    assert _render_ids(brief, 2) == ["a", "b", "c", "d"]

    items = {i: _item(i) for i in ("a", "b", "c", "d", "e")}
    settings = _settings(tmp_path, max_items_per_section=2)
    session = _session(tmp_path)
    llm = ScriptedLLM(list(items))
    comments = await _enhance_comments(
        client=llm,
        session=session,
        settings=settings,
        brief=brief,
        items=items,
        mode=RunMode.FULL,
        meta={},
    )

    assert [c.item_id for c in comments] == ["a", "b", "c", "d"]


async def test_one_batch_failure_keeps_other_batches(tmp_path):
    """④ 首批两次调用都失败 → 只丢该批；第二批照常产出，meta 标 degraded。"""
    ids = [f"i{n}" for n in range(15)]
    items = {i: _item(i) for i in ids}
    brief = DailyBrief(sections=[Section(name="开源项目", item_ids=ids)])
    # 渲染集要先容得下 15 条（默认每板块 10 条），否则第二批根本不存在
    settings = _settings(tmp_path, enhance_batch_size=10, max_items_per_section=15)
    session = _session(tmp_path)
    llm = ScriptedLLM(ids, fail_first={"brief_item_comment": 2, "brief_item_enhance": 2})
    meta: dict[str, Any] = {}

    comments = await _enhance_comments(
        client=llm,
        session=session,
        settings=settings,
        brief=brief,
        items=items,
        mode=RunMode.FULL,
        meta=meta,
    )

    by_id = {c.item_id: c for c in comments}
    # 第一批（前 10 条）失败：字段留空，交给渲染层显示 —
    assert by_id["i0"].one_liner == "" and by_id["i0"].why == ""
    # 第二批（后 5 条）正常产出
    assert by_id["i14"].one_liner == "要点-i14"
    assert by_id["i14"].why == "重要-i14"
    assert meta.get("degraded") is True
    # 4 次失败调用（两 purpose 各 2 次）+ 2 次成功调用
    assert len(llm.calls) == 6


async def test_ttl_expiry_triggers_refresh(tmp_path):
    """补：TTL 过期也算未命中（缓存四条的第三条）。"""
    items = {"a": _item("a")}
    brief = DailyBrief(sections=[Section(name="开源项目", item_ids=["a"])])
    settings = _settings(tmp_path, enhance_ttl_days=1)
    session = _session(tmp_path)
    row = _fresh_row(items["a"])
    row.updated_at = datetime.now(tz=UTC) - timedelta(days=3)
    session.add(row)
    session.commit()

    llm = ScriptedLLM(list(items))
    await _enhance_comments(
        client=llm,
        session=session,
        settings=settings,
        brief=brief,
        items=items,
        mode=RunMode.HYBRID,
        meta={},
    )

    assert llm.calls == ["brief_item_comment", "brief_item_enhance"]


async def test_full_mode_ignores_cache(tmp_path):
    """S4.0：full 强制全刷 —— 缓存完整也要重新调用。"""
    items = {"a": _item("a")}
    brief = DailyBrief(sections=[Section(name="开源项目", item_ids=["a"])])
    settings = _settings(tmp_path)
    session = _session(tmp_path)
    session.add(_fresh_row(items["a"]))
    session.commit()

    llm = ScriptedLLM(list(items))
    comments = await _enhance_comments(
        client=llm,
        session=session,
        settings=settings,
        brief=brief,
        items=items,
        mode=RunMode.FULL,
        meta={},
    )

    assert llm.calls == ["brief_item_comment", "brief_item_enhance"]
    assert comments[0].one_liner == "要点-a"  # 来自模型，而非 "缓存要点-a"
