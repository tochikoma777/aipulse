"""M5 S3 自验证：L1 硬判据 / L2 信息增量 / L3 跨期回检 / L4 校准追踪。

设计原则：

- **离线**：只读已生成的 Markdown 与 `data/reports/**`，不调 LLM（成本 0）。
  生成时的判据（字数/套话/违规/锚定）与 L1 共用同一套函数，避免"生成时算一遍、
  自检时另算一遍"的口径漂移。
- **能抓"正确的废话"**：L2 不看字数与套话，只看「输入里不存在」的结论
  （跨条目关联 / 替代 / 背离 / 外部命名实体）。
- **无数据就说无数据**：L3 没有到期预言时不编命中率；L4 首期只建基线，
  不把"无法校准"写成"校准通过"。

状态文件（都在 `data/reports/trend/` 下，随报告入库）：

- `watchlist.json`：每期"下期观察"的条目 + 待核对日期，下期自动核对在榜状态。
- `calibration.json`：每期"结构变化/二阶影响"声称过的条目 id，下期算存活率。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from aipulse.analysis.cross_period import (
    CrossPeriodIndex,
    StructureReport,
    build_tracks,
    compute_all,
)
from aipulse.reasoning.trend import (
    BOILERPLATE_PHRASES,
    SEGMENTS,
    build_evidence,
    char_count,
    segment_violations,
    slice_index,
    weak_correlation_present,
)

# ── 判定值 ──────────────────────────────────────────────────────────────────
PASS = "pass"
WARN = "warn"
FAIL = "fail"
NO_DATA = "no_data"
BASELINE_ONLY = "baseline_only"

# SSOT 对周报正文的要求
TOTAL_MIN_CHARS = 2000
TOTAL_MAX_CHARS = 4000
# 增量少于这个数视为"没有超过基线"，判失败
MIN_INCREMENTS = 3
# L4：存活率低于这个值说明系统在过度声称
MIN_SURVIVAL_RATE = 0.5

_SECTION_RE = re.compile(r"^##\s+(\d+)\.\s*(.+)$", re.M)
_ITEM_ID_RE = re.compile(r"it_[0-9a-f]{6,}")
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
# 关系词：出现它才说明模型在条目之间建立了输入里没有的关系
_RELATION_WORDS = (
    "替代",
    "取代",
    "承接",
    "挤压",
    "背离",
    "同向",
    "反向",
    "让位",
    "转移",
    "溢出",
    "此消彼长",
)
# 结构词：配合数字才说明用到了跨期计算，而不是抄条目数字
_STRUCTURE_WORDS = ("份额", "斜率", "持续性", "来源构成", "板块")
# 纯数值比较：可归约到基线（"A 比 B 高 0.83"），不算信息增量
_PAIRWISE_WORDS = ("高于", "低于", "较多", "较少", "较", "相比", "分别")
_ENTITY_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Za-z0-9.+-]{2,}(?![A-Za-z0-9])")
_ENTITY_STOP = frozenset({"Top", "Top30", "AI", "LLM", "API", "JSON", "Markdown", "Brier"})

_TITLE_TO_KEY: dict[str, str] = {title: key for key, title, _ in SEGMENTS}


@dataclass(frozen=True)
class LayerResult:
    """一层自验证的结论。"""

    layer: str
    name: str
    verdict: str
    summary: str
    metrics: dict[str, Any] = field(default_factory=dict)
    findings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "name": self.name,
            "verdict": self.verdict,
            "summary": self.summary,
            "metrics": self.metrics,
            "findings": list(self.findings),
        }


@dataclass(frozen=True)
class SelfCheckReport:
    """四层结论 + 报告标识。"""

    issue: str
    comparison_start: str
    comparison_end: str
    layers: tuple[LayerResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue": self.issue,
            "comparison": [self.comparison_start, self.comparison_end],
            "layers": [layer.to_dict() for layer in self.layers],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# 自验证 · {self.issue}",
            "",
            f"比较区间 {self.comparison_start} → {self.comparison_end}",
            "",
        ]
        for layer in self.layers:
            lines.append(f"## {layer.layer} {layer.name} — {layer.verdict}")
            lines.append("")
            lines.append(layer.summary)
            for finding in layer.findings:
                lines.append(f"- {finding}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


# ══════════════════════════════════════════════════════════════════════════
# 解析
# ══════════════════════════════════════════════════════════════════════════


def parse_markdown(text: str) -> dict[str, str]:
    """按 `## N. 标题` 切出各节正文；标题未知的节忽略（如自验证报告本身）。"""
    matches = list(_SECTION_RE.finditer(text))
    out: dict[str, str] = {}
    for pos, match in enumerate(matches):
        end = matches[pos + 1].start() if pos + 1 < len(matches) else len(text)
        key = _TITLE_TO_KEY.get(match.group(2).strip())
        if key and key not in out:
            out[key] = text[match.end() : end].strip()
    return out


def sections_from_machine(payload: Any) -> dict[str, str]:
    """从机器层 `weekly.json` 取出 7 节正文——与 `parse_markdown` 同构。

    S5 之后人类层 `weekly.md` 不再包含 7 节正文（正文零裸 ID、只给结论），
    L1-L4 因此改读机器层。**四层的判定逻辑一行没改**，只是输入源换成了 JSON。
    """
    if not isinstance(payload, dict):
        return {}
    out: dict[str, str] = {}
    for segment in payload.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        key = str(segment.get("key") or "")
        body = str(segment.get("body") or "")
        if key and key not in out:
            out[key] = body
    return out


def _clauses(text: str) -> list[str]:
    return [c.strip() for c in re.split(r"[。；;！？\n]", text) if c.strip()]


# ══════════════════════════════════════════════════════════════════════════
# L1 硬判据
# ══════════════════════════════════════════════════════════════════════════


def check_l1(
    sections: dict[str, str],
    index: CrossPeriodIndex,
    reports: dict[str, StructureReport],
) -> LayerResult:
    """字数区间 / 结构完整 / 套话 / 违规 / 锚定 id —— 全部可执行断言。"""
    weak = weak_correlation_present(reports)
    per_segment: dict[str, Any] = {}
    findings: list[str] = []
    missing = [key for key, _, _ in SEGMENTS if not sections.get(key, "").strip()]
    if missing:
        findings.append(f"缺节或空节：{'/'.join(missing)}")

    total = 0
    violation_total = 0
    boilerplate_total = 0
    for key, title, _ in SEGMENTS:
        body = sections.get(key, "")
        if not body:
            per_segment[key] = {"chars": 0, "ids": 0, "violations": ["缺节"]}
            continue
        evidence = build_evidence(index, reports, key)
        bad = segment_violations(body, key, evidence, weak_corr=weak)
        hits = [phrase for phrase in BOILERPLATE_PHRASES if phrase in body]
        chars = char_count(body)
        ids = sorted(set(_ITEM_ID_RE.findall(body)))
        total += chars
        violation_total += len(bad)
        boilerplate_total += len(hits)
        per_segment[key] = {
            "title": title,
            "chars": chars,
            "ids": len(ids),
            "violations": bad,
            "boilerplate": hits,
        }
        for item in bad:
            findings.append(f"{key}：{item}")
        if hits:
            findings.append(f"{key}：套话 {hits}")
        if key != "prediction_review" and not ids:
            findings.append(f"{key}：未锚定任何 item_id")

    in_range = TOTAL_MIN_CHARS <= total <= TOTAL_MAX_CHARS
    if not in_range:
        findings.append(f"全文 {total} 字，超出 SSOT {TOTAL_MIN_CHARS}-{TOTAL_MAX_CHARS}")
    verdict = (
        PASS
        if not missing and violation_total == 0 and boilerplate_total == 0 and in_range
        else FAIL
    )
    summary = (
        f"全文 {total} 字（区间 {TOTAL_MIN_CHARS}-{TOTAL_MAX_CHARS}："
        f"{'在区间内' if in_range else '越界'}），"
        f"违规 {violation_total}、套话 {boilerplate_total}、缺节 {len(missing)}。"
    )
    return LayerResult(
        layer="L1",
        name="硬判据",
        verdict=verdict,
        summary=summary,
        metrics={
            "total_chars": total,
            "in_range": in_range,
            "violations": violation_total,
            "boilerplate": boilerplate_total,
            "missing_segments": missing,
            "segments": per_segment,
        },
        findings=tuple(findings),
    )


# ══════════════════════════════════════════════════════════════════════════
# L2 信息增量
# ══════════════════════════════════════════════════════════════════════════


def _baseline_top(
    index: CrossPeriodIndex, reports: dict[str, StructureReport], size: int = 10
) -> list[dict[str, Any]]:
    """基线 = 比较区间末日的 Top N 与它们的相邻差。

    这是"不做任何分析、直接把榜单前十条列出来"的水平；长文必须超过它。
    """
    heat = reports.get("heat_migration")
    if heat is None:
        return []
    end = str(heat.metrics.get("comparison_end") or (index.days[-1] if index.days else ""))
    start = str(heat.metrics.get("comparison_start") or "")
    snap_end = index.snapshot(end)
    snap_start = index.snapshot(start) if start else None
    if snap_end is None:
        return []
    ranked = sorted(snap_end.items.values(), key=lambda it: it.hot_score, reverse=True)[:size]
    rows: list[dict[str, Any]] = []
    for pos, item in enumerate(ranked, 1):
        before = snap_start.items.get(item.item_id) if snap_start else None
        rows.append(
            {
                "rank": pos,
                "item_id": item.item_id,
                "title": item.title,
                "section": item.section,
                "hot": round(item.hot_score, 2),
                "delta": round(item.hot_score - before.hot_score, 2) if before else None,
            }
        )
    return rows


def _corpus(index: CrossPeriodIndex) -> set[str]:
    words: set[str] = set()
    for day in index.days:
        snap = index.snapshots[day]
        words.update(section.lower() for section in snap.sections)
        for item in snap.items.values():
            words.update(
                part.lower() for part in re.split(r"\W+", f"{item.title} {item.summary}") if part
            )
            if item.source:
                words.add(item.source.lower())
    return words


def check_l2(
    sections: dict[str, str],
    index: CrossPeriodIndex,
    reports: dict[str, StructureReport],
) -> LayerResult:
    """统计"输入里不存在"的结论：跨条目关联 / 替代 / 背离 / 外部命名实体。

    ★ 纯数值两两比较（"A 比 B 高 0.83"）**不计入增量**：它可以直接从基线榜单算出来，
    是最典型的"锚定充足但零信息量"。
    """
    baseline = _baseline_top(index, reports)
    baseline_ids = {row["item_id"] for row in baseline}
    corpus = _corpus(index)

    increments: list[dict[str, str]] = []
    pairwise = 0
    cited: set[str] = set()
    external_entities: set[str] = set()
    for key, _, _ in SEGMENTS:
        body = sections.get(key, "")
        if not body:
            continue
        for clause in _clauses(body):
            ids = sorted(set(_ITEM_ID_RE.findall(clause)))
            cited.update(ids)
            has_number = bool(_NUMBER_RE.search(clause))
            relation = next((w for w in _RELATION_WORDS if w in clause), "")
            structure = next((w for w in _STRUCTURE_WORDS if w in clause), "")
            entities = {
                e
                for e in _ENTITY_RE.findall(clause)
                if e not in _ENTITY_STOP and e.lower() not in corpus
            }
            if entities:
                external_entities.update(entities)
                increments.append(
                    {
                        "kind": "external_entity",
                        "segment": key,
                        "clause": clause,
                        "detail": "/".join(sorted(entities)),
                    }
                )
                continue
            if len(ids) >= 2 and relation:
                increments.append(
                    {"kind": "cross_item", "segment": key, "clause": clause, "detail": relation}
                )
            elif len(ids) >= 2 and has_number and any(w in clause for w in _PAIRWISE_WORDS):
                # 两两数值比较：可归约到基线，不算增量
                pairwise += 1
            elif ids and structure and has_number:
                increments.append(
                    {"kind": "structure", "segment": key, "clause": clause, "detail": structure}
                )

    # 「替代对」「背离」是独立的两个结构，单独统计，避免被 structure 淹没
    substitution = [i for i in increments if i["kind"] == "cross_item" and "替代" in i["detail"]]
    divergence = [i for i in increments if i["kind"] == "cross_item" and "背离" in i["detail"]]

    total = len(increments)
    if total >= MIN_INCREMENTS:
        verdict = PASS
    elif total == 0:
        verdict = FAIL
    else:
        verdict = WARN
    overlap = len(cited & baseline_ids)
    coverage = f"{overlap}/{len(cited)}" if cited else "0/0"
    summary = (
        f"较基线（Top{len(baseline)} 榜单）新增结论 {total} 条"
        f"（跨条目 {sum(1 for i in increments if i['kind'] == 'cross_item')}、"
        f"结构 {sum(1 for i in increments if i['kind'] == 'structure')}、"
        f"外部实体 {len(external_entities)}）；"
        f"纯数值两两比较 {pairwise} 条（不计入增量）。"
    )
    findings: list[str] = []
    if total == 0:
        findings.append("增量为 0：长文没有超出「直接列 Top10」的水平")
    if total < MIN_INCREMENTS:
        findings.append(f"增量 {total} < {MIN_INCREMENTS} 条，判定为不足")
    if cited and overlap * 2 < len(cited):
        findings.append(f"引用条目只有 {coverage} 落在基线 Top{len(baseline)} 内，其余来自榜单尾部")
    if pairwise > max(3, total):
        findings.append(
            f"两两数值比较 {pairwise} 条多于有效增量 {total} 条：疑似用数字堆砌代替分析"
        )
    return LayerResult(
        layer="L2",
        name="信息增量",
        verdict=verdict,
        summary=summary,
        metrics={
            "increments": total,
            "min_increments": MIN_INCREMENTS,
            "kinds": {
                "cross_item": sum(1 for i in increments if i["kind"] == "cross_item"),
                "structure": sum(1 for i in increments if i["kind"] == "structure"),
                "external_entity": len(external_entities),
                "substitution": len(substitution),
                "divergence": len(divergence),
            },
            "pairwise_numeric": pairwise,
            "baseline_top": baseline,
            "baseline_overlap": coverage,
            "examples": increments[:5],
        },
        findings=tuple(findings),
    )


# ══════════════════════════════════════════════════════════════════════════
# L3 跨期回检（含 watchlist 机制）
# ══════════════════════════════════════════════════════════════════════════


def _state_files(state_dir: Path, name: str) -> list[Path]:
    """本期状态文件 + 各期目录下的同名文件（按目录名 = 窗口末日排序）。

    ★ S5 起产物按窗口末日分目录，如果只读本期文件，跨期历史就丢了——
    而 L3（watchlist 核对）与 L4（存活率）要的正是跨期。
    """
    files = {state_dir / name}
    parent = state_dir.parent
    if parent.exists():
        files.update(parent.glob(f"*/{name}"))
    return sorted(p for p in files if p.is_file())


def _load_state(state_dir: Path, name: str) -> dict[str, Any]:
    """合并各期状态；`entries` 按 (issue, item_id) 去重，`issues` 按 key 去重。"""
    merged: dict[str, Any] = {}
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    issues: dict[str, Any] = {}
    for path in _state_files(state_dir, name):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        for entry in data.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            key = (str(entry.get("issue") or ""), str(entry.get("item_id") or ""))
            entries.setdefault(key, entry)
        for issue in data.get("issues") or []:
            if isinstance(issue, dict):
                issues.setdefault(str(issue.get("issue") or ""), issue)
    if entries:
        merged["entries"] = [entries[k] for k in sorted(entries)]
    if issues:
        merged["issues"] = [issues[k] for k in sorted(issues)]
    return merged


def _save_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _next_day(day: str) -> str:
    try:
        return (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    except ValueError:
        return ""


def check_l3(
    sections: dict[str, str],
    index: CrossPeriodIndex,
    *,
    state_dir: Path,
    write_state: bool = True,
) -> LayerResult:
    """预言命中率 + watchlist 在榜核对。

    - 预言：没有到期样本时输出 `no_data`，不给任何比率；
    - watchlist：本期写入待核对条目（check_on = 窗口末日次日），下期自动核对。
    """
    total = len(index.predictions)
    verified = [p for p in index.predictions if p.verdict]
    hits = [p for p in verified if p.verdict == "hit"]
    pending = [p for p in index.predictions if not p.verdict]
    earliest = min((p.due_date for p in pending if p.due_date), default="")

    path = state_dir / "watchlist.json"
    state = _load_state(state_dir, "watchlist.json")
    entries: list[dict[str, Any]] = list(state.get("entries") or [])
    latest = index.days[-1] if index.days else ""
    tracks = build_tracks(index)

    resolved: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("status") != "pending":
            continue
        check_on = str(entry.get("check_on") or "")
        if not check_on or not latest or check_on > latest:
            continue
        track = tracks.get(str(entry.get("item_id")))
        in_top = bool(track and track.present_today)
        entry["status"] = "still_on" if in_top else "dropped"
        entry["resolved_on"] = latest
        item = index.snapshots[latest].items.get(str(entry.get("item_id")))
        entry["resolved_hot"] = round(item.hot_score, 2) if item else None
        resolved.append(entry)

    created: list[dict[str, Any]] = []
    window_end = latest
    for item_id in sorted(set(_ITEM_ID_RE.findall(sections.get("watchlist", "")))):
        if any(
            str(e.get("item_id")) == item_id and str(e.get("issue")) == window_end for e in entries
        ):
            continue
        clause = next((c for c in _clauses(sections.get("watchlist", "")) if item_id in c), "")
        entry = {
            "issue": window_end,
            "item_id": item_id,
            "check_on": _next_day(window_end),
            "expectation": clause[:120],
            "status": "pending",
        }
        entries.append(entry)
        created.append(entry)

    if write_state:
        _save_state(path, {"entries": entries})

    no_prediction_data = not verified
    pending_after = [e for e in entries if e.get("status") == "pending"]
    history = [e for e in entries if e.get("status") in {"still_on", "dropped"}]
    still_on_history = sum(1 for e in history if e.get("status") == "still_on")

    if verified:
        pred_note = (
            f"预言 {total} 条已验证 {len(verified)}、命中 {len(hits)}"
            f"（{len(hits) / len(verified):.0%}）"
        )
    else:
        pred_note = f"预言 {total} 条无到期样本（最早到期 {earliest or '未知'}），不给命中率"

    if resolved:
        still_on = sum(1 for e in resolved if e.get("status") == "still_on")
        verdict = PASS
        watch_note = (
            f"本轮核对 {len(resolved)} 条 watchlist："
            f"仍在榜 {still_on}、跌出 {len(resolved) - still_on}"
        )
    elif history:
        # 重跑同一期时不该退化成"无待核对项"：历史核对结果仍要报出来
        verdict = PASS
        watch_note = (
            f"本轮无新增核对项；历史已核对 {len(history)} 条："
            f"仍在榜 {still_on_history}、跌出 {len(history) - still_on_history}"
        )
    elif created:
        verdict = NO_DATA
        check_on = str(created[0].get("check_on"))
        watch_note = f"watchlist 新建 {len(created)} 条，核对日 {check_on}，本轮记 0 条"
    else:
        verdict = NO_DATA if no_prediction_data else PASS
        watch_note = "watchlist 无待核对项"

    summary = f"{pred_note}；{watch_note}。"

    findings: list[str] = []
    if no_prediction_data:
        findings.append("本周没有到期预言：不给命中率，等最早到期日再算。")
    if created:
        names = "/".join(str(e["item_id"]) for e in created)
        findings.append(f"watchlist 已登记 {len(created)} 条待核对项（{names}）")
    return LayerResult(
        layer="L3",
        name="跨期回检",
        verdict=verdict,
        summary=summary,
        metrics={
            "predictions_total": total,
            "predictions_verified": len(verified),
            "predictions_hit": len(hits),
            "predictions_pending": len(pending),
            "earliest_due": earliest,
            "hit_rate": (len(hits) / len(verified)) if verified else None,
            "watchlist_created": created,
            "watchlist_resolved": resolved,
            "watchlist_pending": len(pending_after),
            "state_file": str(path),
        },
        findings=tuple(findings),
    )


# ══════════════════════════════════════════════════════════════════════════
# L4 校准追踪
# ══════════════════════════════════════════════════════════════════════════


def check_l4(
    sections: dict[str, str],
    index: CrossPeriodIndex,
    *,
    state_dir: Path,
    write_state: bool = True,
) -> LayerResult:
    """上期"结构性变化"声称的条目，本期存活率；低于阈值即为过度声称。"""
    path = state_dir / "calibration.json"
    state = _load_state(state_dir, "calibration.json")
    issues: list[dict[str, Any]] = list(state.get("issues") or [])
    latest = index.days[-1] if index.days else ""

    claimed: list[str] = []
    for key in ("structural_changes", "second_order_effects"):
        claimed.extend(_ITEM_ID_RE.findall(sections.get(key, "")))
    claimed_ids = sorted(set(claimed))

    resolutions: list[dict[str, Any]] = []
    for issue in issues:
        if issue.get("resolved"):
            continue
        window_end = str(issue.get("window_end") or "")
        if not window_end or latest <= window_end:
            continue
        later = [d for d in index.days if d > window_end]
        survived: list[str] = []
        dropped: list[str] = []
        for item_id in issue.get("claimed_ids") or []:
            seen = any(item_id in index.snapshots[d].items for d in later)
            (survived if seen else dropped).append(str(item_id))
        total = len(survived) + len(dropped)
        rate = len(survived) / total if total else None
        issue["resolved"] = {
            "checked_on": latest,
            "survived": survived,
            "dropped": dropped,
            "survival_rate": rate,
        }
        resolutions.append(issue)

    if claimed_ids and not any(str(i.get("issue")) == latest for i in issues):
        issues.append(
            {
                "issue": latest,
                "window_end": latest,
                "claimed_ids": claimed_ids,
                "resolved": None,
            }
        )

    if write_state:
        _save_state(path, {"issues": issues})

    history = [i for i in issues if i.get("resolved")]
    if history:
        # 重跑同一期时，本轮可能没有新回检；仍要报出最近一次结论，
        # 否则第二次运行会退化成"首期基线"，看起来像机制没生效。
        recent = history[-1]
        recent_rate = recent["resolved"].get("survival_rate")
        rates = [
            float(i["resolved"]["survival_rate"])
            for i in history
            if i["resolved"].get("survival_rate") is not None
        ]
        avg = sum(rates) / len(rates) if rates else None
        verdict = PASS if (avg is None or avg >= MIN_SURVIVAL_RATE) else FAIL
        latest_note = (
            f"最近回检 {recent['issue']}（{recent['resolved'].get('checked_on')}）："
            f"{(recent_rate if recent_rate is not None else 0):.0%} 存活；"
            f"本轮新回检 {len(resolutions)} 期"
        )
        summary = latest_note
        findings = tuple(
            f"{i['issue']}：存活率 {float(i['resolved']['survival_rate']):.0%}"
            for i in history[-3:]
            if i["resolved"].get("survival_rate") is not None
        )
        if len(history) == 1 and recent["resolved"].get("checked_on") == _next_day(
            str(recent.get("issue"))
        ):
            findings += ("只隔 1 天，本轮存活率仅用于验证机制，不作质量判定。",)
        if avg is not None and avg < MIN_SURVIVAL_RATE:
            findings += ("存活率低于 50%：结构声称偏多，下期应提高准入门槛",)
    else:
        verdict = BASELINE_ONLY
        summary = (
            f"首期基线已建立（本期声称 {len(claimed_ids)} 个条目），尚无下期数据，不足以校准。"
        )
        findings = ("机制已生效：下期会自动回检这些条目的存活率。",)

    return LayerResult(
        layer="L4",
        name="校准追踪",
        verdict=verdict,
        summary=summary,
        metrics={
            "claimed_ids": claimed_ids,
            "min_survival_rate": MIN_SURVIVAL_RATE,
            "resolved_issues": [i["issue"] for i in history],
            "resolved_this_run": [r["issue"] for r in resolutions],
            "state_file": str(path),
        },
        findings=findings,
    )


# ══════════════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════════════


def run_selfcheck(
    source: str | dict[str, Any],
    index: CrossPeriodIndex,
    *,
    state_dir: str | Path,
    window_days: int = 7,
    write_state: bool = True,
) -> SelfCheckReport:
    """对一份已生成的周报跑完 L1-L4。纯离线，不调 LLM。

    `source` 可以是机器层 `weekly.json` 的 dict（S5 起的默认），
    也可以是旧格式 Markdown 文本——两条路都归约成同一个 `sections`。
    """
    sliced = slice_index(index, window_days)
    if not sliced.days:
        return SelfCheckReport(issue="", comparison_start="", comparison_end="", layers=())
    reports = {report.key: report for report in _compute(sliced)}
    sections = sections_from_machine(source) if isinstance(source, dict) else parse_markdown(source)
    heat = reports.get("heat_migration")
    start = str(heat.metrics.get("comparison_start") or sliced.days[0]) if heat else sliced.days[0]
    end = str(heat.metrics.get("comparison_end") or sliced.days[-1]) if heat else sliced.days[-1]
    directory = Path(state_dir)
    return SelfCheckReport(
        issue=sliced.days[-1],
        comparison_start=start,
        comparison_end=end,
        layers=(
            check_l1(sections, sliced, reports),
            check_l2(sections, sliced, reports),
            check_l3(sections, sliced, state_dir=directory, write_state=write_state),
            check_l4(sections, sliced, state_dir=directory, write_state=write_state),
        ),
    )


def _compute(index: CrossPeriodIndex) -> tuple[StructureReport, ...]:
    """算出 9 个结构：L1 要用与生成时同一份证据判「复述标题」。"""
    return compute_all(index)


__all__ = [
    "BASELINE_ONLY",
    "FAIL",
    "MIN_INCREMENTS",
    "MIN_SURVIVAL_RATE",
    "NO_DATA",
    "PASS",
    "WARN",
    "LayerResult",
    "SelfCheckReport",
    "check_l1",
    "check_l2",
    "check_l3",
    "check_l4",
    "parse_markdown",
    "run_selfcheck",
]
