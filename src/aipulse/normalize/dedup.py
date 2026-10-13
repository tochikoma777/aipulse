"""三级去重（设计方案 §6.2）。

| 级别 | 方法 | 判定 |
|---|---|---|
| L1 精确 | `sha1(canonical_url + source)` | 同源自 URL → 丢弃 |
| L2 跨源 | `cross_source_key`：`arxiv:{id}` / `repo:{full_name}` | 合并为一条，`seen_in` 记录多源 |
| L3 近似 | `simhash64(title + summary)`，汉明距离 ≤3 | 视为同一事件，合并保留热度最高者 |

合并规则：最早 `published_at`、各项指标取最大（非空优先）、tags 并集、
`seen_in` 并集。跨源印证写入 `extra["cross_source"]=True`（打分层据此加热度加成）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aipulse.core.hashing import content_hash, cross_source_key, hamming_distance, simhash64
from aipulse.core.logging import get_logger
from aipulse.schema.items import RawItem, SourceMetrics

log = get_logger(__name__)

DEFAULT_SIMHASH_THRESHOLD = 3
CROSS_SOURCE_BONUS = 0.05  # 多源印证 = 更强信号（M2 打分层使用）


@dataclass
class DedupStats:
    input_count: int = 0
    l1_dropped: int = 0
    l2_merged: int = 0
    l3_merged: int = 0
    output_count: int = 0
    merged_sources: dict[str, int] = field(default_factory=dict)


def _merge_metrics(items: list[RawItem]) -> SourceMetrics:
    """指标合并：每项取所有源中的最大值（缺失即 None，不用 0 覆盖真实值）。"""
    merged = SourceMetrics()
    for name in SourceMetrics.model_fields:
        values = [
            getattr(item.metrics, name) for item in items if getattr(item.metrics, name) is not None
        ]
        if values:
            setattr(merged, name, max(values))
    return merged


def merge_items(items: list[RawItem]) -> RawItem:
    """把一组"同一事件"的 RawItem 合并成一条。"""
    primary = min(items, key=lambda i: i.published_at)  # 保留最早发布者作为主体
    seen_in = sorted({i.source.value for i in items})
    tags: list[str] = []
    for item in items:
        for tag in item.tags:
            if tag not in tags:
                tags.append(tag)

    extra: dict[str, Any] = {}
    for item in items:  # 后出现的源覆盖同名字段，但关键标记要保守
        extra.update(item.extra or {})
    # title_only：只要有一个源有正文就不算"仅标题"（避免量子位污染 arXiv 条目）
    extra["title_only"] = all(bool((i.extra or {}).get("title_only")) for i in items)
    if len(seen_in) > 1:
        extra["cross_source"] = True
        extra["cross_source_bonus"] = CROSS_SOURCE_BONUS

    merged = primary.model_copy(deep=True)
    merged.metrics = _merge_metrics(items)
    merged.seen_in = seen_in
    merged.tags = tags
    merged.extra = extra
    # 保留信息量最大的摘要（i.summary 可能是 None，强制转 str）
    merged.summary = str(max((i.summary for i in items), key=len))
    if len(seen_in) > 1:
        log.info("dedup.merged", key=primary.url, seen_in=seen_in)
    return merged


def dedup_items(
    items: list[RawItem], *, simhash_threshold: int = DEFAULT_SIMHASH_THRESHOLD
) -> tuple[list[RawItem], DedupStats]:
    """三级去重。返回 `(去重后的条目, 统计)`。"""
    stats = DedupStats(input_count=len(items))

    # ── L1：同源自 URL 精确去重 ─────────────────────────────────────
    unique: list[RawItem] = []
    seen_hashes: set[str] = set()
    for item in items:
        key = content_hash(item.url, item.source.value)
        if key in seen_hashes:
            stats.l1_dropped += 1
            continue
        seen_hashes.add(key)
        unique.append(item)

    # ── L2：跨源 key 合并（arxiv:{id} / repo:{full_name}）─────────────
    buckets: dict[str, list[RawItem]] = {}
    passthrough: list[RawItem] = []
    for item in unique:
        cross_key = cross_source_key(item.url)
        if cross_key is None:
            passthrough.append(item)
            continue
        buckets.setdefault(cross_key, []).append(item)

    merged: list[RawItem] = list(passthrough)
    for key, group in buckets.items():
        if len(group) > 1:
            stats.l2_merged += len(group) - 1
            stats.merged_sources[key] = len(group)
        merged.append(merge_items(group))

    # ── L3：SimHash 近似合并（汉明距离 ≤3）──────────────────────────
    fingerprints: list[tuple[int, RawItem]] = []
    result: list[RawItem] = []
    for item in merged:
        fingerprint = simhash64(f"{item.title} {item.summary[:500]}")
        hit_index = next(
            (
                i
                for i, (other, _) in enumerate(fingerprints)
                if hamming_distance(other, fingerprint) <= simhash_threshold
            ),
            None,
        )
        if hit_index is None:
            fingerprints.append((fingerprint, item))
            result.append(item)
            continue
        # 与已存在的近指纹合并：把两条并成一条（保留合并后的结果）
        existing = result[hit_index]
        combined = merge_items([existing, item])
        result[hit_index] = combined
        fingerprints[hit_index] = (
            simhash64(f"{combined.title} {combined.summary[:500]}"),
            combined,
        )
        stats.l3_merged += 1

    stats.output_count = len(result)
    return result, stats
