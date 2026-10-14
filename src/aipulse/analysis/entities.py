"""实体抽取与频次统计（设计方案 §9.3，规则 + 词典，零成本）。

V1 用 `configs/entities.yaml` 词典 + 正则（大小写不敏感、含常见别名），
对条目 title+summary 做匹配，写 `entities` 表。频次变化驱动周/月趋势判断。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from aipulse.core.config import load_entities, project_root
from aipulse.core.logging import get_logger
from aipulse.store.models import Entity, Item

log = get_logger(__name__)

_ASCII_RE = re.compile(r"[A-Za-z]")

_matcher: list[tuple[re.Pattern[str], str, str]] | None = None
_matcher_root: str | None = None


def load_entity_entries() -> list[tuple[str, str, list[str]]]:
    """读取词典 → [(name, type, [aliases])]。"""
    data = load_entities().get("entities", {})
    entries: list[tuple[str, str, list[str]]] = []
    if not isinstance(data, dict):
        return entries
    for etype, items in data.items():
        for item in items or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            aliases = [str(a) for a in (item.get("aliases") or [])]
            entries.append((str(name), str(etype), aliases))
    return entries


def _build_matcher() -> list[tuple[re.Pattern[str], str, str]]:
    """编译 (正则, 规范名, 类型)。ASCII 名加词边界，中文名子串匹配。"""
    patterns: list[tuple[re.Pattern[str], str, str]] = []
    for name, etype, aliases in load_entity_entries():
        for nm in [name, *aliases]:
            if not nm:
                continue
            if _ASCII_RE.search(nm):
                patterns.append((re.compile(rf"\b{re.escape(nm)}\b", re.IGNORECASE), name, etype))
            else:
                patterns.append((re.compile(re.escape(nm)), name, etype))
    return patterns


def matcher() -> list[tuple[re.Pattern[str], str, str]]:
    """编译后的匹配器。以项目根为键缓存：`AIPULSE_ROOT` 变化时重建（测试/热载友好）。"""
    global _matcher, _matcher_root
    root = str(project_root())
    if _matcher is None or _matcher_root != root:
        _matcher = _build_matcher()
        _matcher_root = root
    return _matcher


def reset_matcher() -> None:
    """测试/配置热载用：清空缓存。"""
    global _matcher, _matcher_root
    _matcher = None
    _matcher_root = None


def extract_entities(text: str) -> list[tuple[str, str]]:
    """从文本中抽取实体 → [(规范名, 类型)]（去重，保留词典声明顺序）。"""
    found: dict[tuple[str, str], None] = {}
    for pat, name, etype in matcher():
        if pat.search(text or ""):
            found[(name, etype)] = None
    return list(found.keys())


def build_entity_rows(items: list[Item], *, day: date) -> list[Entity]:
    """为一批条目生成 Entity 行（同实体同条目同天只记一次，去重交给 upsert_entities）。"""
    rows: list[Entity] = []
    for item in items:
        text = f"{item.title or ''} {item.summary or ''}"
        for name, etype in extract_entities(text):
            rows.append(Entity(name=name, type=etype, item_id=item.id, date=day, weight=1.0))
    return rows


def count_entities(rows: list[Entity]) -> dict[str, dict[str, Any]]:
    """按实体名统计频次 → {name: {"type": ..., "count": ...}}。"""
    counts: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = counts.setdefault(row.name, {"type": row.type, "count": 0})
        entry["count"] += 1
    return counts


__all__ = [
    "build_entity_rows",
    "count_entities",
    "extract_entities",
    "load_entity_entries",
    "reset_matcher",
]
