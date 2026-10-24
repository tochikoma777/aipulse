"""跨期结构计算（M5 S1）：从已 commit 的日报里算出"变化"，不调 LLM。

**为什么要有这一层**：M6b 已实证「让模型自主挑选 → why 覆盖率崩到 4%」。
同理，让模型自己"发现趋势"，它只会复述最显眼的那一个。所以趋势必须由代码算出来，
模型只负责解释与判断。本模块全程纯计算、零 LLM、零主库读写。

数据源只有 `data/reports/**/` 下已 commit 的产物（Actions 不持久化 SQLite，
本地主库已断档，不可作为跨期依据）：

- `daily.json`：`sections` / `items` / `underrated` / `comments`；
- `predictions.md`：当日新生成的预言（Markdown 表格）；
- `verdicts.md`：到期验证结果（Markdown 表格，无到期时只有一行说明）。

**★ 语义前提（S1.5 修正）**：每天 30 条 items 是 **brief 渲染集（Top30）**，不是全量语料。
榜单每天换血 70%+（相邻两天重叠仅 7–9 条，10-15→10-16 为 0），所以：

- 跨天比较只能表达"**是否在榜**"，不能表达"是否存在"；
- "今天不在榜" 一律读作「跌出 Top30」，**绝不能写成「消失/退场」**；
- 因此 ①②⑤⑥ 基于 `ItemTrack`（item_id → 7 天在榜/热度序列）而不是 T0/T1 两个时点。

历史结构兼容（实测 2026-10-15 ~ 2026-10-21）：

- 10-15 / 10-16：`items` 无 `metrics` / `streak_days`，只有 3 个 section，`comments` 为空；
- 10-17：评论用 `why_it_matters`（不是 `why`）；
- 10-18 起：评论用 `why`；
- 任意字段缺失 / JSON 损坏：跳过该条目或该天，**绝不抛异常**。

阈值全部是函数参数的显式默认值（模块常量），S1 阶段不新增 `configs/*.yaml` 字段——
新增配置项属于「字段新增」，需项目负责人确认后再落。
"""

from __future__ import annotations

import json
import math
import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from aipulse.analysis.cluster import tokenize

__all__ = [
    "CrossPeriodIndex",
    "DaySnapshot",
    "ItemTrack",
    "PeriodItem",
    "PredictionRecord",
    "StructureReport",
    "TrackPoint",
    "build_tracks",
    "collection_failures",
    "comparison_segment",
    "homogeneous_segments",
    "source_change_days",
    "co_movement",
    "direction_eps",
    "compute_all",
    "divergence",
    "emergence",
    "heat_migration",
    "load_cross_period",
    "persistence",
    "prediction_review",
    "source_share",
    "substitution",
    "unrealized",
]

# ── 判定状态（机器值；中文口径见各 StructureReport.name 与 S1 报告）──────────
STATUS_OK = "ok"
STATUS_INSUFFICIENT = "insufficient_data"

# ── 默认阈值（S1 用显式默认值，不读 YAML）──────────────────────────────────
DEFAULT_HOT_DELTA = 5.0
DEFAULT_METRIC_REL_DELTA = 0.10
DEFAULT_TITLE_SIMILARITY = 0.45
DEFAULT_CO_MOVEMENT_MIN_SIZE = 2
DEFAULT_SUBSTITUTE_TOP_K = 3
DEFAULT_FLAT_DELTA = 5.0
DEFAULT_TRACK_MIN_DAYS = 2
DEFAULT_TRACK_MIN_OVERLAP = 3
DEFAULT_TRACK_CORRELATION = 0.7
# ① 的方向判定阈值（pp/天）：斜率绝对值低于它视为「基本走平」。
# 5 天窗口下 0.5pp/天 ≈ 累计 2.5pp，小于日报单日份额波动——这是**锚点**，
# 不是通用常数：斜率估计的标准误 ∝ 1/√N，窗口越长，同样的斜率越可信。
# 固定 0.5 会让 30 天窗口对慢漂移过度迟钝、让 3 天窗口对噪声过度敏感。
DIRECTION_EPS_ANCHOR_DAYS = 5
DEFAULT_DIRECTION_EPS = 0.5
DEFAULT_MIN_EDGE_CORRELATION = 0.8


# 每个源的"互动指标"：背离检测要拿它跟 hot_score 比方向。
# rss 只有 rank_score（榜单位次），github 的 stars_in_window 是增量——都偏弱，
# 但它们是该源唯一可用的量，宁可标注来源也不要用别的源的字段硬套。
def direction_eps(days: int) -> float:
    """走平阈值随窗口缩放：`eps(N) = 0.5 * sqrt(5/N)`。

    依据：斜率的标准误与 √N 成反比，窗口翻倍 → 同样斜率更可信 → 阈值应放宽收紧。
    以 5 天 0.5pp/天 为锚点（原始校准值），N=3 时约 0.65、N=30 时约 0.20。
    """
    n = max(int(days), 2)
    return DEFAULT_DIRECTION_EPS * math.sqrt(DIRECTION_EPS_ANCHOR_DAYS / n)


ENGAGEMENT_METRIC: dict[str, str] = {
    "hackernews": "points",
    "hf_papers": "upvotes",
    "reddit": "score",
    "rss": "rank_score",
    "github_trending": "stars_in_window",
}

_PRED_ROW_MIN_COLS = 7
_EVIDENCE_ID_RE = re.compile(r"it_[0-9a-f]{6,}")
_DUE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_VERDICT_MARKS: dict[str, str] = {"✅ 命中": "hit", "🟡 部分": "partial", "❌ 落空": "miss"}


# ══════════════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PeriodItem:
    """某一天的一条日报条目（只保留跨期计算需要的字段）。"""

    item_id: str
    day: str
    title: str
    source: str
    section: str
    hot_score: float
    summary: str
    url: str
    metrics: dict[str, float] = field(default_factory=dict)
    streak_days: int | None = None
    topic_id: str | None = None


@dataclass
class DaySnapshot:
    """一天的只读快照。"""

    day: str
    items: dict[str, PeriodItem]
    sections: tuple[str, ...] = ()
    underrated: tuple[str, ...] = ()
    # source → (status, item_count)；来自同日目录下的 source_runs.json。
    # 10-15 / 10-16 没有这个文件，所以是空 dict（不代表采集失败）。
    source_runs: dict[str, tuple[str, int]] = field(default_factory=dict)


@dataclass(frozen=True)
class TrackPoint:
    """轨迹上的一个时点。

    `in_top=False` 只表示**当天不在 brief 渲染集（Top30）**，不代表它不存在。
    任何对外措辞都必须用「跌出 Top30」，不能用「消失」。
    `masked=True` 表示**这一天对该条目所属板块无效**（板块整块 0 条，
    多半是采集失败），既不算在榜也不算离榜。
    """

    day: str
    in_top: bool
    hot_score: float | None = None
    masked: bool = False


@dataclass(frozen=True)
class ItemTrack:
    """一个条目在整个窗口内的在榜轨迹。

    `daily.json` 的 items 是 brief 渲染集（每天 30 条），不是全量语料，
    所以跨天对比只能表达"是否在榜"，不能表达"是否还存在"。
    """

    item_id: str
    title: str
    source: str
    section: str
    points: tuple[TrackPoint, ...]
    runs: tuple[int, ...]  # 连续在榜段的长度，按时间顺序
    present_today: bool
    first_seen: str | None
    last_seen: str | None
    masked_days: tuple[str, ...] = ()  # 所属板块采集异常、无法判定的日子

    @property
    def days_on(self) -> int:
        return sum(self.runs)

    @property
    def longest_run(self) -> int:
        return max(self.runs) if self.runs else 0

    @property
    def current_run(self) -> int:
        """截至最后一天仍在延续的连续在榜天数；今天不在榜则为 0。"""
        return self.runs[-1] if self.present_today and self.runs else 0

    def series(self) -> list[tuple[str, float]]:
        """只在榜时点的 (day, hot_score)，供相关性/斜率使用。"""
        return [(p.day, p.hot_score) for p in self.points if p.hot_score is not None]

    def series_day_map(self) -> dict[str, float]:
        return {p.day: p.hot_score for p in self.points if p.hot_score is not None}


@dataclass(frozen=True)
class PredictionRecord:
    """`predictions.md` 里的一行（当日新生成的可证伪预言）。"""

    day: str
    statement: str
    category: str
    confidence: float
    horizon_days: int
    due_date: str
    evidence_ids: tuple[str, ...]
    verdict: str = ""
    verdict_note: str = ""


@dataclass(frozen=True)
class StructureReport:
    """一个结构（或"结构算不出"）的统一出口。

    三项必答：`entry_count`（产出的可追溯条目数）/ `status`（ok=有效、
    insufficient_data=数据不足）/ `required_days`（数据不足时：至少还要多少天）。
    `metrics` 放不适合塞进 entries 的汇总数字（如预言总数、最大 streak）。
    """

    key: str
    name: str
    status: str
    entry_count: int
    entries: tuple[dict[str, Any], ...] = ()
    required_days: int | None = None
    missing: tuple[str, ...] = ()
    notes: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """给 S2 的 prompt 消费：纯 JSON 结构，不含任何渲染。"""
        return {
            "key": self.key,
            "name": self.name,
            "status": self.status,
            "entry_count": self.entry_count,
            "required_days": self.required_days,
            "missing": list(self.missing),
            "notes": self.notes,
            "metrics": dict(self.metrics),
            "entries": [dict(e) for e in self.entries],
        }


@dataclass(frozen=True)
class CrossPeriodIndex:
    """跨期索引：按日期升序的快照集合。"""

    days: tuple[str, ...]
    snapshots: dict[str, DaySnapshot]
    predictions: tuple[PredictionRecord, ...] = ()

    def snapshot(self, day: str) -> DaySnapshot | None:
        return self.snapshots.get(day)

    def latest(self) -> DaySnapshot | None:
        return self.snapshots.get(self.days[-1]) if self.days else None


# ══════════════════════════════════════════════════════════════════════════
# 容错解析
# ══════════════════════════════════════════════════════════════════════════


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: Any) -> float | None:
    """只认真正的数值；bool 是 int 的子类，必须排除。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _day_from_payload(data: dict[str, Any], path: Path) -> str:
    value = _text(data.get("date"))
    if value:
        return value
    parts = path.parent.parts[-3:]
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return "-".join(parts)
    return ""


def _section_map(value: Any) -> tuple[dict[str, str], tuple[str, ...]]:
    """返回 (item_id → 板块名, 板块名顺序)。同一 item 出现在多个板块时取第一个。"""
    if not isinstance(value, list):
        return {}, ()
    section_of: dict[str, str] = {}
    order: list[str] = []
    for section in value:
        if not isinstance(section, dict):
            continue
        name = _text(section.get("name"))
        item_ids = section.get("item_ids")
        if not name or not isinstance(item_ids, list):
            continue
        if name not in order:
            order.append(name)
        for item_id in item_ids:
            key = _text(item_id)
            if key and key not in section_of:
                section_of[key] = name
    return section_of, tuple(order)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(text for text in (_text(v) for v in value) if text)


def _metrics_map(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, float] = {}
    for key, raw in value.items():
        name = _text(key)
        number = _number(raw)
        if name and number is not None:
            out[name] = number
    return out


def _snapshot_from_payload(day: str, data: dict[str, Any]) -> DaySnapshot:
    section_of, order = _section_map(data.get("sections"))
    raw_items = data.get("items")
    items: dict[str, PeriodItem] = {}
    if isinstance(raw_items, dict):
        for raw_id, raw_item in raw_items.items():
            item_id = _text(raw_id)
            if not item_id or not isinstance(raw_item, dict):
                continue
            title = _text(raw_item.get("title"))
            url = _text(raw_item.get("url"))
            if not title and not url:
                continue  # 无法定位的条目对跨期比较没有意义
            metrics = _metrics_map(raw_item.get("metrics"))
            streak = _number(raw_item.get("streak_days"))
            if streak is None:
                streak = metrics.get("streak_days")
            items[item_id] = PeriodItem(
                item_id=item_id,
                day=day,
                title=title,
                source=_text(raw_item.get("source")),
                section=section_of.get(item_id, ""),
                hot_score=_number(raw_item.get("hot_score")) or 0.0,
                summary=_text(raw_item.get("summary")),
                url=url,
                metrics=metrics,
                streak_days=int(streak) if streak is not None else None,
                topic_id=_text(raw_item.get("topic_id")) or None,
            )
    return DaySnapshot(
        day=day,
        items=items,
        sections=order,
        underrated=_string_tuple(data.get("underrated")),
    )


def _split_row(line: str) -> list[str]:
    """按未转义的 `|` 切表格行；`\\|` 还原成 `|`。"""
    cells: list[str] = []
    buf: list[str] = []
    escaped = False
    for ch in line.strip():
        if escaped:
            buf.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == "|":
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    cells.append("".join(buf).strip())
    return [c for c in cells]


def _table_rows(text: str, min_cols: int) -> list[list[str]]:
    """抠出 Markdown 表格的数据行（跳过表头与 `---` 分隔行）。"""
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = _split_row(stripped)
        # 只去掉首尾 `|` 造成的空串；**保留中间的空单元格**，否则列会错位
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        if len(cells) < min_cols:
            continue
        if all(set(c) <= {"-", ":", " "} for c in cells):
            continue
        rows.append(cells)
    return rows[1:] if rows else []  # 第一行是表头


def _parse_horizon(value: str) -> int:
    match = re.search(r"(\d+)", value)
    return int(match.group(1)) if match else 0


def _parse_predictions(day: str, path: Path) -> tuple[PredictionRecord, ...]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ()
    out: list[PredictionRecord] = []
    for cells in _table_rows(text, _PRED_ROW_MIN_COLS):
        statement = cells[0]
        if not statement:
            continue
        due_match = _DUE_RE.search(cells[4]) if len(cells) > 4 else None
        out.append(
            PredictionRecord(
                day=day,
                statement=statement,
                category=cells[1] if len(cells) > 1 else "",
                confidence=_number(_float_text(cells[2] if len(cells) > 2 else "")) or 0.0,
                horizon_days=_parse_horizon(cells[3] if len(cells) > 3 else ""),
                due_date=due_match.group(1) if due_match else "",
                evidence_ids=tuple(_EVIDENCE_ID_RE.findall(cells[6] if len(cells) > 6 else "")),
            )
        )
    return tuple(out)


def _float_text(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _parse_verdicts(path: Path) -> dict[str, tuple[str, str]]:
    """`verdicts.md` → {statement: (verdict, note)}。无到期时文件只有一行说明。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}
    out: dict[str, tuple[str, str]] = {}
    for cells in _table_rows(text, 6):
        statement = cells[0]
        mark = cells[1]
        verdict = _VERDICT_MARKS.get(mark, "")
        if statement and verdict:
            out[_norm_statement(statement)] = (verdict, cells[5] if len(cells) > 5 else "")
    return out


def _norm_statement(value: str) -> str:
    """比对用的归一化：全半角统一 + 去空白。"""
    return "".join(unicodedata.normalize("NFKC", value).split())


# ══════════════════════════════════════════════════════════════════════════
# 加载
# ══════════════════════════════════════════════════════════════════════════


def _parse_source_runs(path: Path) -> dict[str, tuple[str, int]]:
    """`source_runs.json` → {source: (status, item_count)}；缺失或损坏返回空表。"""
    data = _read_json(path)
    if not isinstance(data, dict):
        return {}
    rows = data.get("sources")
    if not isinstance(rows, list):
        return {}
    out: dict[str, tuple[str, int]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = _text(row.get("source"))
        if not source:
            continue
        status = _text(row.get("status")) or "unknown"
        count = _number(row.get("item_count"))
        out[source] = (status, int(count) if count is not None else 0)
    return out


def load_cross_period(reports_dir: str | Path) -> CrossPeriodIndex:
    """扫描 `reports_dir/**/daily.json`（并顺带读同目录的 predictions/verdicts）。"""
    root = Path(reports_dir)
    if not root.exists():
        return CrossPeriodIndex(days=(), snapshots={})

    snapshots: dict[str, DaySnapshot] = {}
    predictions: list[PredictionRecord] = []
    verdicts: dict[str, tuple[str, str]] = {}

    for path in sorted(root.rglob("daily.json")):
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        day = _day_from_payload(data, path)
        if not day:
            continue
        snap = _snapshot_from_payload(day, data)
        snap.source_runs = _parse_source_runs(path.parent / "source_runs.json")
        previous = snapshots.get(day)
        # 同一天多份报告：保留条目更多的（历史重跑会产生 7 件/8 件两种）
        if previous is None or len(snap.items) > len(previous.items):
            snapshots[day] = snap

        predictions.extend(_parse_predictions(day, path.parent / "predictions.md"))
        verdicts.update(_parse_verdicts(path.parent / "verdicts.md"))

    enriched: list[PredictionRecord] = []
    for record in predictions:
        verdict, note = verdicts.get(_norm_statement(record.statement), ("", ""))
        if verdict:
            enriched.append(
                PredictionRecord(
                    day=record.day,
                    statement=record.statement,
                    category=record.category,
                    confidence=record.confidence,
                    horizon_days=record.horizon_days,
                    due_date=record.due_date,
                    evidence_ids=record.evidence_ids,
                    verdict=verdict,
                    verdict_note=note,
                )
            )
        else:
            enriched.append(record)

    return CrossPeriodIndex(
        days=tuple(sorted(snapshots)),
        snapshots=snapshots,
        predictions=tuple(enriched),
    )


def build_tracks(index: CrossPeriodIndex) -> dict[str, ItemTrack]:
    """把"某天有哪些条目"转成"某个条目在哪些天在榜"。

    这是 S1.5 的核心修正：日报每天只有 30 条（brief 渲染集），
    任何"今天没有 = 消失了"的读法都是错的，只能读成"跌出 Top30"。
    """
    days = index.days
    seen: dict[str, list[str]] = {}
    for day in days:
        for item_id in index.snapshots[day].items:
            seen.setdefault(item_id, []).append(day)
    if not days:
        return {}

    bad_days = _bad_days_by_section(index)
    tracks: dict[str, ItemTrack] = {}
    for item_id, present in seen.items():
        present_set = set(present)
        latest = index.snapshots[present[-1]].items[item_id]
        masked_set = bad_days.get(latest.section, set()) - present_set
        points = tuple(
            TrackPoint(
                day=day,
                in_top=day in present_set,
                hot_score=(
                    index.snapshots[day].items[item_id].hot_score if day in present_set else None
                ),
                masked=day in masked_set,
            )
            for day in days
        )
        runs: list[int] = []
        current = 0
        for day in days:
            if day in present_set:
                current += 1
            elif day in masked_set:
                # 采集异常日：既不算在榜也不算离榜，连续段跨过去
                continue
            elif current:
                runs.append(current)
                current = 0
        if current:
            runs.append(current)

        tracks[item_id] = ItemTrack(
            item_id=item_id,
            # 标题/板块可能逐日微调，取最后一次在榜时的值（最能代表当前形态）
            title=latest.title,
            source=latest.source,
            section=latest.section,
            points=points,
            runs=tuple(runs),
            present_today=days[-1] in present_set,
            first_seen=present[0],
            last_seen=present[-1],
            masked_days=tuple(day for day in days if day in masked_set),
        )
    return tracks


# ══════════════════════════════════════════════════════════════════════════
# 公共小工具
# ══════════════════════════════════════════════════════════════════════════


def _bad_report(key: str, name: str, required_days: int, *missing: str) -> StructureReport:
    return StructureReport(
        key=key,
        name=name,
        status=STATUS_INSUFFICIENT,
        entry_count=0,
        required_days=required_days,
        missing=missing,
    )


def _resolve_pair(
    index: CrossPeriodIndex, t0: str | None, t1: str | None
) -> tuple[str, str] | None:
    if t1 is not None:
        if t1 not in index.snapshots or (t0 is not None and t0 not in index.snapshots):
            return None
        if t0 is None:
            earlier = [d for d in index.days if d < t1]
            if not earlier:
                return None
            return earlier[-1], t1
        return t0, t1
    if len(index.days) < 2:
        return None
    return index.days[-2], index.days[-1]


def _shares(totals: dict[str, float]) -> dict[str, float]:
    total = sum(totals.values())
    if total <= 0:
        return {k: 0.0 for k in totals}
    return {k: v / total for k, v in totals.items()}


def _round(value: float, digits: int = 4) -> float:
    return round(value, digits)


def _common(a: DaySnapshot, b: DaySnapshot) -> list[str]:
    return sorted(set(a.items) & set(b.items))


def _section_totals(snap: DaySnapshot) -> dict[str, float]:
    totals: dict[str, float] = {}
    for item in snap.items.values():
        if item.section:
            totals[item.section] = totals.get(item.section, 0.0) + item.hot_score
    return totals


def _section_counts_by_day(index: CrossPeriodIndex) -> dict[str, dict[str, int]]:
    """每天每个板块实际渲染了多少条（用于识别"整块为空"的生成异常）。"""
    out: dict[str, dict[str, int]] = {}
    for day in index.days:
        counts: dict[str, int] = {}
        for item in index.snapshots[day].items.values():
            if item.section:
                counts[item.section] = counts.get(item.section, 0) + 1
        out[day] = counts
    return out


def _schema_change_days(index: CrossPeriodIndex) -> set[str]:
    """板块集合相对前一天发生变化的日子（口径变更日）。"""
    changed: set[str] = set()
    for prev, cur in zip(index.days, index.days[1:], strict=False):
        if set(index.snapshots[prev].sections) != set(index.snapshots[cur].sections):
            changed.add(cur)
    return changed


def _bad_days_by_section(index: CrossPeriodIndex) -> dict[str, set[str]]:
    """板块「夹在两次有数据之间」的 0 条日 = 采集异常日（不是板块退场）。

    实测 2026-10-18：「论文与研究」0 条，而 10-17 与 10-19 都有；
    真实原因是 hf_papers 连续两天 degraded=0 + 24h 滚动窗口把旧条目甩出去。
    这类日子必须从斜率/轨迹里剔除，否则会算出"前高后低"的伪结构。
    """
    counts = _section_counts_by_day(index)
    sections = {name for per_day in counts.values() for name in per_day}
    out: dict[str, set[str]] = {}
    for section in sections:
        present = [day for day in index.days if counts[day].get(section, 0) > 0]
        if len(present) < 2:
            continue
        first, last = present[0], present[-1]
        zeros = {
            day for day in index.days if first < day < last and counts[day].get(section, 0) == 0
        }
        if zeros:
            out[section] = zeros
    return out


def collection_failures(index: CrossPeriodIndex) -> list[dict[str, Any]]:
    """`source_runs` 里 failed / degraded 的记录（含 item_count），供证据与 prompt 使用。"""
    rows: list[dict[str, Any]] = []
    for day in index.days:
        for source, (status, count) in sorted(index.snapshots[day].source_runs.items()):
            if status in {"failed", "degraded"}:
                rows.append({"day": day, "source": source, "status": status, "item_count": count})
    return rows


# 手动投喂通道：没有内容时必然 degraded/0，不能当成采集失败。
_OPTIONAL_SOURCES = frozenset({"inbox"})


def _source_failure_days(index: CrossPeriodIndex) -> dict[str, set[str]]:
    """真正"没采到东西"的源日：status 为 failed/degraded **且 item_count == 0**。

    `degraded` 但 item_count>0（如 reddit 25 条）不算失败——它只是部分降级；
    `inbox` 是手动通道，空着是常态，也不算失败。
    """
    out: dict[str, set[str]] = {}
    for day in index.days:
        for source, (status, count) in index.snapshots[day].source_runs.items():
            if source in _OPTIONAL_SOURCES:
                continue
            if status in {"failed", "degraded"} and count == 0:
                out.setdefault(source, set()).add(day)
    return out


def _section_sources(index: CrossPeriodIndex) -> dict[str, set[str]]:
    """板块 → 实际供给它的来源集合（按窗口内出现过的条目统计）。"""
    out: dict[str, set[str]] = {}
    for day in index.days:
        for item in index.snapshots[day].items.values():
            if item.section and item.source:
                out.setdefault(item.section, set()).add(item.source)
    return out


def _source_sets(index: CrossPeriodIndex) -> dict[str, frozenset[str]]:
    """每天"启用了哪些源"。

    优先用 `source_runs.json` 的 keys（配置层面的源集合）：
    某源当天 0 条是采集异常，不该被误判成"源集合缩小"。
    没有该文件的历史日报退化为"当天有條目的源集合"。
    """
    out: dict[str, frozenset[str]] = {}
    for day in index.days:
        snap = index.snapshots[day]
        if snap.source_runs:
            out[day] = frozenset(snap.source_runs)
        else:
            out[day] = frozenset(item.source for item in snap.items.values() if item.source)
    return out


def source_change_days(index: CrossPeriodIndex) -> set[str]:
    """源集合相对前一天发生变化的日子（新增/移除数据源）。"""
    sets = _source_sets(index)
    changed: set[str] = set()
    for prev, cur in zip(index.days, index.days[1:], strict=False):
        if sets[prev] != sets[cur]:
            changed.add(cur)
    return changed


def homogeneous_segments(index: CrossPeriodIndex, *, min_days: int = 3) -> list[tuple[str, ...]]:
    """按源集合把窗口切成若干"同构区间"，只返回长度 ≥ min_days 的段。

    理由：10-15/16 只有 3 个源，10-17 起 5 个源（多了 reddit/rss）。
    跨变更点的份额对比会把"源扩容"读成"板块迁移"，必须分段；但整窗口封锁
    会让 M5 无话可写，所以保留变更后的同构区间继续可比。
    """
    sets = _source_sets(index)
    segments: list[tuple[str, ...]] = []
    current: list[str] = []
    for day in index.days:
        if current and sets[day] != sets[current[-1]]:
            segments.append(tuple(current))
            current = []
        current.append(day)
    if current:
        segments.append(tuple(current))
    return [segment for segment in segments if len(segment) >= min_days]


def comparison_segment(index: CrossPeriodIndex, *, min_days: int = 3) -> tuple[str, ...] | None:
    """最近一段"源集合同构且 ≥min_days 天"的区间；没有则返回 None。"""
    segments = homogeneous_segments(index, min_days=min_days)
    return segments[-1] if segments else None


# ══════════════════════════════════════════════════════════════════════════
# ① 热度迁移矩阵
# ══════════════════════════════════════════════════════════════════════════


def _resolve_window(
    index: CrossPeriodIndex,
    t0: str | None,
    t1: str | None,
    *,
    homogeneous: bool,
    full_window: bool,
    min_segment_days: int,
) -> tuple[str, ...] | None:
    """决定比较窗口：显式 t0/t1 > 全窗口 > 同构区间 > 最后两天。"""
    if t0 is not None or t1 is not None:
        return _resolve_pair(index, t0, t1)
    if full_window:
        return index.days or None
    if homogeneous:
        return comparison_segment(index, min_days=min_segment_days)
    return _resolve_pair(index, None, None)


def heat_migration(
    index: CrossPeriodIndex,
    *,
    t0: str | None = None,
    t1: str | None = None,
    homogeneous: bool = True,
    full_window: bool = False,
    min_segment_days: int = 3,
) -> StructureReport:
    """按板块聚合，T0→T1 的热度份额变化（百分点），并补上同构区间斜率。

    份额而非绝对值：T0/T1 的条目总量与热度总量不同，绝对值不可比。
    **默认只在最后一段"源集合同构且 ≥3 天"的区间上比较**：
    跨源集合变更日（如 10-17 从 3 源扩到 5 源）的份额对比会把"源扩容"
    读成"板块迁移"；但整窗口封锁又会让周报无话可写，所以按区间切。
    `full_window=True` 仅用于对照与排查，不用于生成。
    """
    key, name = "heat_migration", "① 热度迁移矩阵"
    window = _resolve_window(
        index,
        t0,
        t1,
        homogeneous=homogeneous,
        full_window=full_window,
        min_segment_days=min_segment_days,
    )
    if window is None or len(window) < 2:
        return _bad_report(
            key,
            name,
            min_segment_days if homogeneous and not full_window else 2,
            f"没有 ≥{min_segment_days} 天的源集合同构区间"
            if homogeneous and not full_window
            else "至少需要 2 天日报",
        )
    days_used = window
    a, b = index.snapshots[days_used[0]], index.snapshots[days_used[-1]]
    ta, tb = _section_totals(a), _section_totals(b)
    if not ta or not tb:
        return _bad_report(key, name, 2, "T0/T1 至少一天没有板块归属（sections 为空）")

    sa, sb = _shares(ta), _shares(tb)
    history = [_shares(_section_totals(index.snapshots[day])) for day in days_used]
    bad_days = _bad_days_by_section(index)
    section_sources = _section_sources(index)
    failures = _source_failure_days(index)
    entries: list[dict[str, Any]] = []
    for section in sorted(set(ta) | set(tb)):
        delta_pp = (sb.get(section, 0.0) - sa.get(section, 0.0)) * 100
        series = [day_map.get(section, 0.0) * 100 for day_map in history]
        # ★ 斜率必须剔除"板块整块 0 条"的采集异常日，否则 0 会被当成"回落"
        excluded = sorted(bad_days.get(section, set()) & set(days_used))
        points = [
            (pos, series[pos])
            for pos, day in enumerate(days_used)
            if day not in bad_days.get(section, set())
        ]
        # ★ 若该板块的供给源在窗口内"整源 0 条"，则整个板块的结构判断都不可信
        taint_sources = sorted(s for s in section_sources.get(section, set()) if failures.get(s))
        taint_days = sorted({day for source in taint_sources for day in failures[source]})
        slope = _slope_at(points)
        # ★ 阈值随**实际可用天数**缩放（剔除坏日后的 len(points)），不是固定 0.5
        eps = direction_eps(len(points))
        direction = "flat" if abs(slope) < eps else ("up" if slope > 0 else "down")
        conflict = (direction == "up" and delta_pp < 0) or (direction == "down" and delta_pp > 0)
        entries.append(
            {
                "section": section,
                "t0_total_hot": _round(ta.get(section, 0.0), 2),
                "t1_total_hot": _round(tb.get(section, 0.0), 2),
                "t0_share": _round(sa.get(section, 0.0)),
                "t1_share": _round(sb.get(section, 0.0)),
                "delta_pp": _round(delta_pp, 2),
                "slope_pp_per_day": _round(slope, 2),
                "slope_days": len(points),
                # 方向以斜率为准（两点差会被首末两天主导），但幅度仍报首末差。
                # 两者不一致时必须显式标出，禁止只挑一个数字下结论。
                "direction": direction,
                "signal_conflict": conflict,
                "excluded_days": excluded,
                "slope_note": (
                    f"已排除 {len(excluded)} 个板块空日（{'/'.join(excluded)}）" if excluded else ""
                ),
                "taint_sources": taint_sources,
                "taint_days": taint_days,
                "trend_usable": not taint_sources,
                "trend_note": (
                    f"供给源 {'/'.join(taint_sources)} 在 "
                    f"{'/'.join(taint_days)} 整源 0 条，本板块不得作结构性趋势判断"
                    if taint_sources
                    else ""
                ),
                "share_series_pp": [_round(v, 2) for v in series],
                "t0_top_items": _top_items(a, section, 3),
                "t1_top_items": _top_items(b, section, 3),
            }
        )
    entries.sort(key=lambda e: abs(float(e["delta_pp"])), reverse=True)
    excluded_total = sum(len(e["excluded_days"]) for e in entries)
    tainted = [str(e["section"]) for e in entries if not e["trend_usable"]]
    conflicts = [str(e["section"]) for e in entries if e["signal_conflict"]]
    source_changes = sorted(source_change_days(index))
    return StructureReport(
        key=key,
        name=name,
        status=STATUS_OK,
        entry_count=len(entries),
        entries=tuple(entries),
        notes=(
            f"对比区间 {a.day}→{b.day}（{len(days_used)} 天，源集合同构）；"
            f"份额分母仅含已归板块的条目；"
            f"direction 以斜率（阈值 ±{direction_eps(len(points)):.2f}pp/天，随窗口缩放）为准，"
            f"delta_pp 只作幅度参照"
            + (f"；首末差与斜率方向不一致：{'/'.join(conflicts)}" if conflicts else "")
            + (f"；采集失败、不可作趋势：{'/'.join(tainted)}" if tainted else "")
            + (
                f"；跨源集合变更日（{'/'.join(source_changes)}）的比较已禁用"
                if source_changes
                else ""
            )
        ),
        metrics={
            "comparison_start": a.day,
            "comparison_end": b.day,
            "comparison_days": len(days_used),
            "full_window_days": len(index.days),
            "source_change_days": source_changes,
            "excluded_section_days": excluded_total,
            "tainted_sections": tainted,
            "conflicting_sections": conflicts,
            "t0_items": len(a.items),
            "t1_items": len(b.items),
            "overlap_items": len(_common(a, b)),
            "window_days": len(index.days),
        },
    )


def _slope_at(points: list[tuple[int, float]]) -> float:
    """最小二乘斜率（value / 天），x 用真实日序号，允许跳过坏日。"""
    n = len(points)
    if n < 2:
        return 0.0
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    denom = sum((x - mean_x) ** 2 for x, _ in points)
    if denom == 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in points) / denom


def _top_items(snap: DaySnapshot, section: str, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {"item_id": it.item_id, "title": it.title, "hot_score": _round(it.hot_score, 2)}
        for it in snap.items.values()
        if it.section == section
    ]
    rows.sort(key=lambda r: float(r["hot_score"]), reverse=True)
    return rows[:limit]


# ══════════════════════════════════════════════════════════════════════════
# ② 共动聚类
# ══════════════════════════════════════════════════════════════════════════


def co_movement(
    index: CrossPeriodIndex,
    *,
    tracks: dict[str, ItemTrack] | None = None,
    min_days: int = DEFAULT_TRACK_MIN_DAYS,
    min_overlap: int = DEFAULT_TRACK_MIN_OVERLAP,
    correlation: float = DEFAULT_TRACK_CORRELATION,
    min_edge_correlation: float = DEFAULT_MIN_EDGE_CORRELATION,
    min_size: int = DEFAULT_CO_MOVEMENT_MIN_SIZE,
) -> StructureReport:
    """同板块 / 同来源内，热度轨迹正相关的条目组。

    **为什么不再用两日差**：相邻两天的榜单重叠只有 7–9/30，
    "同向变化"在这么小的交集上几乎等于随机。改用轨迹相关：
    只有在榜 ≥`min_days` 天、且两条轨迹共同在榜 ≥`min_overlap` 天的配对才参与计算。

    相关性的代价是样本更少（共同在榜 3 天以上才可算），
    所以 `metrics` 里必须同时报"可算配对数"和"达阈值的边数"——
    0 条时要能分清是"没有共动"还是"根本没有可算样本"。
    """
    key, name = "co_movement", "② 共动聚类"
    if len(index.days) < 2:
        return _bad_report(key, name, 2, "至少需要 2 天日报")
    tracks = tracks if tracks is not None else build_tracks(index)
    sample = {iid: t for iid, t in tracks.items() if t.days_on >= min_days}
    if len(sample) < min_size:
        return _bad_report(
            key, name, 2, f"在榜 ≥{min_days} 天的条目只有 {len(sample)} 条，不足以算共动"
        )

    # (scope,label) -> {(item_a, item_b): (r, 共同在榜天数)}
    pair_stats: dict[tuple[str, str], dict[tuple[str, str], tuple[float, int]]] = {}
    comparable: set[tuple[str, str]] = set()
    for scope in ("section", "source"):
        buckets: dict[str, list[ItemTrack]] = {}
        for track in sample.values():
            label = track.section if scope == "section" else track.source
            if label:
                buckets.setdefault(label, []).append(track)
        for label, members in buckets.items():
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    left, right = members[i], members[j]
                    shared = sorted(set(left.series_day_map()) & set(right.series_day_map()))
                    if len(shared) < min_overlap:
                        continue
                    r = _pearson(
                        [left.series_day_map()[d] for d in shared],
                        [right.series_day_map()[d] for d in shared],
                    )
                    if r is None:
                        continue
                    # 同一对条目可能在板块与来源两个 scope 里各算一次，指标只计唯一对
                    pair_key = (
                        (left.item_id, right.item_id)
                        if left.item_id <= right.item_id
                        else (right.item_id, left.item_id)
                    )
                    comparable.add(pair_key)
                    pair_stats.setdefault((scope, label), {})[pair_key] = (r, len(shared))

    entries: list[dict[str, Any]] = []
    seen: set[frozenset[str]] = set()
    for (scope, label), stats in sorted(pair_stats.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        strong_edges = [
            (r, a, b, n_days) for (a, b), (r, n_days) in stats.items() if r >= correlation
        ]
        if not strong_edges:
            continue
        for component in _components(strong_edges, min_size):
            signature = frozenset(component)
            if signature in seen:
                continue
            seen.add(signature)
            members_sorted = sorted(
                (tracks[iid] for iid in component),
                key=lambda t: t.days_on,
                reverse=True,
            )
            # 组内全部可算的配对（不只达阈值的边），用于回答"这组最弱的一对有多弱"
            inner = [
                (r, n_days, a, b)
                for (a, b), (r, n_days) in stats.items()
                if a in signature and b in signature
            ]
            strong = [p for p in inner if p[0] >= correlation]
            weak = [p for p in inner if p[0] < min_edge_correlation]
            edges_out: list[dict[str, Any]] = sorted(
                (
                    {"left": a, "right": b, "r": _round(r, 3), "n_days": n_days}
                    for r, n_days, a, b in strong
                ),
                key=lambda e: float(e["r"]),
                reverse=True,
            )
            entries.append(
                {
                    "scope": scope,
                    "label": label,
                    "size": len(component),
                    "mean_correlation": _round(
                        sum(float(e["r"]) for e in edges_out) / len(edges_out), 3
                    ),
                    "min_correlation": _round(min(p[0] for p in inner), 3),
                    "weak_pairs": len(weak),
                    # 连通分量不等于"整体同向"：实测有一组 11 条里存在 r=-0.97 的反向对，
                    # 只是被中间节点连起来了。coherent=False 时禁止把它写成"板块整体共动"。
                    "is_coherent": bool(weak) is False,
                    "n_days_min": min(p[1] for p in inner),
                    "n_days_max": max(p[1] for p in inner),
                    # ★ n 只有 3~7 天时 Pearson 的显著阈值接近 0.997；
                    #   这里报的 0.9x 并不显著，所以必须显式声明"未做显著性检验"，
                    #   下游只能表述为"观察到同步变化"，不能写"存在相关"。
                    "has_significance_test": False,
                    "members": [
                        {
                            "item_id": t.item_id,
                            "title": t.title,
                            "days_on": t.days_on,
                            "first_seen": t.first_seen,
                            "last_seen": t.last_seen,
                            "series": [[day, _round(hot, 2)] for day, hot in t.series()],
                        }
                        for t in members_sorted
                    ],
                    "edges": edges_out,
                }
            )
    entries.sort(key=lambda e: (int(e["size"]), float(e["mean_correlation"])), reverse=True)
    return StructureReport(
        key=key,
        name=name,
        status=STATUS_OK,
        entry_count=len(entries),
        entries=tuple(entries),
        notes=(
            f"样本=在榜 ≥{min_days} 天的 {len(sample)} 条；配对需共同在榜 ≥{min_overlap} 天，"
            f"成组阈值 r≥{correlation}；组内弱边（r<{min_edge_correlation}）只计数、不拆组；"
            "★ 未做显著性检验：n<5 时 Pearson 的显著阈值≈0.997，"
            "只能表述为「观察到同步变化」，禁止写「存在相关/共动」"
        ),
        metrics={
            "sample_items": len(sample),
            "comparable_pairs": len(comparable),
            "edges": sum(1 for v in pair_stats.values() for r, _ in v.values() if r >= correlation),
            "groups": len(entries),
            "window_days": len(index.days),
            "has_significance_test": False,
        },
    )


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    try:
        return float(statistics.correlation(xs, ys))
    except statistics.StatisticsError:
        return None  # 任一侧方差为 0（热度完全不动）


def _components(edges: list[tuple[float, str, str, int]], min_size: int) -> list[list[str]]:
    """把边连成连通分量；只返回 size ≥ min_size 的分量。"""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for _, a, b, _n_days in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    groups: dict[str, list[str]] = {}
    for node in list(parent):
        groups.setdefault(find(node), []).append(node)
    return [sorted(v) for v in groups.values() if len(v) >= min_size]


# ══════════════════════════════════════════════════════════════════════════
# ③ 背离检测
# ══════════════════════════════════════════════════════════════════════════


def divergence(
    index: CrossPeriodIndex,
    *,
    t0: str | None = None,
    t1: str | None = None,
    hot_delta: float = DEFAULT_HOT_DELTA,
    metric_rel_delta: float = DEFAULT_METRIC_REL_DELTA,
) -> StructureReport:
    """hot_score 方向与互动指标方向相反的条目。

    hot_score 由算法合成（含新鲜度/跨源加成），互动指标是原始量；
    两者背离说明"热"不是靠数据涨的，而是靠时间窗或跨源权重堆出来的。
    """
    key, name = "divergence", "③ 背离检测"
    pair = _resolve_pair(index, t0, t1)
    if pair is None:
        return _bad_report(key, name, 2, "至少需要 2 天日报")
    a, b = index.snapshots[pair[0]], index.snapshots[pair[1]]

    entries: list[dict[str, Any]] = []
    comparable = 0
    skipped_no_metric = 0
    for item_id in _common(a, b):
        old, new = a.items[item_id], b.items[item_id]
        metric = ENGAGEMENT_METRIC.get(new.source)
        if metric is None:
            skipped_no_metric += 1
            continue
        m0, m1 = old.metrics.get(metric), new.metrics.get(metric)
        if m0 is None or m1 is None:
            skipped_no_metric += 1
            continue
        comparable += 1
        dh = new.hot_score - old.hot_score
        dm = m1 - m0
        rel = abs(dm) / max(abs(m0), 1.0)
        if abs(dh) < hot_delta or rel < metric_rel_delta:
            continue
        if dh * dm >= 0:
            continue
        entries.append(
            {
                "item_id": item_id,
                "title": new.title,
                "source": new.source,
                "section": new.section,
                "metric": metric,
                "t0_hot": _round(old.hot_score, 2),
                "t1_hot": _round(new.hot_score, 2),
                "delta_hot": _round(dh, 2),
                "t0_metric": _round(m0, 2),
                "t1_metric": _round(m1, 2),
                "delta_metric_rel": _round(rel),
                "relation": "hot_up_metric_down" if dh > 0 else "hot_down_metric_up",
            }
        )

    if comparable == 0:
        return _bad_report(
            key,
            name,
            2,
            "T0/T1 没有可比的互动指标（10-15 / 10-16 的 items 无 metrics 字段）",
        )
    entries.sort(key=lambda e: abs(float(e["delta_hot"])), reverse=True)
    return StructureReport(
        key=key,
        name=name,
        status=STATUS_OK,
        entry_count=len(entries),
        entries=tuple(entries),
        notes=(
            f"T0={a.day} T1={b.day}；阈值 |Δhot|≥{hot_delta} 且 |Δmetric|/max(|metric_T0|,1)"
            f"≥{metric_rel_delta}；互动指标按源取（{ENGAGEMENT_METRIC}）"
        ),
        metrics={
            "compared_items": comparable,
            "skipped_no_metric": skipped_no_metric,
        },
    )


# ══════════════════════════════════════════════════════════════════════════
# ④ 替代对
# ══════════════════════════════════════════════════════════════════════════


def substitution(
    index: CrossPeriodIndex,
    *,
    t0: str | None = None,
    t1: str | None = None,
    similarity_threshold: float = DEFAULT_TITLE_SIMILARITY,
    top_k: int = DEFAULT_SUBSTITUTE_TOP_K,
) -> StructureReport:
    """一个条目掉榜、另一个相似条目上榜 → 疑似"同类替代"。

    **退化方案（已确认做不到的）**：不能按 `topic_id` 配对——它是
    `hash(日期:名称)`，跨天必变（实测每天只有 0–4 条有值，且没有跨天稳定性）。
    因此按 **同板块 + 标题 TF-IDF 余弦** 配对：先限定板块（语义域），
    再比标题相似度。代价是跨板块的替代（如论文→项目）识别不到。
    """
    key, name = "substitution", "④ 替代对"
    pair = _resolve_pair(index, t0, t1)
    if pair is None:
        return _bad_report(key, name, 2, "至少需要 2 天日报")
    a, b = index.snapshots[pair[0]], index.snapshots[pair[1]]

    vanished = [it for it in a.items.values() if it.item_id not in b.items and it.section]
    appeared = [it for it in b.items.values() if it.item_id not in a.items and it.section]
    if not vanished or not appeared:
        return StructureReport(
            key=key,
            name=name,
            status=STATUS_OK,
            entry_count=0,
            notes=(
                f"T0={a.day} T1={b.day}；掉榜 {len(vanished)} 条、新上榜 {len(appeared)} 条，"
                "没有可配对的候选（不是结构无效，是本期没有换血）"
            ),
            metrics={"vanished": len(vanished), "appeared": len(appeared)},
        )

    entries: list[dict[str, Any]] = []
    max_similarity = 0.0
    for section in sorted({it.section for it in vanished} & {it.section for it in appeared}):
        olds = [it for it in vanished if it.section == section]
        news = [it for it in appeared if it.section == section]
        if not olds or not news:
            continue
        corpus = [tokenize(f"{it.title} {it.summary}") for it in [*olds, *news]]
        if not any(corpus):
            continue
        try:
            matrix = TfidfVectorizer(max_features=20000).fit_transform(corpus)
        except ValueError:
            continue  # 空词表：整段都是停用词
        sim = cosine_similarity(matrix)
        for i, old in enumerate(olds):
            scored = [(float(sim[i][len(olds) + j]), new) for j, new in enumerate(news)]
            max_similarity = max(max_similarity, *(score for score, _ in scored))
            hits = sorted(
                (pair for pair in scored if pair[0] >= similarity_threshold),
                key=lambda pair_: pair_[0],
                reverse=True,
            )
            for score, new in hits[:top_k]:
                entries.append(
                    {
                        "section": section,
                        "t0_item_id": old.item_id,
                        "t0_title": old.title,
                        "t0_hot": _round(old.hot_score, 2),
                        "t1_item_id": new.item_id,
                        "t1_title": new.title,
                        "t1_hot": _round(new.hot_score, 2),
                        "similarity": _round(score),
                        "shared_terms": _shared_terms(old.title, new.title, 5),
                    }
                )
    entries.sort(key=lambda e: float(e["similarity"]), reverse=True)
    return StructureReport(
        key=key,
        name=name,
        status=STATUS_OK,
        entry_count=len(entries),
        entries=tuple(entries),
        notes=(
            f"T0={a.day} T1={b.day}；配对口径 = 同板块 + 标题/摘要 TF-IDF 余弦"
            f"≥{similarity_threshold}（topic_id 跨天不稳定，不可用）"
        ),
        metrics={
            "vanished": len(vanished),
            "appeared": len(appeared),
            "max_similarity": _round(max_similarity),
        },
    )


def _shared_terms(left: str, right: str, limit: int) -> list[str]:
    a = {t for t in tokenize(left).split() if len(t) > 1}
    b = {t for t in tokenize(right).split() if len(t) > 1}
    shared = sorted(a & b, key=lambda t: (-len(t), t))
    return shared[:limit]


# ══════════════════════════════════════════════════════════════════════════
# ⑤ 在榜轨迹的四类变化
# ══════════════════════════════════════════════════════════════════════════

KIND_DROPPED = "dropped"  # 跌出 Top30
KIND_NEW = "new"  # 真新
KIND_RETURNED = "returned"  # 重回
KIND_FLUCTUATING = "fluctuating"  # 波动
KIND_PERSISTENT = "persistent"  # 持续在榜（不是事件，仅计数）
KIND_FLASH = "single_day_flash"  # 单日闪现（不是事件，仅计数）


def emergence(
    index: CrossPeriodIndex, *, tracks: dict[str, ItemTrack] | None = None
) -> StructureReport:
    """按在榜轨迹把条目分成四类：跌出 / 真新 / 重回 / 波动。

    **措辞铁律**：`daily.json` 的 items 只是 brief 渲染集（Top30）。
    - "跌出" 只能是 **跌出 Top30**，绝不能说成"消失/退场"；
    - "真新" 只能是 **本窗口内首次出现**，窗口左边界之外的历史不可知；
    - "重回" 是断过之后又在**最后一天**回到榜；
    - "波动" 是断过又离开（或进出 ≥3 次），属噪音，不算涌现也不算断档。

    另有两类不是"变化事件"，只进 metrics 不进 entries：
    `持续在榜`（今天在榜且从未断过）、`单日闪现`（只出现过一天且已不在榜）。
    """
    key, name = "emergence", "⑤ 在榜变化（跌出/真新/重回/波动）"
    if len(index.days) < 2:
        return _bad_report(key, name, 2, "至少需要 2 天日报")
    tracks = tracks if tracks is not None else build_tracks(index)
    today = index.days[-1]
    day_index = {day: i for i, day in enumerate(index.days)}
    section_counts = _section_counts_by_day(index)
    schema_changes = _schema_change_days(index)
    bad_by_section = _bad_days_by_section(index)

    grouped: dict[str, list[dict[str, Any]]] = {
        KIND_DROPPED: [],
        KIND_NEW: [],
        KIND_RETURNED: [],
        KIND_FLUCTUATING: [],
    }
    counts = {
        KIND_DROPPED: 0,
        KIND_NEW: 0,
        KIND_RETURNED: 0,
        KIND_FLUCTUATING: 0,
        KIND_PERSISTENT: 0,
        KIND_FLASH: 0,
    }

    for track in tracks.values():
        segments = len(track.runs)
        if segments >= 3 or (segments == 2 and not track.present_today):
            kind = KIND_FLUCTUATING
        elif track.present_today and track.first_seen == today:
            kind = KIND_NEW
        elif track.present_today and segments == 2:
            kind = KIND_RETURNED
        elif track.present_today:
            kind = KIND_PERSISTENT
        elif segments == 1 and track.longest_run >= 2:
            kind = KIND_DROPPED
        else:
            kind = KIND_FLASH
        counts[kind] += 1
        if kind not in grouped:
            continue

        entry: dict[str, Any] = {
            "kind": kind,
            "item_id": track.item_id,
            "title": track.title,
            "source": track.source,
            "section": track.section,
            "days_on": track.days_on,
            "longest_run": track.longest_run,
            "first_seen": track.first_seen,
            "last_seen": track.last_seen,
            "current_run": track.current_run,
        }
        if track.last_seen is not None:
            pos = day_index.get(track.last_seen, -1)
            entry["hot_at_last_seen"] = _round(track.series_day_map()[track.last_seen], 2)
            if kind == KIND_DROPPED and 0 <= pos < len(index.days) - 1:
                entry["dropped_on"] = index.days[pos + 1]

        # ★ 归因：跌出不一定发生在内容上。2026-10-18 有 13 条「论文与研究」
        # 集体跌出，真实原因是当天该板块渲染 0 条（hf_papers degraded=0），
        # 不是话题更替。这类事件必须标出来并从趋势里剔除。
        attribution = "normal"
        if kind == KIND_DROPPED and "dropped_on" in entry:
            drop_day = str(entry["dropped_on"])
            if drop_day in bad_by_section.get(track.section, set()) or (
                section_counts.get(drop_day, {}).get(track.section, 0) == 0
            ):
                attribution = "section_empty"
            elif drop_day in schema_changes:
                attribution = "section_schema_change"
        entry["attribution"] = attribution
        entry["trend_eligible"] = attribution == "normal" and track.days_on >= 2
        if track.days_on < 2:
            entry["caution"] = "单日，不构成趋势"
        grouped[kind].append(entry)

    for kind in (KIND_DROPPED, KIND_NEW, KIND_RETURNED, KIND_FLUCTUATING):
        grouped[kind].sort(
            key=lambda e: (int(e["longest_run"]), float(e.get("hot_at_last_seen") or 0.0)),
            reverse=True,
        )
    entries = [
        *grouped[KIND_DROPPED],
        *grouped[KIND_NEW],
        *grouped[KIND_RETURNED],
        *grouped[KIND_FLUCTUATING],
    ]

    single_day = [e for e in entries if int(e.get("days_on", 0)) < 2]
    ineligible = [e for e in entries if not e.get("trend_eligible")]
    return StructureReport(
        key=key,
        name=name,
        status=STATUS_OK,
        entry_count=len(entries),
        entries=tuple(entries),
        notes=(
            f"窗口 {index.days[0]}→{today}（{len(index.days)} 天）；"
            "「跌出」= 连续在榜 ≥2 天后不再出现在 Top30（不等于消失）；"
            "「真新」= 本窗口内首次出现（左边界外不可知）；"
            "「波动」= 断过又离开或进出 ≥3 次；"
            "attribution != normal 的事件（板块整块渲染为空 / 板块口径变更）"
            "不得计入趋势"
        ),
        metrics={
            **counts,
            "tracks_total": len(tracks),
            "window_days": len(index.days),
            "dropped_section_empty": sum(
                1 for e in entries if e.get("attribution") == "section_empty"
            ),
            "dropped_schema_change": sum(
                1 for e in entries if e.get("attribution") == "section_schema_change"
            ),
            "trend_eligible_entries": len(entries) - len(ineligible),
            "ineligible_entries": len(ineligible),
            "single_day_entries": len(single_day),
            "schema_change_days": sorted(schema_changes),
        },
    )


# ══════════════════════════════════════════════════════════════════════════
# ⑥ 持续性分布
# ══════════════════════════════════════════════════════════════════════════


def persistence(
    index: CrossPeriodIndex, *, tracks: dict[str, ItemTrack] | None = None
) -> StructureReport:
    """按轨迹分桶（最长连续在榜 1-2 / 3-4 / ≥5 天）。

    不再依赖 `streak_days`：该字段只有 10-17 起才有，且是单日快照里的自报值；
    轨迹才是从已 commit 的报告里直接算出来、可复现的口径。

    "常青"需要 ≥14 天窗口才有区分度，当前窗口不够就明说（`required_days`）。
    """
    key, name = "persistence", "⑥ 持续性分布"
    if not index.days:
        return _bad_report(key, name, 2, "没有任何日报")
    tracks = tracks if tracks is not None else build_tracks(index)
    if not tracks:
        return _bad_report(key, name, 2, "没有解析到任何条目")

    buckets: tuple[tuple[str, int, int | None], ...] = (
        ("1-2", 1, 2),
        ("3-4", 3, 4),
        ("≥5", 5, None),
    )
    entries: list[dict[str, Any]] = []
    for label, low, high in buckets:
        members = [
            t
            for t in tracks.values()
            if t.longest_run >= low and (high is None or t.longest_run <= high)
        ]
        members.sort(key=lambda t: (-t.longest_run, -t.days_on))
        entries.append(
            {
                "bucket": label,
                "count": len(members),
                "items": [
                    {
                        "item_id": t.item_id,
                        "title": t.title,
                        "longest_run": t.longest_run,
                        "days_on": t.days_on,
                        "current_run": t.current_run,
                        "first_seen": t.first_seen,
                        "last_seen": t.last_seen,
                    }
                    for t in members[:10]
                ],
            }
        )

    observed = max(t.longest_run for t in tracks.values())
    window = len(index.days)
    # 常青需要"连续在榜 ≥14 天"才有区分度；当前窗口不够就明说
    required = max(0, 14 - window) or None
    return StructureReport(
        key=key,
        name=name,
        status=STATUS_OK,
        entry_count=len(entries),
        entries=tuple(entries),
        required_days=required,
        notes=(
            f"窗口 {window} 天，最长连续在榜 {observed} 天；"
            "分桶依据 = 最长连续在榜天数（不是总在榜天数，也不是 streak_days）；"
            "≥5 桶当前只能证明「连续几天在榜」，不能证明「常青」（需 ≥14 天窗口）"
        ),
        metrics={
            "tracks_total": len(tracks),
            "max_longest_run": observed,
            "window_days": window,
        },
    )


# ══════════════════════════════════════════════════════════════════════════
# ⑦ 来源份额变化
# ══════════════════════════════════════════════════════════════════════════


def source_share(
    index: CrossPeriodIndex,
    *,
    t0: str | None = None,
    t1: str | None = None,
    homogeneous: bool = True,
    full_window: bool = False,
    min_segment_days: int = 3,
) -> StructureReport:
    """按 source 统计条目数与热度份额的变化。

    与 ① 同口径：默认只在最后一段"源集合同构且 ≥3 天"的区间两端比较，
    否则源扩容本身会被读成"来源份额变化"。
    """
    key, name = "source_share", "⑦ 来源份额变化"
    window = _resolve_window(
        index,
        t0,
        t1,
        homogeneous=homogeneous,
        full_window=full_window,
        min_segment_days=min_segment_days,
    )
    if window is None or len(window) < 2:
        return _bad_report(
            key,
            name,
            min_segment_days if homogeneous and not full_window else 2,
            f"没有 ≥{min_segment_days} 天的源集合同构区间"
            if homogeneous and not full_window
            else "至少需要 2 天日报",
        )
    days_used = window
    a, b = index.snapshots[days_used[0]], index.snapshots[days_used[-1]]
    if not a.items or not b.items:
        return _bad_report(key, name, 2, "T0/T1 有一天空榜")

    count_a, hot_a = _source_totals(a)
    count_b, hot_b = _source_totals(b)
    share_ca, share_cb = _shares(count_a), _shares(count_b)
    share_ha, share_hb = _shares(hot_a), _shares(hot_b)

    entries: list[dict[str, Any]] = []
    # 某个来源在窗口内"整源 0 条"（failed/degraded 且 item_count=0）时，
    # 它的份额变化一律不可作趋势判断。仅"降级但仍有条目"（如 reddit 25 条）不算。
    failures = _source_failure_days(index)
    for source in sorted(set(count_a) | set(count_b)):
        share_c0, share_c1 = share_ca.get(source, 0.0), share_cb.get(source, 0.0)
        share_h0, share_h1 = share_ha.get(source, 0.0), share_hb.get(source, 0.0)
        failed_days = sorted(failures.get(source, set()))
        entries.append(
            {
                "source": source,
                "t0_count": int(count_a.get(source, 0)),
                "t1_count": int(count_b.get(source, 0)),
                "count_share_t0": _round(share_c0),
                "count_share_t1": _round(share_c1),
                "count_delta_pp": _round((share_c1 - share_c0) * 100, 2),
                "hot_share_t0": _round(share_h0),
                "hot_share_t1": _round(share_h1),
                "hot_delta_pp": _round((share_h1 - share_h0) * 100, 2),
                "collection_failure_days": failed_days,
                "trend_usable": not failed_days,
                "note": (
                    f"{'/'.join(failed_days)} 整源 0 条，份额变化不可作趋势" if failed_days else ""
                ),
            }
        )
    entries.sort(key=lambda e: abs(float(e["count_delta_pp"])), reverse=True)
    suspect = [str(e["source"]) for e in entries if not e["trend_usable"]]
    source_changes = sorted(source_change_days(index))
    return StructureReport(
        key=key,
        name=name,
        status=STATUS_OK,
        entry_count=len(entries),
        entries=tuple(entries),
        notes=(
            f"对比区间 {a.day}→{b.day}（{len(days_used)} 天，源集合同构）；"
            f"条目数与热度各算一次份额（pp=百分点）"
            + (f"；采集失败、不可作趋势：{'/'.join(suspect)}" if suspect else "")
            + (
                f"；跨源集合变更日（{'/'.join(source_changes)}）的比较已禁用"
                if source_changes
                else ""
            )
        ),
        metrics={
            "comparison_start": a.day,
            "comparison_end": b.day,
            "comparison_days": len(days_used),
            "full_window_days": len(index.days),
            "source_change_days": source_changes,
            "unusable_sources": suspect,
            "t0_total": len(a.items),
            "t1_total": len(b.items),
            "overlap_items": len(_common(a, b)),
        },
    )


def _source_totals(snap: DaySnapshot) -> tuple[dict[str, float], dict[str, float]]:
    counts: dict[str, float] = {}
    hots: dict[str, float] = {}
    for item in snap.items.values():
        source = item.source or "(unknown)"
        counts[source] = counts.get(source, 0.0) + 1
        hots[source] = hots.get(source, 0.0) + item.hot_score
    return counts, hots


# ══════════════════════════════════════════════════════════════════════════
# ⑧ 预言复盘
# ══════════════════════════════════════════════════════════════════════════


def prediction_review(index: CrossPeriodIndex, *, day: str | None = None) -> StructureReport:
    """读历史 predictions，比对已产生的验证结果。

    当前现实：54 条预言全部 pending，最早到期日 2026-11-16（30 天周期）。
    所以这里必然 0 条——这是**数据不足**，不是结构无价值。
    """
    key, name = "prediction_review", "⑧ 预言复盘"
    if not index.days:
        return _bad_report(key, name, 2, "没有任何日报")
    today = day or index.days[-1]
    if not index.predictions:
        return _bad_report(key, name, 2, "没有解析到任何 predictions.md 表格行")

    verified = [p for p in index.predictions if p.verdict]
    pending = [p for p in index.predictions if not p.verdict]
    due_dates = sorted({p.due_date for p in pending if p.due_date})
    earliest = due_dates[0] if due_dates else ""
    required = _days_until(today, earliest)

    entries: list[dict[str, Any]] = [
        {
            "statement": p.statement,
            "evidence_ids": list(p.evidence_ids),
            "due_date": p.due_date,
            "confidence": p.confidence,
            "verdict": p.verdict,
            "verdict_note": p.verdict_note,
        }
        for p in verified
    ]
    status = STATUS_OK if verified else STATUS_INSUFFICIENT
    return StructureReport(
        key=key,
        name=name,
        status=status,
        entry_count=len(verified),
        entries=tuple(entries),
        required_days=required,
        missing=() if verified else (f"最早的预言到期日是 {earliest}，当前日报只到 {today}",),
        notes=(
            f"共 {len(index.predictions)} 条预言（仅 predictions.md 里的 LLM 产物，"
            f"不含手写预言）：已验证 {len(verified)}、待验证 {len(pending)}；"
            "预言周期 7/30/90 天，复盘最早要等 7 天周期的预言到期"
        ),
        metrics={
            "total": len(index.predictions),
            "verified": len(verified),
            "pending": len(pending),
            "earliest_due": earliest,
            "latest_day": today,
        },
    )


def _days_until(today: str, due: str) -> int | None:
    try:
        return max(0, (date.fromisoformat(due) - date.fromisoformat(today)).days + 1)
    except ValueError:
        return None


# ══════════════════════════════════════════════════════════════════════════
# ⑨ 未发生的预期
# ══════════════════════════════════════════════════════════════════════════


def unrealized(
    index: CrossPeriodIndex,
    *,
    t0: str | None = None,
    t1: str | None = None,
    flat_delta: float = DEFAULT_FLAT_DELTA,
) -> StructureReport:
    """上期被标为「值得观察」但本期没有发生的条目。

    **口径说明（现有数据的唯一可行解）**：日报里没有专门的 watchlist 字段，
    唯一的"值得观察"人工标记是 `underrated`（被低估的条目）。它的元素是
    `标题——理由` 字符串、**不带 item_id**，因此按标题（`——` 前的前缀）回连条目；
    回连不上的只计数、不臆造 id。
    """
    key, name = "unrealized", "⑨ 未发生的预期"
    pair = _resolve_pair(index, t0, t1)
    if pair is None:
        return _bad_report(key, name, 2, "至少需要 2 天日报")
    a, b = index.snapshots[pair[0]], index.snapshots[pair[1]]
    if not a.underrated:
        return _bad_report(key, name, 3, f"{a.day} 没有 underrated 字段（10-15 / 10-16 为空数组）")

    by_title = {it.title: it for it in a.items.values() if it.title}
    entries: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for line in a.underrated:
        title = line.split("——")[0].strip()
        item = by_title.get(title) or _best_containment(title, a)
        if item is None:
            unmatched.append(title)
            continue
        new = b.items.get(item.item_id)
        if new is None:
            outcome, delta = "vanished", None
        else:
            delta = new.hot_score - item.hot_score
            outcome = "flat" if abs(delta) < flat_delta else "moved"
        if outcome == "moved":
            continue  # 预期"发生了"，不属于本结构
        entries.append(
            {
                "item_id": item.item_id,
                "title": item.title,
                "source": item.source,
                "section": item.section,
                "marker": line,
                "t0_hot": _round(item.hot_score, 2),
                "t1_hot": _round(new.hot_score, 2) if new else None,
                "delta": _round(delta, 2) if delta is not None else None,
                "outcome": outcome,
            }
        )
    entries.sort(key=lambda e: float(e["t0_hot"]), reverse=True)
    return StructureReport(
        key=key,
        name=name,
        status=STATUS_OK,
        entry_count=len(entries),
        entries=tuple(entries),
        notes=(
            f"T0={a.day} T1={b.day}；标记来源=underrated（无 item_id，按标题回连）；"
            f"判定 flat=|Δhot|<{flat_delta}、vanished=T1 不在榜；回连失败 {len(unmatched)} 条"
        ),
        metrics={
            "markers": len(a.underrated),
            "matched": len(a.underrated) - len(unmatched),
            "unmatched": len(unmatched),
        },
    )


def _best_containment(title: str, snap: DaySnapshot) -> PeriodItem | None:
    """标题回连的兜底：找包含该前缀的最短标题（避免把长标题误配到短标题）。"""
    needle = title.casefold()
    if not needle:
        return None
    candidates = [it for it in snap.items.values() if needle and needle in it.title.casefold()]
    if not candidates:
        return None
    return min(candidates, key=lambda it: len(it.title))


# ══════════════════════════════════════════════════════════════════════════
# 汇总
# ══════════════════════════════════════════════════════════════════════════


def compute_all(
    index: CrossPeriodIndex, *, t0: str | None = None, t1: str | None = None
) -> tuple[StructureReport, ...]:
    """按固定顺序算完 9 个结构；任何一个算不出都不影响其他 8 个。

    轨迹只构建一次，供 ②⑤⑥ 共用（30 条 × 7 天的规模下开销可忽略，
    但保持单一入口能保证三个结构看到的是同一份轨迹）。
    """
    tracks = build_tracks(index)
    return (
        heat_migration(index, t0=t0, t1=t1),
        co_movement(index, tracks=tracks),
        divergence(index, t0=t0, t1=t1),
        substitution(index, t0=t0, t1=t1),
        emergence(index, tracks=tracks),
        persistence(index, tracks=tracks),
        source_share(index, t0=t0, t1=t1),
        prediction_review(index, day=t1),
        unrealized(index, t0=t0, t1=t1),
    )
