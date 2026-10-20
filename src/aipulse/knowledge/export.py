"""M6c 知识库导出引擎。

只依赖 daily_index 与 user_data.db 的笔记行；不碰主库、不调 LLM。
Markdown 是唯一 renderer；将来加格式 = 新增一个 Exporter 实现。
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from aipulse.knowledge.daily_index import DailyIndex
from aipulse.knowledge.models import KnowledgeItem
from aipulse.utils.text import truncate_summary

MAX_ITEMS_PER_SHARD = 500
MAX_BYTES_PER_SHARD = 200 * 1024

SECTION_SLUGS = {
    "开源项目": "open-source",
    "论文与研究": "research",
    "社区舆论": "community",
    "产业与新闻": "industry",
}


@dataclass(frozen=True)
class ExportItem:
    item_id: str
    title: str
    url: str
    source: str
    hot_score: float
    section: str
    date: str
    why: str
    one_liner: str
    note: str
    status: str
    summary: str


@dataclass(frozen=True)
class ExportFile:
    path: str
    section: str
    slug: str
    item_count: int
    note_count: int
    size_bytes: int
    update: str


@dataclass(frozen=True)
class ExportResult:
    out_dir: Path
    total_items: int
    with_why: int
    with_notes: int
    files: tuple[ExportFile, ...]


@runtime_checkable
class Exporter(Protocol):
    format: str

    def render(self, items: list[ExportItem]) -> str: ...

    def file_ext(self) -> str: ...


class MarkdownExporter:
    format = "markdown"

    def file_ext(self) -> str:
        return ".md"

    def render(self, items: list[ExportItem]) -> str:
        return "\n\n".join(self._render_item(item) for item in items)

    def _render_item(self, item: ExportItem) -> str:
        why = item.why.strip()
        if not why:
            summary = truncate_summary(item.summary)
            why = f"{summary}（摘要，AI 未分析）" if summary else "（摘要，AI 未分析）"

        lines = [
            f"## {item.title or '—'}",
            f"- 来源：{item.source or '—'} · 热度 {item.hot_score:.1f} · 发现 {item.date or '—'}",
            f"- 链接：{item.url or '—'}",
            f"- 阅读状态：{item.status}",
            "",
            f"**为什么重要**：{why}",
        ]
        note = item.note.strip()
        if note:
            lines.extend(["", f"**我的笔记**：{note}"])
        return "\n".join(lines)


def section_slug(name: str) -> str:
    """板块名 → 文件名 slug；空板块统一 uncategorized。"""
    value = name.strip()
    if not value:
        return "uncategorized"
    if value in SECTION_SLUGS:
        return SECTION_SLUGS[value]
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if slug:
        return slug
    # 未知中文板块：稳定短哈希，避免文件名里出现中文/空串
    return "section-" + hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]


def _section_name(name: str) -> str:
    return name.strip() or "未分类"


def _month(date: str) -> str:
    return date[:7] if re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", date) else "undated"


def _update_date(items: Iterable[ExportItem]) -> str:
    dates = [item.date for item in items if item.date]
    return max(dates) if dates else "—"


def _note_count(items: Iterable[ExportItem]) -> int:
    return sum(1 for item in items if item.note.strip())


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _header_text(
    section_name: str,
    slug: str,
    item_count: int,
    note_count: int,
    update: str,
) -> str:
    return "\n".join(
        [
            f"# {section_name}",
            (f"> 板块：{slug} · 条目 {item_count} 条（含笔记 {note_count}）· 更新 {update or '—'}"),
            "> 本文件由 aipulse 自动生成，可直接喂给任意 AI 工具。",
        ]
    )


def _section_header(section_name: str, slug: str, items: list[ExportItem]) -> str:
    return _header_text(
        section_name,
        slug,
        len(items),
        _note_count(items),
        _update_date(items),
    )


def _my_notes_header(items: list[ExportItem]) -> str:
    return "\n".join(
        [
            "# 我的笔记",
            f"> 条目 {len(items)} 条（含笔记 {_note_count(items)}）· 更新 {_update_date(items)}",
            "> 本文件由 aipulse 自动生成，可直接喂给任意 AI 工具。",
        ]
    )


def _index_header(items: list[ExportItem], with_why: int) -> str:
    return "\n".join(
        [
            "# 知识库导出索引",
            (
                f"> 条目总数：{len(items)} · 带 why：{with_why} · "
                f"带笔记：{sum(1 for item in items if item.note.strip())} · "
                f"更新时间：{_update_date(items)}"
            ),
            "> 本文件由 aipulse 自动生成，可直接喂给任意 AI 工具。",
        ]
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def _chunks(
    items: list[ExportItem], *, section_name: str, slug: str, exporter: Exporter
) -> list[list[ExportItem]]:
    """按 500 条或 200KB 切片；逐项渲染只做一次，避免 O(n²)。"""
    chunks: list[list[ExportItem]] = []
    current: list[ExportItem] = []
    current_bytes = 0
    current_notes = 0
    current_update = ""

    for item in items:
        block = exporter.render([item])
        block_bytes = len(block.encode("utf-8"))
        item_note = 1 if item.note.strip() else 0
        candidate_count = len(current) + 1
        candidate_notes = current_notes + item_note
        candidate_update = max(filter(None, [current_update, item.date]), default="")
        header = _header_text(
            section_name, slug, candidate_count, candidate_notes, candidate_update
        )
        candidate_bytes = (
            len((header + "\n\n").encode("utf-8"))
            + current_bytes
            + (2 if current else 0)
            + block_bytes
            + 1
        )
        too_many = candidate_count > MAX_ITEMS_PER_SHARD
        too_big = candidate_bytes > MAX_BYTES_PER_SHARD

        if current and (too_many or too_big):
            chunks.append(current)
            current = [item]
            current_bytes = block_bytes
            current_notes = item_note
            current_update = item.date
        else:
            current.append(item)
            current_bytes += (2 if len(current) > 1 else 0) + block_bytes
            current_notes = candidate_notes
            current_update = candidate_update

    if current:
        chunks.append(current)
    return chunks


def _shard_name(base: str, index: int, ext: str) -> str:
    return f"{base}{ext}" if index == 1 else f"{base}-{index}{ext}"


def build_export_items(
    index: DailyIndex,
    notes: Iterable[KnowledgeItem],
    *,
    include_skipped: bool = False,
) -> list[ExportItem]:
    """daily_index 全量条目 + 用户笔记/状态；skipped 默认排除。"""
    rows = {row.item_id: row for row in notes}
    items: list[ExportItem] = []
    for indexed in index.items.values():
        row = rows.get(indexed.item_id)
        status = (row.status if row else "unread") or "unread"
        if status == "skipped" and not include_skipped:
            continue
        items.append(
            ExportItem(
                item_id=indexed.item_id,
                title=indexed.title,
                url=indexed.url,
                source=indexed.source,
                hot_score=indexed.hot_score,
                section=indexed.section,
                date=indexed.date,
                why=indexed.why,
                one_liner=indexed.one_liner,
                note=(row.note if row else ""),
                status=status,
                summary=indexed.summary,
            )
        )
    items.sort(key=lambda item: (item.date, item.hot_score, item.title, item.item_id), reverse=True)
    return items


def export_knowledge(
    index: DailyIndex,
    notes: Iterable[KnowledgeItem],
    out_dir: str | Path,
    *,
    include_skipped: bool = False,
    exporter: Exporter | None = None,
) -> ExportResult:
    """把索引 + 笔记写成 data/knowledge/ 下的 Markdown 文件树。"""
    renderer = exporter or MarkdownExporter()
    items = build_export_items(index, notes, include_skipped=include_skipped)
    out = Path(out_dir)
    topics_dir = out / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)

    groups: dict[tuple[str, str, str], list[ExportItem]] = {}
    for item in items:
        slug = section_slug(item.section)
        name = _section_name(item.section)
        month = "" if slug == "uncategorized" else _month(item.date)
        groups.setdefault((slug, name, month), []).append(item)

    exported: list[ExportFile] = []
    ext = renderer.file_ext()
    for slug, name, month in sorted(groups):
        base = slug if slug == "uncategorized" else f"{slug}-{month}"
        chunks = _chunks(
            groups[(slug, name, month)], section_name=name, slug=slug, exporter=renderer
        )
        for index_num, chunk in enumerate(chunks, start=1):
            filename = _shard_name(base, index_num, ext)
            path = topics_dir / filename
            content = _section_header(name, slug, chunk) + "\n\n" + renderer.render(chunk)
            _write(path, content)
            exported.append(
                ExportFile(
                    path=path.relative_to(out).as_posix(),
                    section=name,
                    slug=slug,
                    item_count=len(chunk),
                    note_count=_note_count(chunk),
                    size_bytes=path.stat().st_size,
                    update=_update_date(chunk),
                )
            )

    note_items = [item for item in items if item.note.strip()]
    my_notes_path = out / "my-notes.md"
    my_notes_content = (
        _my_notes_header(note_items)
        + "\n\n"
        + (renderer.render(note_items) if note_items else "暂无笔记。")
    )
    _write(my_notes_path, my_notes_content)
    my_notes_file = ExportFile(
        path=my_notes_path.relative_to(out).as_posix(),
        section="我的笔记",
        slug="my-notes",
        item_count=len(note_items),
        note_count=len(note_items),
        size_bytes=my_notes_path.stat().st_size,
        update=_update_date(note_items),
    )

    with_why = sum(1 for item in items if item.why.strip())
    index_content = _index_header(items, with_why) + "\n\n"
    index_content += "| 文件 | 板块 | 条目数 | 含笔记 | 体积 | 更新时间 |\n"
    index_content += "|---|---:|---:|---:|---:|---:|\n"
    for file in [my_notes_file, *sorted(exported, key=lambda row: row.path)]:
        index_content += (
            f"| `{file.path}` | {file.section} | {file.item_count} | "
            f"{file.note_count} | {_human_size(file.size_bytes)} | {file.update} |\n"
        )
    _write(out / "index.md", index_content)

    return ExportResult(
        out_dir=out,
        total_items=len(items),
        with_why=with_why,
        with_notes=sum(1 for item in items if item.note.strip()),
        files=tuple([my_notes_file, *exported]),
    )
