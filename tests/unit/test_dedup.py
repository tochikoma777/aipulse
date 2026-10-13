"""三级去重单测（设计 §6.2）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aipulse.core.timeutil import utcnow
from aipulse.normalize.dedup import dedup_items, merge_items
from aipulse.schema.items import RawItem, SourceEnum, SourceMetrics

BASE = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)


def _item(
    source: SourceEnum,
    url: str,
    *,
    title: str = "Title",
    summary: str = "",
    published_at: datetime | None = None,
    metrics: SourceMetrics | None = None,
    extra: dict | None = None,
    tags: list[str] | None = None,
) -> RawItem:
    return RawItem(
        source=source,
        external_id=url,
        title=title,
        url=url,
        summary=summary,
        published_at=published_at or BASE,
        metrics=metrics or SourceMetrics(),
        tags=tags or [],
        extra=extra or {},
    )


def test_l1_drops_same_source_duplicate_url():
    items = [_item(SourceEnum.RSS, "https://e.com/a"), _item(SourceEnum.RSS, "https://e.com/a")]
    result, stats = dedup_items(items)
    assert len(result) == 1
    assert stats.l1_dropped == 1


def test_l2_merges_arxiv_and_hf_same_paper():
    """DoD 核心：arXiv 与 HF 的同一篇论文必须合并为 1 条，seen_in 含两个源。"""
    items = [
        _item(
            SourceEnum.ARXIV,
            "arxiv:2501.12345",
            title="A great paper",
            summary="abstract",
            metrics=SourceMetrics(),
            tags=["cs.LG"],
        ),
        _item(
            SourceEnum.HF_PAPERS,
            "arxiv:2501.12345",
            title="A great paper",
            summary="abstract from hf",
            metrics=SourceMetrics(upvotes=42),
            extra={"arxiv_id": "2501.12345"},
        ),
    ]
    result, stats = dedup_items(items)
    assert len(result) == 1
    assert result[0].seen_in == ["arxiv", "hf_papers"]
    assert result[0].metrics.upvotes == 42  # 指标合并取有效值
    assert result[0].extra["cross_source"] is True
    assert result[0].extra["cross_source_bonus"] > 0
    assert stats.l2_merged == 1


def test_l2_merges_repo_across_rss_and_github():
    items = [
        _item(SourceEnum.GITHUB_TRENDING, "https://github.com/owner/repo", title="owner/repo"),
        _item(SourceEnum.HACKERNEWS, "https://github.com/owner/repo", title="Show HN: repo"),
    ]
    result, _ = dedup_items(items)
    assert len(result) == 1
    assert set(result[0].seen_in) == {"github_trending", "hackernews"}


def test_l3_merges_near_duplicate_titles():
    items = [
        _item(SourceEnum.RSS, "https://a.com/1", title="OpenAI 发布 GPT-5，推理能力大幅提升"),
        _item(SourceEnum.RSS, "https://b.com/2", title="OpenAI 发布 GPT-5，推理能力大幅提升！"),
    ]
    result, stats = dedup_items(items)
    assert len(result) == 1
    assert stats.l3_merged == 1


def test_l3_keeps_unrelated_items():
    items = [
        _item(SourceEnum.RSS, "https://a.com/1", title="OpenAI 发布 GPT-5，推理能力大幅提升"),
        _item(SourceEnum.RSS, "https://b.com/2", title="vLLM 新版本吞吐翻倍，显存占用下降"),
    ]
    result, _ = dedup_items(items)
    assert len(result) == 2


def test_merge_rules_earliest_publish_largest_summary_union_tags():
    early = _item(
        SourceEnum.ARXIV,
        "arxiv:2501.9",
        summary="short",
        published_at=BASE,
        tags=["cs.AI"],
    )
    late = _item(
        SourceEnum.HF_PAPERS,
        "arxiv:2501.9",
        summary="a much longer summary body",
        published_at=BASE + timedelta(hours=5),
        tags=["cs.CL"],
    )
    merged = merge_items([early, late])
    assert merged.published_at == BASE  # 保留最早发布
    assert merged.summary == "a much longer summary body"  # 保留信息量最大
    assert set(merged.tags) == {"cs.AI", "cs.CL"}


def test_title_only_flag_is_conservative_on_merge():
    """只要有一个源有正文，合并后就不算"仅标题"，避免量子位条目污染聚类判定。"""
    title_only = _item(SourceEnum.RSS, "arxiv:2501.77", extra={"title_only": True}, tags=[])
    rich = _item(SourceEnum.ARXIV, "arxiv:2501.77", extra={"title_only": False})
    merged = merge_items([title_only, rich])
    assert merged.extra["title_only"] is False


def test_dedup_empty_input():
    result, stats = dedup_items([])
    assert result == []
    assert stats.input_count == 0 and stats.output_count == 0


def test_dedup_keeps_distinct_items():
    """标题各异、无跨源键 → 一条都不该被合并。"""
    now = utcnow()
    items = [
        _item(
            SourceEnum.RSS,
            f"https://e.com/{i}",
            title=f"独立事件 {i}：第 {i} 个不同主题的消息",
            published_at=now - timedelta(hours=i),
        )
        for i in range(5)
    ]
    result, _ = dedup_items(items)
    assert len(result) == 5


def test_l3_merges_identical_titles_from_different_urls():
    """同一标题、不同 URL（转载/镜像）应被判为同一事件。"""
    items = [
        _item(SourceEnum.RSS, "https://a.com/x", title="Same story everywhere"),
        _item(SourceEnum.RSS, "https://b.com/y", title="Same story everywhere"),
    ]
    result, stats = dedup_items(items)
    assert len(result) == 1 and stats.l3_merged == 1
