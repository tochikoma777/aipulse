"""每日报告索引：把 `data/reports/**/daily.json` 变成可检索的只读视图。

只读模块：不碰主库，也不写任何文件。供 knowledge CLI 的 `--url` / `--query`
与 `items` 命令使用；S4 也可以复用同一份索引。

历史结构兼容（实测 2026-10-15 ~ 10-18）：

- 10-15 / 10-16：`comments` 为空数组，无 `overview_bullets` / `headline_item_id`；
- 10-17：评论用 `why_it_matters`（不是 `why`），有 `overview_bullets`；
- 10-18：评论用 `why`；
- 字段缺失 / JSON 损坏：跳过该文件或该条目，不抛异常。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IndexedItem:
    """一条可检索的日报条目。"""

    item_id: str
    title: str
    url: str
    source: str
    summary: str
    section: str
    date: str
    hot_score: float
    why: str
    one_liner: str


@dataclass
class DailyIndex:
    """三个映射；`items` 已按 item_id 去重并完成跨天合并。"""

    items: dict[str, IndexedItem]
    url_to_id: dict[str, str]
    title_to_ids: dict[str, list[str]]


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _hot_score(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _date_from_payload(data: dict[str, Any], path: Path) -> str:
    value = _text(data.get("date"))
    if value:
        return value
    # 路径形如 data/reports/2026/10/18/daily.json
    parts = path.parent.parts[-3:]
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return "-".join(parts)
    return ""


def _section_map(value: Any) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    out: dict[str, str] = {}
    for section in value:
        if not isinstance(section, dict):
            continue
        name = _text(section.get("name"))
        item_ids = section.get("item_ids")
        if not name or not isinstance(item_ids, list):
            continue
        for item_id in item_ids:
            if isinstance(item_id, str) and item_id and item_id not in out:
                out[item_id] = name
    return out


def _comment_why(comment: Any) -> str:
    if not isinstance(comment, dict):
        return ""
    for key in ("why", "why_it_matters"):
        value = _text(comment.get(key))
        if value:
            return value
    return ""


def _comment_map(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for comment in value:
        if not isinstance(comment, dict):
            continue
        item_id = _text(comment.get("item_id"))
        if not item_id:
            continue
        existing = out.get(item_id)
        # 同一 item 的重复评论：优先保留有 why 的那条
        if existing is None or (not _comment_why(existing) and _comment_why(comment)):
            out[item_id] = comment
    return out


def _merge(old: IndexedItem | None, new: IndexedItem) -> IndexedItem:
    """跨天合并：有 why 的记录优先；都有 why（或都没有）时取较新的记录。"""
    if old is None:
        return new
    if not old.why and new.why:
        return new
    if old.why and not new.why:
        return old
    # 都有 why 或都没有 why：以较新的记录为主，缺字段回填旧值
    return replace(
        new,
        title=new.title or old.title,
        url=new.url or old.url,
        source=new.source or old.source,
        summary=new.summary or old.summary,
        section=new.section or old.section,
        why=new.why or old.why,
        one_liner=new.one_liner or old.one_liner,
    )


def build_daily_index(reports_dir: str | Path) -> DailyIndex:
    """扫描 `reports_dir/**/daily.json`，构建只读索引。"""
    root = Path(reports_dir)
    records: dict[str, IndexedItem] = {}
    if not root.exists():
        return DailyIndex(items={}, url_to_id={}, title_to_ids={})

    for path in sorted(root.rglob("daily.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue

        date = _date_from_payload(data, path)
        sections = _section_map(data.get("sections"))
        comments = _comment_map(data.get("comments"))
        raw_items = data.get("items")
        if not isinstance(raw_items, dict):
            continue

        for raw_id, raw_item in raw_items.items():
            item_id = _text(raw_id)
            if not item_id or not isinstance(raw_item, dict):
                continue
            comment = comments.get(item_id, {})
            title = _text(raw_item.get("title"))
            url = _text(raw_item.get("url"))
            if not title and not url:
                # 没有标题也没有 URL 的条目无法被用户定位，跳过
                continue
            record = IndexedItem(
                item_id=item_id,
                title=title,
                url=url,
                source=_text(raw_item.get("source")),
                summary=_text(raw_item.get("summary")),
                section=sections.get(item_id, ""),
                date=date,
                hot_score=_hot_score(raw_item.get("hot_score")),
                why=_comment_why(comment),
                one_liner=_text(comment.get("one_liner")),
            )
            records[item_id] = _merge(records.get(item_id), record)

    items = dict(sorted(records.items()))
    url_to_id: dict[str, str] = {}
    title_to_ids: dict[str, list[str]] = {}
    for item in items.values():
        if item.url:
            url_to_id.setdefault(item.url, item.item_id)
        if item.title:
            title_to_ids.setdefault(item.title, []).append(item.item_id)
    for ids in title_to_ids.values():
        ids.sort()
    return DailyIndex(items=items, url_to_id=url_to_id, title_to_ids=title_to_ids)


def find_by_url(index: DailyIndex, url: str) -> IndexedItem | None:
    """按完整 URL 精确反查；找不到返回 None。"""
    item_id = index.url_to_id.get(url.strip())
    return index.items.get(item_id) if item_id else None


def search_by_query(index: DailyIndex, query: str) -> list[IndexedItem]:
    """标题大小写不敏感子串匹配；按匹配位置从前往后排序。"""
    needle = query.strip().casefold()
    if not needle:
        return []
    matches: list[tuple[int, IndexedItem]] = []
    for item in index.items.values():
        position = item.title.casefold().find(needle)
        if position >= 0:
            matches.append((position, item))
    matches.sort(key=lambda pair: (pair[0], pair[1].title.casefold(), pair[1].item_id))
    return [item for _, item in matches]
