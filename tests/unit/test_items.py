from datetime import UTC, datetime, timedelta, timezone

from aipulse.schema.items import RawItem, SourceEnum, SourceMetrics


def test_source_enum_values_match_config_keys():
    assert {s.value for s in SourceEnum} == {
        "github_trending",
        "arxiv",
        "hf_papers",
        "hackernews",
        "reddit",
        "rss",
        "inbox",
    }
    assert SourceEnum.GITHUB_TRENDING.display_name == "GitHub Trending"
    assert SourceEnum.INBOX.display_name == "手动投喂"


def test_raw_item_defaults_and_utc_normalization():
    item = RawItem(
        source=SourceEnum.ARXIV,
        external_id="2501.12345",
        title="A paper",
        url="https://arxiv.org/abs/2501.12345",
        published_at=datetime(2026, 10, 12, 8, 0, tzinfo=timezone(timedelta(hours=8))),
    )
    assert item.summary == ""
    assert item.metrics.upvotes is None
    assert item.normalized_published_at() == datetime(2026, 10, 12, 0, 0, tzinfo=UTC)

    naive = RawItem(
        source=SourceEnum.RSS,
        external_id="x",
        title="t",
        url="u",
        published_at=datetime(2026, 10, 12, 8, 0),
    )
    assert naive.normalized_published_at().tzinfo == UTC


def test_source_metrics_keeps_missing_as_none():
    # Reddit RSS 无 score：必须保持 None（而不是 0），才能触发打分层降权与位次补偿
    metrics = SourceMetrics(num_comments=12, rank_score=0.8)
    assert metrics.score is None
    assert metrics.rank_score == 0.8
    assert metrics.model_dump()["num_comments"] == 12
