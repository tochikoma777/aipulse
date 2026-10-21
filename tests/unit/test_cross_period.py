"""跨期结构计算单测（M5 S1）。

全部用临时目录里的假报告，不碰网络、不碰主库。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aipulse.analysis.cross_period import (
    STATUS_INSUFFICIENT,
    STATUS_OK,
    build_tracks,
    co_movement,
    comparison_segment,
    compute_all,
    divergence,
    emergence,
    heat_migration,
    homogeneous_segments,
    load_cross_period,
    persistence,
    prediction_review,
    source_change_days,
    source_share,
    substitution,
    unrealized,
)

# ── 构造工具 ───────────────────────────────────────────────────────────────


def _item(
    item_id: str,
    title: str,
    hot: float,
    *,
    source: str = "hackernews",
    metrics: dict[str, Any] | None = None,
    streak: int | None = None,
    summary: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": item_id,
        "title": title,
        "url": f"https://example.com/{item_id}",
        "source": source,
        "summary": summary,
        "hot_score": hot,
    }
    if metrics is not None:
        payload["metrics"] = metrics
    if streak is not None:
        payload["streak_days"] = streak
    return payload


def _day(
    root: Path,
    day: str,
    items: list[dict[str, Any]],
    *,
    sections: list[dict[str, Any]] | None = None,
    comments: list[dict[str, Any]] | None = None,
    underrated: list[str] | None = None,
    predictions_md: str | None = None,
    verdicts_md: str | None = None,
    raw_daily: str | None = None,
    source_runs: list[dict[str, Any]] | None = None,
) -> Path:
    target = root / Path(*day.split("-"))
    target.mkdir(parents=True, exist_ok=True)
    if raw_daily is not None:
        (target / "daily.json").write_text(raw_daily, encoding="utf-8")
    else:
        payload = {
            "date": day,
            "items": {it["id"]: it for it in items},
            "sections": sections or [],
            "comments": comments or [],
            "underrated": underrated or [],
        }
        (target / "daily.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    if predictions_md is not None:
        (target / "predictions.md").write_text(predictions_md, encoding="utf-8")
    if verdicts_md is not None:
        (target / "verdicts.md").write_text(verdicts_md, encoding="utf-8")
    if source_runs is not None:
        (target / "source_runs.json").write_text(
            json.dumps({"date": day, "sources": source_runs}, ensure_ascii=False),
            encoding="utf-8",
        )
    return target


def _section(name: str, ids: list[str]) -> dict[str, Any]:
    return {"name": name, "item_ids": ids}


PRED_HEADER = (
    "| 预言 | 类别 | 置信度 | 周期 | 到期日 | 判据 | 证据 id |\n|---|---|---|---|---|---|---|\n"
)
VERDICT_HEADER = "| 预言 | 判定 | 置信度 | 来源 | 判定方 | 依据 |\n|---|---|---|---|---|---|\n"


# ── 解析容错 ───────────────────────────────────────────────────────────────


def test_load_tolerates_four_historical_shapes(tmp_path: Path) -> None:
    """10-15 无 metrics / comments 空；10-17 用 why_it_matters；10-18 用 why；坏 JSON 跳过。"""
    _day(
        tmp_path,
        "2026-10-15",
        [_item("it_aaaaaa", "old shape", 10.0)],
        sections=[_section("开源项目", ["it_aaaaaa"]), _section("社区舆论", [])],
        comments=[],
    )
    _day(
        tmp_path,
        "2026-10-17",
        [_item("it_bbbbbb", "why_it_matters shape", 20.0, metrics={"points": 5})],
        sections=[_section("论文与研究", ["it_bbbbbb"])],
        comments=[{"item_id": "it_bbbbbb", "why_it_matters": "旧字段名"}],
    )
    _day(
        tmp_path,
        "2026-10-18",
        [_item("it_cccccc", "why shape", 30.0, metrics={"points": 9})],
        sections=[_section("论文与研究", ["it_cccccc"])],
        comments=[{"item_id": "it_cccccc", "why": "新字段名"}],
    )
    _day(tmp_path, "2026-10-19", [], raw_daily="{ not json")

    index = load_cross_period(tmp_path)
    assert index.days == ("2026-10-15", "2026-10-17", "2026-10-18")
    assert index.snapshots["2026-10-15"].items["it_aaaaaa"].metrics == {}
    assert index.snapshots["2026-10-18"].items["it_cccccc"].section == "论文与研究"
    # why / why_it_matters 不是跨期计算的必需字段，但也不能让解析崩掉
    assert "it_bbbbbb" in index.snapshots["2026-10-17"].items


def test_load_skips_unusable_items(tmp_path: Path) -> None:
    _day(
        tmp_path,
        "2026-10-20",
        [
            {"id": "it_nourl", "source": "hackernews"},  # 无标题无 URL
            {"id": "it_bool", "title": "bool hot", "hot_score": True, "url": "u"},
            {
                "id": "it_ok",
                "title": "ok",
                "url": "u2",
                "hot_score": 5,
                "metrics": {"points": 3, "bad": "x", "flag": True},
            },
        ],
    )
    index = load_cross_period(tmp_path)
    snap = index.snapshots["2026-10-20"]
    assert set(snap.items) == {"it_bool", "it_ok"}
    assert snap.items["it_bool"].hot_score == 0.0  # bool 不算数值
    assert snap.items["it_ok"].metrics == {"points": 3.0}


def test_load_missing_dir_returns_empty() -> None:
    index = load_cross_period("/nonexistent/reports")
    assert index.days == ()
    assert index.latest() is None


def test_same_day_keeps_richer_snapshot(tmp_path: Path) -> None:
    day_dir = _day(tmp_path, "2026-10-20", [_item("it_a", "a", 1.0)])
    payload = {
        "date": "2026-10-20",
        "items": {
            "it_a": _item("it_a", "a", 1.0),
            "it_b": _item("it_b", "b", 2.0),
        },
        "sections": [],
        "comments": [],
        "underrated": [],
    }
    (day_dir / "daily.json").write_text(json.dumps(payload), encoding="utf-8")
    index = load_cross_period(tmp_path)
    assert len(index.snapshots["2026-10-20"].items) == 2


# ── ① 热度迁移 ─────────────────────────────────────────────────────────────


def test_heat_migration_reports_delta_pp(tmp_path: Path) -> None:
    _day(
        tmp_path,
        "2026-10-20",
        [_item("it_a", "a", 75.0), _item("it_b", "b", 25.0)],
        sections=[_section("开源项目", ["it_a"]), _section("论文与研究", ["it_b"])],
    )
    _day(
        tmp_path,
        "2026-10-21",
        [_item("it_a", "a", 25.0), _item("it_b", "b", 75.0)],
        sections=[_section("开源项目", ["it_a"]), _section("论文与研究", ["it_b"])],
    )
    report = heat_migration(load_cross_period(tmp_path), homogeneous=False)
    assert report.status == STATUS_OK
    assert report.entry_count == 2
    by_section = {e["section"]: e for e in report.entries}
    assert by_section["开源项目"]["delta_pp"] == pytest.approx(-50.0)
    assert by_section["论文与研究"]["delta_pp"] == pytest.approx(50.0)
    assert by_section["开源项目"]["t0_top_items"][0]["item_id"] == "it_a"


# ── ② 共动 ─────────────────────────────────────────────────────────────────


def test_co_movement_uses_trajectory_correlation(tmp_path: Path) -> None:
    """同向轨迹成组；反向轨迹不成组；板块与来源重复时只留板块。"""
    series = {"it_a": [10.0, 20.0, 30.0], "it_b": [11.0, 21.0, 31.0], "it_c": [30.0, 20.0, 10.0]}
    for pos, day in enumerate(("2026-10-19", "2026-10-20", "2026-10-21")):
        _day(
            tmp_path,
            day,
            [_item(iid, iid, values[pos], source="hackernews") for iid, values in series.items()],
            sections=[_section("开源项目", list(series))],
        )
    report = co_movement(load_cross_period(tmp_path))
    assert report.entry_count == 1
    entry = report.entries[0]
    assert entry["scope"] == "section"
    assert {m["item_id"] for m in entry["members"]} == {"it_a", "it_b"}
    assert entry["mean_correlation"] == pytest.approx(1.0, abs=0.01)
    assert report.metrics["sample_items"] == 3
    assert report.metrics["comparable_pairs"] == 3


def test_co_movement_insufficient_when_nobody_stays_two_days(tmp_path: Path) -> None:
    """每天全是新条目：没有在榜 ≥2 天的样本，必须明确报"样本不足"而不是 0 条共动。"""
    _day(tmp_path, "2026-10-20", [_item("it_a", "a", 10.0)])
    _day(tmp_path, "2026-10-21", [_item("it_b", "b", 20.0)])
    report = co_movement(load_cross_period(tmp_path))
    assert report.status == STATUS_INSUFFICIENT
    assert report.metrics == {}


def test_co_movement_reports_pairs_even_without_groups(tmp_path: Path) -> None:
    """三条完全无关的轨迹：0 组，但可算配对数必须 >0（否则没法区分"没共动"和"没样本"）。"""
    series = {"it_a": [10.0, 30.0, 10.0], "it_b": [10.0, 10.0, 30.0], "it_c": [30.0, 10.0, 20.0]}
    for pos, day in enumerate(("2026-10-19", "2026-10-20", "2026-10-21")):
        _day(
            tmp_path,
            day,
            [_item(iid, iid, values[pos]) for iid, values in series.items()],
            sections=[_section("s", list(series))],
        )
    report = co_movement(load_cross_period(tmp_path))
    assert report.status == STATUS_OK
    assert report.entry_count == 0
    assert report.metrics["comparable_pairs"] == 3


# ── ③ 背离 ─────────────────────────────────────────────────────────────────


def test_divergence_detects_opposite_direction(tmp_path: Path) -> None:
    _day(
        tmp_path,
        "2026-10-20",
        [_item("it_a", "a", 40.0, metrics={"points": 100})],
    )
    _day(
        tmp_path,
        "2026-10-21",
        [_item("it_a", "a", 60.0, metrics={"points": 50})],
    )
    report = divergence(load_cross_period(tmp_path))
    assert report.status == STATUS_OK
    assert report.entry_count == 1
    entry = report.entries[0]
    assert entry["metric"] == "points"
    assert entry["relation"] == "hot_up_metric_down"
    assert entry["t0_hot"] == 40.0 and entry["t1_hot"] == 60.0
    assert entry["t0_metric"] == 100.0 and entry["t1_metric"] == 50.0


def test_divergence_insufficient_without_metrics(tmp_path: Path) -> None:
    _day(tmp_path, "2026-10-15", [_item("it_a", "a", 10.0)])
    _day(tmp_path, "2026-10-16", [_item("it_a", "a", 20.0)])
    report = divergence(load_cross_period(tmp_path))
    assert report.status == STATUS_INSUFFICIENT
    assert report.required_days == 2
    assert "metrics" in report.missing[0]


# ── ④ 替代对 ───────────────────────────────────────────────────────────────


def test_substitution_matches_similar_titles(tmp_path: Path) -> None:
    _day(
        tmp_path,
        "2026-10-20",
        [_item("it_old", "Open source agent framework released", 80.0, summary="agent framework")],
        sections=[_section("开源项目", ["it_old"])],
    )
    _day(
        tmp_path,
        "2026-10-21",
        [
            _item(
                "it_new", "Open source agent framework released v2", 70.0, summary="agent framework"
            )
        ],
        sections=[_section("开源项目", ["it_new"])],
    )
    report = substitution(load_cross_period(tmp_path), similarity_threshold=0.5)
    assert report.status == STATUS_OK
    assert report.entry_count == 1
    entry = report.entries[0]
    assert entry["t0_item_id"] == "it_old"
    assert entry["t1_item_id"] == "it_new"
    assert entry["similarity"] >= 0.5
    assert entry["section"] == "开源项目"


def test_substitution_reports_max_similarity_when_no_match(tmp_path: Path) -> None:
    _day(
        tmp_path,
        "2026-10-20",
        [_item("it_old", "completely unrelated topic", 80.0)],
        sections=[_section("开源项目", ["it_old"])],
    )
    _day(
        tmp_path,
        "2026-10-21",
        [_item("it_new", "another totally different subject", 70.0)],
        sections=[_section("开源项目", ["it_new"])],
    )
    report = substitution(load_cross_period(tmp_path))
    assert report.status == STATUS_OK
    assert report.entry_count == 0
    # 0 条必须能区分「没有替代」和「阈值不合适」
    assert "max_similarity" in report.metrics


# ── ⑤ 在榜轨迹四类 ─────────────────────────────────────────────────────────


def test_emergence_classifies_four_kinds_from_tracks(tmp_path: Path) -> None:
    """四天窗口构造四类 + 两类非事件，验证分类互斥且计数正确。

    - it_drop：10-19、10-20 连续在榜，10-21 不在 → 跌出
    - it_new：只在 10-21 → 真新
    - it_back：10-18 在、10-19 断、10-20~21 回 → 重回
    - it_wave：10-18 在、10-19 断、10-20 在、10-21 断 → 波动（断过又离开）
    - it_stay：四天都在 → 持续在榜（非事件）
    - it_flash：只在 10-18 → 单日闪现（非事件）
    """
    days = ("2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21")
    presence = {
        "it_drop": ("2026-10-19", "2026-10-20"),
        "it_new": ("2026-10-21",),
        "it_back": ("2026-10-18", "2026-10-20", "2026-10-21"),
        "it_wave": ("2026-10-18", "2026-10-20"),
        "it_stay": days,
        "it_flash": ("2026-10-18",),
    }
    for day in days:
        present = [iid for iid, pdays in presence.items() if day in pdays]
        _day(tmp_path, day, [_item(iid, iid, 50.0) for iid in present])

    report = emergence(load_cross_period(tmp_path))
    kinds = {e["item_id"]: e["kind"] for e in report.entries}
    assert kinds["it_drop"] == "dropped"
    assert kinds["it_new"] == "new"
    assert kinds["it_back"] == "returned"
    assert kinds["it_wave"] == "fluctuating"
    assert "it_stay" not in kinds  # 持续在榜不算事件
    assert "it_flash" not in kinds  # 单日闪现不算事件
    assert report.metrics["dropped"] == 1
    assert report.metrics["new"] == 1
    assert report.metrics["returned"] == 1
    assert report.metrics["fluctuating"] == 1
    assert report.metrics["persistent"] == 1
    assert report.metrics["single_day_flash"] == 1
    assert report.entry_count == 4


def test_emergence_dropped_is_not_called_vanish(tmp_path: Path) -> None:
    """跌出必须带 dropped_on 且措辞是 Top30，条目本身仍可被追溯。"""
    _day(tmp_path, "2026-10-19", [_item("it_a", "a", 80.0)])
    _day(tmp_path, "2026-10-20", [_item("it_a", "a", 70.0)])
    _day(tmp_path, "2026-10-21", [_item("it_b", "b", 10.0)])
    report = emergence(load_cross_period(tmp_path))
    dropped = next(e for e in report.entries if e["kind"] == "dropped")
    assert dropped["item_id"] == "it_a"
    assert dropped["dropped_on"] == "2026-10-21"
    assert dropped["longest_run"] == 2
    assert "Top30" in report.notes


# ── ⑥ 持续性 ───────────────────────────────────────────────────────────────


def test_persistence_buckets_from_tracks(tmp_path: Path) -> None:
    """按最长连续在榜天数分桶；不再读 streak_days。"""
    days = ("2026-10-19", "2026-10-20", "2026-10-21")
    presence = {
        "it_three": days,
        "it_two": days[:2],
        "it_one": (days[1],),
    }
    for day in days:
        present = [iid for iid, pdays in presence.items() if day in pdays]
        _day(tmp_path, day, [_item(iid, iid, 50.0) for iid in present])

    report = persistence(load_cross_period(tmp_path))
    buckets = {e["bucket"]: e for e in report.entries}
    assert buckets["3-4"]["count"] == 1
    assert buckets["3-4"]["items"][0]["item_id"] == "it_three"
    assert buckets["3-4"]["items"][0]["current_run"] == 3
    assert buckets["1-2"]["count"] == 2
    assert report.metrics["max_longest_run"] == 3
    assert report.required_days == 11  # 窗口 3 天，距 14 天还差 11


def test_persistence_works_without_streak_field(tmp_path: Path) -> None:
    """10-15/10-16 没有 streak_days，轨迹口径必须照常工作。"""
    _day(tmp_path, "2026-10-15", [_item("it_a", "a", 10.0)])
    _day(tmp_path, "2026-10-16", [_item("it_a", "a", 20.0)])
    report = persistence(load_cross_period(tmp_path))
    assert report.status == STATUS_OK
    assert report.metrics["max_longest_run"] == 2


# ── ⑦ 来源份额 ─────────────────────────────────────────────────────────────


def test_source_share_counts_and_hot(tmp_path: Path) -> None:
    _day(
        tmp_path,
        "2026-10-20",
        [_item("it_a", "a", 60.0, source="hackernews"), _item("it_b", "b", 40.0, source="rss")],
    )
    _day(
        tmp_path,
        "2026-10-21",
        [
            _item("it_a", "a", 20.0, source="hackernews"),
            _item("it_b", "b", 20.0, source="rss"),
            _item("it_c", "c", 60.0, source="hf_papers"),
        ],
    )
    report = source_share(load_cross_period(tmp_path), homogeneous=False)
    assert report.entry_count == 3
    by_source = {e["source"]: e for e in report.entries}
    assert by_source["hackernews"]["count_delta_pp"] == pytest.approx(-16.67)
    assert by_source["hf_papers"]["t0_count"] == 0
    assert by_source["hf_papers"]["t1_count"] == 1


# ── ⑧ 预言复盘 ─────────────────────────────────────────────────────────────


def test_prediction_review_insufficient_until_due(tmp_path: Path) -> None:
    pred = PRED_HEADER + (
        "| Foo will ship | product | 0.60 | 30 天 | 2030-01-01 | 判据 | `it_deadbe` |\n"
    )
    _day(tmp_path, "2026-10-21", [_item("it_a", "a", 10.0)], predictions_md=pred)
    report = prediction_review(load_cross_period(tmp_path))
    assert report.status == STATUS_INSUFFICIENT
    assert report.entry_count == 0
    assert report.metrics["total"] == 1
    assert report.metrics["earliest_due"] == "2030-01-01"
    assert report.required_days is not None and report.required_days > 1000


def test_prediction_review_counts_verified(tmp_path: Path) -> None:
    pred = PRED_HEADER + (
        "| Foo will ship | product | 0.60 | 7 天 | 2026-10-20 | 判据 | `it_deadbe` |\n"
    )
    verdicts = VERDICT_HEADER + "| Foo will ship | ✅ 命中 | 0.60 | llm | 系统 | 已发布 |\n"
    _day(
        tmp_path,
        "2026-10-21",
        [_item("it_a", "a", 10.0)],
        predictions_md=pred,
        verdicts_md=verdicts,
    )
    report = prediction_review(load_cross_period(tmp_path))
    assert report.status == STATUS_OK
    assert report.entry_count == 1
    assert report.entries[0]["verdict"] == "hit"
    assert report.entries[0]["evidence_ids"] == ["it_deadbe"]


def test_prediction_review_without_predictions(tmp_path: Path) -> None:
    _day(tmp_path, "2026-10-21", [_item("it_a", "a", 10.0)])
    report = prediction_review(load_cross_period(tmp_path))
    assert report.status == STATUS_INSUFFICIENT


# ── ⑨ 未发生的预期 ─────────────────────────────────────────────────────────


def test_unrealized_matches_underrated_marker(tmp_path: Path) -> None:
    _day(
        tmp_path,
        "2026-10-20",
        [
            _item("it_flat", "Flat Topic", 50.0),
            _item("it_gone", "Gone Topic", 60.0),
            _item("it_moved", "Moved Topic", 40.0),
        ],
        underrated=[
            "Flat Topic——被低估",
            "Gone Topic——被低估",
            "Moved Topic——被低估",
            "Unmatched Title——被低估",
        ],
    )
    _day(
        tmp_path,
        "2026-10-21",
        [_item("it_flat", "Flat Topic", 52.0), _item("it_moved", "Moved Topic", 70.0)],
    )
    report = unrealized(load_cross_period(tmp_path))
    outcomes = {e["item_id"]: e["outcome"] for e in report.entries}
    assert outcomes == {"it_flat": "flat", "it_gone": "vanished"}
    assert report.metrics["unmatched"] == 1


def test_unrealized_insufficient_without_markers(tmp_path: Path) -> None:
    _day(tmp_path, "2026-10-15", [_item("it_a", "a", 10.0)])
    _day(tmp_path, "2026-10-16", [_item("it_a", "a", 20.0)])
    report = unrealized(load_cross_period(tmp_path))
    assert report.status == STATUS_INSUFFICIENT
    assert report.required_days == 3


# ── 汇总与边界 ─────────────────────────────────────────────────────────────


def test_compute_all_returns_nine_reports(tmp_path: Path) -> None:
    _day(tmp_path, "2026-10-20", [_item("it_a", "a", 10.0)])
    _day(tmp_path, "2026-10-21", [_item("it_a", "a", 20.0)])
    reports = compute_all(load_cross_period(tmp_path))
    assert len(reports) == 9
    assert [r.key for r in reports][0] == "heat_migration"
    assert all(r.entry_count == len(r.entries) for r in reports)


def test_single_day_makes_pairwise_structures_insufficient(tmp_path: Path) -> None:
    _day(tmp_path, "2026-10-21", [_item("it_a", "a", 10.0)])
    index = load_cross_period(tmp_path)
    for report in (
        heat_migration(index),
        co_movement(index),
        divergence(index),
        substitution(index),
        emergence(index),
        source_share(index),
        unrealized(index),
    ):
        assert report.status == STATUS_INSUFFICIENT
        # ①⑦ 走同构区间，最少要 3 天；其余结构 2 天
        assert report.required_days is not None and report.required_days >= 2


def test_report_to_dict_is_json_serialisable(tmp_path: Path) -> None:
    _day(tmp_path, "2026-10-20", [_item("it_a", "a", 10.0)])
    _day(tmp_path, "2026-10-21", [_item("it_a", "a", 20.0)])
    payload = [r.to_dict() for r in compute_all(load_cross_period(tmp_path))]
    assert json.loads(json.dumps(payload, ensure_ascii=False))[0]["key"] == "heat_migration"
    assert set(payload[0]) >= {"key", "status", "entry_count", "required_days", "entries"}


# ── 边界与防御分支 ──────────────────────────────────────────────────────────


def test_empty_index_every_structure_degrades(tmp_path: Path) -> None:
    index = load_cross_period(tmp_path)
    assert index.snapshot("2030-01-01") is None
    assert index.days == ()
    assert heat_migration(index).status == STATUS_INSUFFICIENT
    assert persistence(index).status == STATUS_INSUFFICIENT
    assert source_share(index).status == STATUS_INSUFFICIENT
    assert prediction_review(index).status == STATUS_INSUFFICIENT


def test_day_from_path_and_malformed_sections(tmp_path: Path) -> None:
    """daily.json 缺 date 时按路径推断；sections / underrated 不是 list 时降级为空。"""
    target = tmp_path / "2026" / "10" / "22"
    target.mkdir(parents=True)
    payload = {
        "items": {"it_a": {"title": "a", "url": "u", "hot_score": 1.0}},
        "sections": "not-a-list",
        "underrated": "also-not-a-list",
    }
    (target / "daily.json").write_text(json.dumps(payload), encoding="utf-8")
    index = load_cross_period(tmp_path)
    assert index.days == ("2026-10-22",)
    snap = index.snapshots["2026-10-22"]
    assert snap.sections == ()
    assert snap.underrated == ()


def test_section_entries_missing_fields_are_skipped(tmp_path: Path) -> None:
    _day(
        tmp_path,
        "2026-10-22",
        [_item("it_a", "a", 1.0)],
        sections=[
            {"item_ids": ["it_a"]},  # 缺 name
            {"name": "s"},  # 缺 item_ids
            {"name": "t", "item_ids": "x"},  # item_ids 不是 list
        ],
    )
    snap = load_cross_period(tmp_path).snapshots["2026-10-22"]
    assert snap.sections == ()
    assert snap.items["it_a"].section == ""


def test_prediction_table_handles_escaped_pipe_and_bad_confidence(tmp_path: Path) -> None:
    pred = PRED_HEADER + (
        "| A \\| B will ship | product | not-a-number | 30 天 | 2030-01-01 | 判据 | `it_abc123` |\n"
        "| short row |\n"
    )
    _day(tmp_path, "2026-10-21", [_item("it_a", "a", 10.0)], predictions_md=pred)
    index = load_cross_period(tmp_path)
    assert len(index.predictions) == 1
    record = index.predictions[0]
    assert record.statement == "A | B will ship"
    assert record.confidence == 0.0
    assert record.due_date == "2030-01-01"


def test_unreadable_prediction_files_are_skipped(tmp_path: Path) -> None:
    day_dir = _day(tmp_path, "2026-10-21", [_item("it_a", "a", 10.0)])
    (day_dir / "predictions.md").mkdir()
    (day_dir / "verdicts.md").mkdir()
    index = load_cross_period(tmp_path)
    assert index.predictions == ()


def test_heat_migration_zero_totals_and_unknown_t1(tmp_path: Path) -> None:
    _day(
        tmp_path,
        "2026-10-20",
        [_item("it_a", "a", 0.0)],
        sections=[_section("s", ["it_a"])],
    )
    _day(
        tmp_path,
        "2026-10-21",
        [_item("it_a", "a", 0.0)],
        sections=[_section("s", ["it_a"])],
    )
    index = load_cross_period(tmp_path)
    assert heat_migration(index, t1="1999-01-01").status == STATUS_INSUFFICIENT
    report = heat_migration(index, homogeneous=False)
    assert report.status == STATUS_OK
    assert report.entries[0]["delta_pp"] == 0.0


def test_co_movement_skips_scopeless_and_flat_series(tmp_path: Path) -> None:
    days = ("2026-10-19", "2026-10-20", "2026-10-21")
    for day in days:
        _day(
            tmp_path,
            day,
            [
                _item("it_x", "x", 5.0, source=""),
                _item("it_y", "y", 5.0, source=""),
            ],
            sections=[_section("s", ["it_x", "it_y"])],
        )
    report = co_movement(load_cross_period(tmp_path))
    assert report.status == STATUS_OK
    # 板块有 label 但热度全平 → 相关性无法计算；来源 label 为空 → 直接跳过
    assert report.entry_count == 0
    assert report.metrics["comparable_pairs"] == 0


def test_divergence_skips_unknown_source_and_same_direction(tmp_path: Path) -> None:
    _day(
        tmp_path,
        "2026-10-20",
        [
            _item("it_unknown", "u", 10.0, source="mystery"),
            _item("it_same", "s", 10.0, source="hackernews", metrics={"points": 10}),
        ],
    )
    _day(
        tmp_path,
        "2026-10-21",
        [
            _item("it_unknown", "u", 20.0, source="mystery"),
            _item("it_same", "s", 30.0, source="hackernews", metrics={"points": 30}),
        ],
    )
    report = divergence(load_cross_period(tmp_path))
    assert report.status == STATUS_OK
    assert report.entry_count == 0
    assert report.metrics["skipped_no_metric"] == 1
    assert report.metrics["compared_items"] == 1


def test_substitution_skips_sections_without_both_sides(tmp_path: Path) -> None:
    _day(
        tmp_path,
        "2026-10-20",
        [_item("it_old", "old topic here", 50.0)],
        sections=[_section("s1", ["it_old"])],
    )
    _day(
        tmp_path,
        "2026-10-21",
        [_item("it_new", "new topic here", 60.0)],
        sections=[_section("s2", ["it_new"])],
    )
    report = substitution(load_cross_period(tmp_path))
    assert report.status == STATUS_OK
    assert report.entry_count == 0


def test_substitution_handles_empty_vocabulary(tmp_path: Path) -> None:
    """单字符标题在 TF-IDF 默认分词下词表为空，必须跳过而不是崩。"""
    _day(
        tmp_path,
        "2026-10-20",
        [_item("it_old", "a", 50.0)],
        sections=[_section("s", ["it_old"])],
    )
    _day(
        tmp_path,
        "2026-10-21",
        [_item("it_new", "b", 60.0)],
        sections=[_section("s", ["it_new"])],
    )
    report = substitution(load_cross_period(tmp_path))
    assert report.status == STATUS_OK
    assert report.entry_count == 0


def test_persistence_with_day_but_no_items(tmp_path: Path) -> None:
    _day(tmp_path, "2026-10-21", [])
    report = persistence(load_cross_period(tmp_path))
    assert report.status == STATUS_INSUFFICIENT
    assert "没有解析到任何条目" in report.missing[0]


def test_source_share_with_empty_day(tmp_path: Path) -> None:
    _day(tmp_path, "2026-10-20", [_item("it_a", "a", 10.0)])
    _day(tmp_path, "2026-10-21", [])
    report = source_share(load_cross_period(tmp_path))
    assert report.status == STATUS_INSUFFICIENT


def test_unrealized_containment_fallback_and_unmatched(tmp_path: Path) -> None:
    _day(
        tmp_path,
        "2026-10-20",
        [_item("it_long", "A Very Long Title About Agents", 40.0)],
        underrated=["A Very Long Title——被低估", "Completely Missing——被低估"],
    )
    _day(
        tmp_path,
        "2026-10-21",
        [_item("it_long", "A Very Long Title About Agents", 41.0)],
    )
    report = unrealized(load_cross_period(tmp_path))
    assert report.entry_count == 1
    assert report.entries[0]["item_id"] == "it_long"
    assert report.metrics["unmatched"] == 1


# ── 2a：口径归因与显著性标注 ────────────────────────────────────────────────


def test_co_movement_reports_n_days_and_no_significance_test(tmp_path: Path) -> None:
    series = {"it_a": [10.0, 20.0, 30.0], "it_b": [11.0, 21.0, 31.0]}
    for pos, day in enumerate(("2026-10-19", "2026-10-20", "2026-10-21")):
        _day(
            tmp_path,
            day,
            [_item(iid, iid, values[pos]) for iid, values in series.items()],
            sections=[_section("s", list(series))],
        )
    report = co_movement(load_cross_period(tmp_path))
    group = report.entries[0]
    assert group["has_significance_test"] is False
    assert group["n_days_min"] == 3
    assert group["min_correlation"] == pytest.approx(1.0, abs=0.01)
    assert group["edges"][0]["n_days"] == 3
    assert report.metrics["has_significance_test"] is False


def test_co_movement_counts_weak_pairs_without_dropping_group(tmp_path: Path) -> None:
    """三条轨迹：a/b 强相关，c 与两者中等相关；弱边只计数，不拆组。"""
    series = {
        "it_a": [10.0, 20.0, 40.0, 80.0],
        "it_b": [11.0, 21.0, 41.0, 81.0],
        "it_c": [12.0, 19.0, 39.0, 79.0],
    }
    for pos, day in enumerate(("2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21")):
        _day(
            tmp_path,
            day,
            [_item(iid, iid, values[pos]) for iid, values in series.items()],
            sections=[_section("s", list(series))],
        )
    report = co_movement(load_cross_period(tmp_path))
    assert report.entry_count == 1
    group = report.entries[0]
    assert group["size"] == 3
    assert group["min_correlation"] <= group["mean_correlation"]


def test_emergence_flags_section_empty_drops(tmp_path: Path) -> None:
    """板块当天整块渲染 0 条 → 跌出归因 section_empty，不得计入趋势。"""
    _day(
        tmp_path,
        "2026-10-19",
        [_item("it_a", "paper a", 50.0)],
        sections=[_section("论文与研究", ["it_a"])],
    )
    _day(
        tmp_path,
        "2026-10-20",
        [_item("it_a", "paper a", 50.0)],
        sections=[_section("论文与研究", ["it_a"])],
    )
    _day(
        tmp_path,
        "2026-10-21",
        [_item("it_b", "community b", 40.0)],
        sections=[_section("社区舆论", ["it_b"])],
    )
    report = emergence(load_cross_period(tmp_path))
    dropped = next(e for e in report.entries if e["kind"] == "dropped")
    assert dropped["attribution"] == "section_empty"
    assert dropped["trend_eligible"] is False
    assert report.metrics["dropped_section_empty"] == 1


def test_emergence_flags_schema_change_drops(tmp_path: Path) -> None:
    """板块集合变化当天发生的跌出 → section_schema_change。"""
    _day(
        tmp_path,
        "2026-10-19",
        [_item("it_a", "a", 50.0)],
        sections=[_section("A", ["it_a"]), _section("B", [])],
    )
    _day(
        tmp_path,
        "2026-10-20",
        [_item("it_a", "a", 50.0)],
        sections=[_section("A", ["it_a"]), _section("B", [])],
    )
    _day(
        tmp_path,
        "2026-10-21",
        [_item("it_b", "b", 40.0)],
        sections=[_section("A", ["it_b"]), _section("B", []), _section("C", [])],
    )
    report = emergence(load_cross_period(tmp_path))
    dropped = next(e for e in report.entries if e["kind"] == "dropped")
    assert dropped["attribution"] == "section_schema_change"
    assert dropped["trend_eligible"] is False
    assert "2026-10-21" in report.metrics["schema_change_days"]


def test_emergence_marks_single_day_entries_as_not_trend_eligible(tmp_path: Path) -> None:
    _day(tmp_path, "2026-10-20", [_item("it_a", "a", 10.0)])
    _day(tmp_path, "2026-10-21", [_item("it_a", "a", 10.0), _item("it_b", "b", 30.0)])
    report = emergence(load_cross_period(tmp_path))
    new = next(e for e in report.entries if e["kind"] == "new")
    assert new["days_on"] == 1
    assert new["trend_eligible"] is False
    assert "单日" in new["caution"]
    assert report.metrics["single_day_entries"] >= 1


# ── S2.5：坏日归因传播 ──────────────────────────────────────────────────────


def test_track_skips_bad_day_without_splitting_run(tmp_path: Path) -> None:
    """板块中间整块为空的那天，不应把条目切成两段（否则会误判为"波动"）。"""
    _day(
        tmp_path,
        "2026-10-17",
        [_item("it_p", "paper", 50.0)],
        sections=[_section("论文与研究", ["it_p"])],
    )
    _day(
        tmp_path,
        "2026-10-18",
        [_item("it_x", "other", 40.0)],
        sections=[_section("论文与研究", [])],
    )
    _day(
        tmp_path,
        "2026-10-19",
        [_item("it_p", "paper", 55.0)],
        sections=[_section("论文与研究", ["it_p"])],
    )
    index = load_cross_period(tmp_path)
    track = build_tracks(index)["it_p"]
    assert track.runs == (2,)
    assert track.masked_days == ("2026-10-18",)
    assert [p.masked for p in track.points] == [False, True, False]


def test_heat_migration_excludes_bad_day_and_marks_taint(tmp_path: Path) -> None:
    runs_bad = [{"source": "hf_papers", "status": "degraded", "item_count": 0}]
    runs_ok = [{"source": "hf_papers", "status": "ok", "item_count": 10}]
    for day, count, runs in (
        ("2026-10-17", 1, runs_ok),
        ("2026-10-18", 0, runs_bad),
        ("2026-10-19", 1, runs_ok),
        ("2026-10-20", 1, runs_ok),
    ):
        items = [] if count == 0 else [_item("it_p", "paper", 10.0, source="hf_papers")]
        _day(
            tmp_path,
            day,
            items,
            sections=[_section("论文与研究", ["it_p"] if count else [])],
            source_runs=runs,
        )
    report = heat_migration(load_cross_period(tmp_path))
    entry = report.entries[0]
    assert entry["excluded_days"] == ["2026-10-18"]
    assert entry["slope_days"] == 3
    assert entry["trend_usable"] is False
    assert entry["taint_sources"] == ["hf_papers"]
    assert report.metrics["tainted_sections"] == ["论文与研究"]


def test_source_share_flags_collection_failure(tmp_path: Path) -> None:
    _day(
        tmp_path,
        "2026-10-20",
        [_item("it_a", "a", 10.0, source="arxiv")],
        source_runs=[{"source": "arxiv", "status": "ok", "item_count": 5}],
    )
    _day(
        tmp_path,
        "2026-10-21",
        [_item("it_b", "b", 10.0, source="arxiv")],
        source_runs=[{"source": "arxiv", "status": "failed", "item_count": 0}],
    )
    report = source_share(load_cross_period(tmp_path), homogeneous=False)
    entry = report.entries[0]
    assert entry["trend_usable"] is False
    assert entry["collection_failure_days"] == ["2026-10-21"]
    assert report.metrics["unusable_sources"] == ["arxiv"]


def test_source_share_degraded_with_items_is_usable(tmp_path: Path) -> None:
    """degraded 但 item_count>0（reddit 25 条）不算采集失败。"""
    _day(
        tmp_path,
        "2026-10-20",
        [_item("it_a", "a", 10.0, source="reddit")],
        source_runs=[{"source": "reddit", "status": "degraded", "item_count": 25}],
    )
    _day(
        tmp_path,
        "2026-10-21",
        [_item("it_a", "a", 12.0, source="reddit")],
        source_runs=[{"source": "reddit", "status": "degraded", "item_count": 25}],
    )
    report = source_share(load_cross_period(tmp_path), homogeneous=False)
    assert report.entries[0]["trend_usable"] is True


# ── S2.6：源集合变更 → 同构区间 ────────────────────────────────────────────


def _runs(*sources: str) -> list[dict[str, Any]]:
    return [{"source": s, "status": "ok", "item_count": 5} for s in sources]


def test_source_change_splits_into_homogeneous_segments(tmp_path: Path) -> None:
    """前 2 天 2 个源、后 3 天 3 个源 → 只有后段满足 ≥3 天。"""
    for day, sources in (
        ("2026-10-15", ("github_trending", "hackernews")),
        ("2026-10-16", ("github_trending", "hackernews")),
        ("2026-10-17", ("github_trending", "hackernews", "reddit")),
        ("2026-10-18", ("github_trending", "hackernews", "reddit")),
        ("2026-10-19", ("github_trending", "hackernews", "reddit")),
    ):
        _day(
            tmp_path,
            day,
            [_item("it_a", "a", 10.0, source="github_trending")],
            sections=[_section("开源项目", ["it_a"])],
            source_runs=_runs(*sources),
        )
    index = load_cross_period(tmp_path)
    segments = homogeneous_segments(index, min_days=3)
    assert segments == [("2026-10-17", "2026-10-18", "2026-10-19")]
    assert comparison_segment(index, min_days=3) == segments[0]
    assert source_change_days(index) == {"2026-10-17"}


def test_comparison_segment_is_none_when_all_segments_too_short(tmp_path: Path) -> None:
    """两个 2 天段：都 <3 天 → 不作趋势判断。"""
    for day, sources in (
        ("2026-10-15", ("a",)),
        ("2026-10-16", ("a",)),
        ("2026-10-17", ("a", "b")),
        ("2026-10-18", ("a", "b")),
    ):
        _day(
            tmp_path,
            day,
            [_item("it_a", "a", 10.0, source="a")],
            sections=[_section("开源项目", ["it_a"])],
            source_runs=_runs(*sources),
        )
    index = load_cross_period(tmp_path)
    assert comparison_segment(index, min_days=3) is None
    assert heat_migration(index).status == STATUS_INSUFFICIENT
    assert heat_migration(index).required_days == 3


def test_heat_migration_defaults_to_homogeneous_segment(tmp_path: Path) -> None:
    """默认只在最后一段同构区间比较：comparison_start 必须晚于源变更日。"""
    for day, sources in (
        ("2026-10-15", ("github_trending", "hackernews")),
        ("2026-10-16", ("github_trending", "hackernews")),
        ("2026-10-17", ("github_trending", "hackernews", "reddit")),
        ("2026-10-18", ("github_trending", "hackernews", "reddit")),
        ("2026-10-19", ("github_trending", "hackernews", "reddit")),
    ):
        _day(
            tmp_path,
            day,
            [_item("it_a", "a", 10.0, source="github_trending")],
            sections=[_section("开源项目", ["it_a"])],
            source_runs=_runs(*sources),
        )
    report = heat_migration(load_cross_period(tmp_path))
    assert report.status == STATUS_OK
    assert report.metrics["comparison_start"] == "2026-10-17"
    assert report.metrics["comparison_days"] == 3
    assert report.metrics["full_window_days"] == 5
    assert report.metrics["source_change_days"] == ["2026-10-17"]
    assert "跨源集合变更日" in report.notes
