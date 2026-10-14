"""主题聚类单测（设计方案 §9.2）。"""

from __future__ import annotations

from datetime import UTC, date, datetime

from aipulse.analysis.cluster import cluster_items, tokenize
from aipulse.store.models import Item


def _item(id_: str, title: str, summary: str = "", *, skip_cluster=False, hot_score=50.0):
    return Item(
        id=id_,
        source="rss",
        external_id=f"ext-{id_}",
        title=title,
        url=f"https://example.com/{id_}",
        summary=summary,
        published_at=datetime.now(tz=UTC),
        metrics={},
        seen_in=["rss"],
        skip_cluster=skip_cluster,
        hot_score=hot_score,
    )


def test_tokenize_cjk_uses_jieba():
    tokens = tokenize("大语言模型推理加速")
    assert " " in tokens  # jieba 切成多个词，空格分隔
    assert len(tokens.split()) > 1


def test_cluster_groups_similar_items():
    a = _item("a", "OpenAI GPT-5 model release", "GPT-5 new language model released")
    b = _item("b", "OpenAI GPT-5 announced", "GPT-5 new language model announced")
    c = _item("c", "vLLM inference engine v1", "high performance inference serving")
    topics, mapping = cluster_items([a, b, c], day=date.today())
    # a 与 b 相似 → 同主题；c 独立 → 不落库（单点簇）
    assert mapping.get("a") == mapping.get("b")
    assert mapping.get("a") is not None
    assert len(topics) == 1
    assert topics[0].item_count == 2


def test_cluster_excludes_skip_cluster():
    a = _item("a", "OpenAI GPT-5 release", "GPT-5 new model")
    b = _item("b", "OpenAI GPT-5 release", "GPT-5 new model", skip_cluster=True)
    topics, mapping = cluster_items([a, b], day=date.today())
    # 仅标题源条目不参与聚类：只剩 a 一个可聚类 → 单点簇 → 不落库
    assert topics == []
    assert mapping == {}


def test_cluster_singleton_not_persisted():
    topics, mapping = cluster_items([_item("a", "unique topic alone")], day=date.today())
    assert topics == []
    assert mapping == {}
