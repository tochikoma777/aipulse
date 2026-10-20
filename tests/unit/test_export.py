"""M6c S3：导出引擎（MarkdownExporter / 分片 / index / 幂等）。"""

from __future__ import annotations

from pathlib import Path

from aipulse.knowledge.daily_index import DailyIndex, IndexedItem
from aipulse.knowledge.export import (
    MAX_ITEMS_PER_SHARD,
    Exporter,
    ExportItem,
    MarkdownExporter,
    build_export_items,
    export_knowledge,
    section_slug,
)
from aipulse.knowledge.models import KnowledgeItem


def _indexed(
    item_id: str,
    title: str,
    *,
    section: str = "开源项目",
    date: str = "2026-10-18",
    why: str = "",
    summary: str = "",
    url: str = "",
    source: str = "rss",
    hot_score: float = 1.0,
) -> IndexedItem:
    return IndexedItem(
        item_id=item_id,
        title=title,
        url=url or f"https://e/{item_id}",
        source=source,
        summary=summary,
        section=section,
        date=date,
        hot_score=hot_score,
        why=why,
        one_liner="",
    )


def _index(*items: IndexedItem) -> DailyIndex:
    mapping = {item.item_id: item for item in items}
    return DailyIndex(
        items=mapping,
        url_to_id={item.url: item.item_id for item in items if item.url},
        title_to_ids={item.title: [item.item_id] for item in items if item.title},
    )


def _row(item_id: str, *, note: str = "", status: str = "unread") -> KnowledgeItem:
    return KnowledgeItem(item_id=item_id, note=note, status=status)


def _export_item(**overrides: object) -> ExportItem:
    values: dict[str, object] = {
        "item_id": "it_1",
        "title": "Agent Framework",
        "url": "https://e/1",
        "source": "github_trending",
        "hot_score": 83.8,
        "section": "开源项目",
        "date": "2026-10-18",
        "why": "因为它重要",
        "one_liner": "要点",
        "note": "我的笔记",
        "status": "read",
        "summary": "原始摘要",
    }
    values.update(overrides)
    return ExportItem(**values)  # type: ignore[arg-type]


def test_exporter_protocol_and_item_render() -> None:
    exporter = MarkdownExporter()
    assert isinstance(exporter, Exporter)
    assert exporter.format == "markdown"
    assert exporter.file_ext() == ".md"

    text = exporter.render([_export_item()])
    assert "## Agent Framework" in text
    assert "- 来源：github_trending · 热度 83.8 · 发现 2026-10-18" in text
    assert "- 链接：https://e/1" in text
    assert "- 阅读状态：read" in text
    assert "**为什么重要**：因为它重要" in text
    assert "**我的笔记**：我的笔记" in text


def test_render_falls_back_to_summary_and_omits_empty_note() -> None:
    long_summary = "摘" * 400
    text = MarkdownExporter().render([_export_item(why="", note="", summary=long_summary)])
    assert "（摘要，AI 未分析）" in text
    assert "…" in text
    assert long_summary not in text
    assert "**我的笔记**" not in text


def test_build_export_items_includes_unread_and_excludes_skipped() -> None:
    index = _index(
        _indexed("it_read", "Read", why="why"),
        _indexed("it_unread", "Unread"),
        _indexed("it_skipped", "Skipped"),
    )
    rows = [
        _row("it_read", note="笔记", status="read"),
        _row("it_skipped", note="隐藏", status="skipped"),
    ]

    items = build_export_items(index, rows)
    assert {item.item_id for item in items} == {"it_read", "it_unread"}
    by_id = {item.item_id: item for item in items}
    assert by_id["it_read"].note == "笔记"
    assert by_id["it_read"].status == "read"
    assert by_id["it_unread"].status == "unread"
    assert by_id["it_unread"].note == ""

    with_skipped = build_export_items(index, rows, include_skipped=True)
    assert {item.item_id for item in with_skipped} == {
        "it_read",
        "it_unread",
        "it_skipped",
    }


def test_export_writes_tree_index_and_is_idempotent(tmp_path: Path) -> None:
    index = _index(
        _indexed("it_1", "Agent Framework", why="因为重要"),
        _indexed("it_2", "Uncategorized", section=""),
        _indexed("it_3", "Paper", section="论文与研究", date="2026-09-30"),
    )
    rows = [_row("it_1", note="这是笔记", status="read")]
    out = tmp_path / "knowledge"

    result = export_knowledge(index, rows, out)
    assert result.total_items == 3
    assert result.with_why == 1
    assert result.with_notes == 1

    expected = {
        "index.md",
        "my-notes.md",
        "topics/open-source-2026-10.md",
        "topics/uncategorized.md",
        "topics/research-2026-09.md",
    }
    assert {f.path for f in result.files} == expected - {"index.md"}
    for rel in expected:
        assert (out / rel).is_file()

    index_text = (out / "index.md").read_text(encoding="utf-8")
    for rel in expected - {"index.md"}:
        assert rel in index_text
    assert "open-source-2026-10.md" in index_text
    assert "uncategorized.md" in index_text

    notes_text = (out / "my-notes.md").read_text(encoding="utf-8")
    assert "## Agent Framework" in notes_text
    assert "这是笔记" in notes_text
    assert "## Uncategorized" not in notes_text

    topic_text = (out / "topics" / "open-source-2026-10.md").read_text(encoding="utf-8")
    assert topic_text.startswith("# 开源项目")
    assert "> 板块：open-source · 条目 1 条（含笔记 1）" in topic_text

    before = {rel: (out / rel).read_bytes() for rel in expected}
    export_knowledge(index, rows, out)
    after = {rel: (out / rel).read_bytes() for rel in expected}
    assert after == before


def test_skipped_can_be_included(tmp_path: Path) -> None:
    index = _index(_indexed("it_1", "Hidden", why="why"))
    rows = [_row("it_1", note="隐藏笔记", status="skipped")]

    excluded = export_knowledge(index, rows, tmp_path / "excluded")
    assert excluded.total_items == 0
    assert "## Hidden" not in (tmp_path / "excluded" / "my-notes.md").read_text(encoding="utf-8")

    included = export_knowledge(index, rows, tmp_path / "included", include_skipped=True)
    assert included.total_items == 1
    assert "隐藏笔记" in (tmp_path / "included" / "my-notes.md").read_text(encoding="utf-8")


def test_501_items_split_into_two_shards(tmp_path: Path) -> None:
    items = [
        _indexed(f"it_{i:04d}", f"Item {i:04d}", date="2026-10-18")
        for i in range(MAX_ITEMS_PER_SHARD + 1)
    ]
    out = tmp_path / "knowledge"

    result = export_knowledge(_index(*items), [], out)
    assert result.total_items == MAX_ITEMS_PER_SHARD + 1

    first = out / "topics" / "open-source-2026-10.md"
    second = out / "topics" / "open-source-2026-10-2.md"
    assert first.is_file()
    assert second.is_file()

    index_text = (out / "index.md").read_text(encoding="utf-8")
    assert "open-source-2026-10.md" in index_text
    assert "open-source-2026-10-2.md" in index_text
    assert "| `topics/open-source-2026-10.md` | 开源项目 | 500 |" in index_text
    assert "| `topics/open-source-2026-10-2.md` | 开源项目 | 1 |" in index_text


def test_section_slug_mapping_and_uncategorized() -> None:
    assert section_slug("") == "uncategorized"
    assert section_slug("开源项目") == "open-source"
    assert section_slug("论文与研究") == "research"
    assert section_slug("社区舆论") == "community"
    assert section_slug("产业与新闻") == "industry"
    assert section_slug("Custom Section") == "custom-section"
    assert section_slug("自定义板块").startswith("section-")


def test_200kb_threshold_triggers_split(tmp_path: Path) -> None:
    big = "x" * 110_000
    items = [_indexed(f"it_{i}", f"Big {i}", why=big, date="2026-10-18") for i in range(3)]
    out = tmp_path / "knowledge"

    result = export_knowledge(_index(*items), [], out)
    assert result.total_items == 3

    files = sorted((out / "topics").glob("open-source-2026-10*.md"))
    assert len(files) == 3
    assert all(path.stat().st_size <= 200 * 1024 for path in files)
