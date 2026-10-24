"""自动选题（C2）：从最新 trend 产物里挑一个"最值得辩"的议题。

为什么需要它：`weekly_debate_enabled` 一直是死开关——留着配置却没人读，
下一个人只会问"这开关是不是坏了"。

选题不是猜。争议度由三个**可观测**信号加分，每条都打印出来，
所以"为什么选它"永远可复核：

| 信号 | 分值 | 含义 |
|---|---|---|
| 板块份额 \|Δ\| ≥ 3pp | 3 | 结构真的在动，值得辩"迁移还是脉冲" |
| 本板块被上期周报明确下过判断 | 2 | 有可检验的主张；辩论可以判它对错 |
| 本板块有 watchlist 条目刚被判 dropped | 2 | 上期的判断刚被打脸，争议最大 |
| 本板块还有 watchlist 条目未到期 | 1 | 结论悬着，正是该辩的时候 |

平手时比 \|Δpp\|，再比板块名——保证同样输入永远选出同一个话题。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aipulse.analysis.cross_period import CrossPeriodIndex, compute_all

__all__ = ["AutoTopic", "latest_trend_dir", "pick_auto_topic"]

_DELTA_MIN_PP = 3.0
_CLAIM_HEAD = 18


@dataclass(frozen=True)
class AutoTopic:
    """一个自动选出的话题，带完整的选择依据。"""

    topic: str
    source: str
    section: str
    score: int
    reasons: tuple[str, ...]

    def announcement(self) -> str:
        lines = [f"已自动选题：{self.topic}（来源：{self.source}）", "选择依据："]
        lines.extend(f"  · {reason}" for reason in self.reasons)
        return "\n".join(lines)


def latest_trend_dir(reports_root: Path) -> Path | None:
    """最新一期 trend 目录（按目录名倒序，只认带 weekly.json 的）。"""
    candidates = sorted(p.parent for p in reports_root.glob("trend/*/weekly.json"))
    return candidates[-1] if candidates else None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _watchlist_entries(reports_root: Path) -> list[dict[str, Any]]:
    """合并各期 watchlist（分目录后单期只有自己那几条，跨期才是全貌）。"""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(reports_root.glob("trend/*/watchlist.json")):
        for entry in _load_json(path).get("entries") or []:
            if not isinstance(entry, dict):
                continue
            key = (str(entry.get("issue") or ""), str(entry.get("item_id") or ""))
            merged[key] = entry  # 后写优先：本期文件带最新 resolved
    return list(merged.values())


def _claim_head(text: str) -> str:
    """取判断里最像"标题"的那一截：首个分句，够长才用，否则整句截断。

    周报的判断通常写成「结论：展开」，直接用整句塞进议题会很啰嗦，
    而截断又会在半句处断掉。取第一个分句最接近人写议题的习惯。
    """
    cleaned = " ".join(text.split()).strip("。；，,.;")
    if not cleaned:
        return ""
    head = re.split(r"[：:，,；;]", cleaned)[0].strip()
    if len(head) >= 6:
        return head
    return cleaned if len(cleaned) <= _CLAIM_HEAD else cleaned[:_CLAIM_HEAD] + "…"


def pick_auto_topic(index: CrossPeriodIndex, reports_root: Path) -> AutoTopic | None:
    """挑争议度最高的板块并合成议题；没有 trend 产物时返回 None。"""
    trend_dir = latest_trend_dir(reports_root)
    if trend_dir is None or not index.days:
        return None

    weekly = _load_json(trend_dir / "weekly.json")
    judgements = [j for j in weekly.get("judgements") or [] if isinstance(j, dict)]
    # ★ 不能只看最新一天：watchlist 里 status=dropped 的条目按定义**不在**最新快照里，
    #   只看当天会让"刚被打脸"这个最强争议信号永远取不到板块。
    section_of: dict[str, str] = {}
    for day in index.days:
        snapshot = index.snapshots.get(day)
        if snapshot is None:
            continue
        for item_id, item in snapshot.items.items():
            if item.section:
                section_of[item_id] = item.section

    judged_sections: dict[str, str] = {}
    for judgement in judgements:
        claim = str(judgement.get("claim") or "").strip()
        for item_id in judgement.get("cited_item_ids") or []:
            section = section_of.get(str(item_id), "")
            if section and claim:
                judged_sections.setdefault(section, claim)

    entries = _watchlist_entries(reports_root)
    dropped: dict[str, int] = {}
    pending: dict[str, int] = {}
    for entry in entries:
        section = section_of.get(str(entry.get("item_id") or ""), "")
        if not section:
            continue
        if str(entry.get("status") or "") == "dropped":
            dropped[section] = dropped.get(section, 0) + 1
        if str(entry.get("resolved_on") or "") == "":
            pending[section] = pending.get(section, 0) + 1

    heat = next((r for r in compute_all(index) if r.key == "heat_migration"), None)
    deltas: dict[str, float] = {}
    if heat is not None:
        for entry in heat.entries:
            if not isinstance(entry, dict) or not entry.get("trend_usable"):
                continue
            value = entry.get("delta_pp")
            if isinstance(value, (int, float)):
                deltas[str(entry.get("section") or "")] = float(value)

    best: AutoTopic | None = None
    for section in sorted(set(deltas) | set(judged_sections) | set(dropped) | set(pending)):
        if not section:
            continue
        delta = deltas.get(section, 0.0)
        full_claim = judged_sections.get(section, "")
        score = 0
        reasons: list[str] = []
        if abs(delta) >= _DELTA_MIN_PP:
            score += 3
            reasons.append(f"板块份额 {delta:+.2f}pp（|Δ| ≥ {_DELTA_MIN_PP:.0f}pp，结构在动）")
        if section in judged_sections:
            score += 2
            reasons.append(f"上期周报明确下过判断：「{full_claim[:60]}」")
        if dropped.get(section):
            score += 2
            reasons.append(
                f"本期有 {dropped[section]} 条 watchlist 条目被判 dropped（上期判断被打脸）"
            )
        if pending.get(section):
            score += 1
            reasons.append(f"还有 {pending[section]} 条 watchlist 未到期（结论悬着）")
        if score == 0:
            continue

        claim = _claim_head(full_claim)
        if claim:
            question = f"{section}：{claim}——真实迁移还是单日脉冲？"
        else:
            question = f"{section} 板块份额变化——真实迁移还是单日脉冲？"
        candidate = AutoTopic(
            topic=question,
            source=f"trend/{trend_dir.name}",
            section=section,
            score=score,
            reasons=tuple(reasons),
        )
        if best is None or (
            candidate.score,
            abs(delta),
            candidate.section,
        ) > (best.score, abs(deltas.get(best.section, 0.0)), best.section):
            best = candidate
    return best
