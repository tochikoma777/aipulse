"""S3 自验证单测（L1-L4）。

全部离线：临时目录造假日报，不碰网络、不碰主库。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aipulse.analysis.cross_period import compute_all, load_cross_period
from aipulse.reasoning.selfcheck import (
    BASELINE_ONLY,
    FAIL,
    NO_DATA,
    PASS,
    check_l1,
    check_l2,
    check_l3,
    check_l4,
    parse_markdown,
    run_selfcheck,
)
from aipulse.reasoning.trend import SEGMENTS
from tests.unit.test_cross_period import _day, _item, _section

# ── 构造工具 ───────────────────────────────────────────────────────────────


def _report_text(bodies: dict[str, str]) -> str:
    lines = [
        "# AI 脉搏 · 周度趋势（取数 2026-10-16 → 2026-10-22，7 天）",
        "",
        "> 比较区间 2026-10-17 → 2026-10-22（6 天，源集合同构）。",
        "",
    ]
    for pos, (key, title, _) in enumerate(SEGMENTS, 1):
        lines.extend([f"## {pos}. {title}", "", bodies.get(key, ""), ""])
    return "\n".join(lines)


_BASE_CLAUSE = (
    "it_abc123def456 所在板块份额 0.3019→0.3538（+5.19pp），斜率 +0.19pp/天，"
    "意味着区间内份额抬升而动能趋缓。"
)


def _long_body(repeats: int = 7) -> str:
    return _BASE_CLAUSE * repeats


def _full_bodies() -> dict[str, str]:
    bodies = {key: _long_body() for key, _, _ in SEGMENTS}
    bodies["emerging_topics"] = _long_body(5)  # 该节上限 400 字
    bodies["structural_changes"] = _long_body(6) + "推测：份额抬升来自条目集中。"
    bodies["second_order_effects"] = _long_body(6) + "推测：下一步看份额能否延续。"
    bodies["prediction_review"] = "本周无到期预言，最早到期 2026-11-16。"
    return bodies


def _index(root: Path, days: tuple[str, ...] = ("2026-10-20", "2026-10-21")) -> Any:
    for pos, day in enumerate(days):
        _day(
            root,
            day,
            [
                _item("it_abc123def456", "alpha topic", 80.0 + pos, source="hackernews"),
                _item("it_def456abc123", "beta topic", 60.0 + pos, source="github_trending"),
            ],
            sections=[
                _section("开源项目", ["it_abc123def456"]),
                _section("社区舆论", ["it_def456abc123"]),
            ],
        )
    return load_cross_period(root)


# ── 解析 ───────────────────────────────────────────────────────────────────


def test_parse_markdown_maps_by_title_and_ignores_unknown() -> None:
    text = _report_text(_full_bodies()) + "\n## L1 硬判据 — pass\n\n自检报告不是周报的一节。\n"
    sections = parse_markdown(text)
    assert set(sections) == {key for key, _, _ in SEGMENTS}
    assert "份额 0.3019" in sections["rising_topics"]


# ── L1 ─────────────────────────────────────────────────────────────────────


def test_l1_passes_on_well_formed_report(tmp_path: Path) -> None:
    index = _index(tmp_path)
    reports = {r.key: r for r in compute_all(index)}
    result = check_l1(parse_markdown(_report_text(_full_bodies())), index, reports)
    assert result.verdict == PASS, result.findings
    assert result.metrics["total_chars"] >= 2000
    assert result.metrics["violations"] == 0


def test_l1_fails_on_missing_section_and_boilerplate(tmp_path: Path) -> None:
    index = _index(tmp_path)
    reports = {r.key: r for r in compute_all(index)}
    bodies = _full_bodies()
    bodies["falling_topics"] = ""
    bodies["rising_topics"] = _BASE_CLAUSE * 7 + "该方向未来可期。"
    result = check_l1(parse_markdown(_report_text(bodies)), index, reports)
    assert result.verdict == FAIL
    assert "falling_topics" in result.metrics["missing_segments"]
    assert any("套话" in f for f in result.findings)


def test_l1_flags_total_out_of_ssot_range(tmp_path: Path) -> None:
    index = _index(tmp_path)
    reports = {r.key: r for r in compute_all(index)}
    bodies = {key: _BASE_CLAUSE for key, _, _ in SEGMENTS}
    result = check_l1(parse_markdown(_report_text(bodies)), index, reports)
    assert result.verdict == FAIL
    assert result.metrics["in_range"] is False


# ── L2 ─────────────────────────────────────────────────────────────────────


def test_l2_counts_cross_item_relations_not_pairwise_numbers(tmp_path: Path) -> None:
    index = _index(tmp_path)
    reports = {r.key: r for r in compute_all(index)}
    bodies = {key: _long_body() for key, _, _ in SEGMENTS}
    bodies["structural_changes"] = (
        "it_abc123def456 与 it_def456abc123 一升一降，意味着开源与社区在争夺榜单位置，"
        "推测由条目供给结构决定。"
    )
    bodies["second_order_effects"] = (
        "it_abc123def456 承接了 from it_def456abc123 的曝光，推测替代关系成立。"
    )
    bodies["watchlist"] = "看 it_abc123def456 能否守住份额。"
    result = check_l2(parse_markdown(_report_text(bodies)), index, reports)
    assert result.metrics["kinds"]["cross_item"] >= 1
    assert result.metrics["increments"] >= 1


def test_l2_fails_when_only_pairwise_restatement(tmp_path: Path) -> None:
    index = _index(tmp_path)
    reports = {r.key: r for r in compute_all(index)}
    pairwise = "it_abc123def456 的 82.89 较 it_def456abc123 的 82.06 高 0.83。" * 3
    bodies = {key: pairwise for key, _, _ in SEGMENTS}
    result = check_l2(parse_markdown(_report_text(bodies)), index, reports)
    assert result.verdict == FAIL
    assert result.metrics["increments"] == 0
    assert result.metrics["pairwise_numeric"] >= 1


# ── L3 ─────────────────────────────────────────────────────────────────────


def test_l3_reports_no_data_and_registers_watchlist(tmp_path: Path) -> None:
    index = _index(tmp_path, ("2026-10-20", "2026-10-21"))
    sections = parse_markdown(
        _report_text({**_full_bodies(), "watchlist": "看 it_abc123def456 能否守住。"})
    )
    result = check_l3(sections, index, state_dir=tmp_path / "state")
    assert result.verdict == NO_DATA
    assert result.metrics["predictions_verified"] == 0
    assert result.metrics["hit_rate"] is None
    assert len(result.metrics["watchlist_created"]) == 1
    created = result.metrics["watchlist_created"][0]
    assert created["check_on"] == "2026-10-22"
    assert (tmp_path / "state" / "watchlist.json").exists()


def test_l3_resolves_watchlist_on_next_issue(tmp_path: Path) -> None:
    first = _index(tmp_path, ("2026-10-20", "2026-10-21"))
    sections = parse_markdown(
        _report_text({"watchlist": "看 it_abc123def456 与 it_def456abc123 能否守住。"})
    )
    check_l3(sections, first, state_dir=tmp_path / "state")

    # 次日：alpha 仍在榜，beta 跌出
    _day(
        tmp_path,
        "2026-10-22",
        [_item("it_abc123def456", "alpha topic", 85.0, source="hackernews")],
        sections=[_section("开源项目", ["it_abc123def456"]), _section("社区舆论", [])],
    )
    second = load_cross_period(tmp_path)
    result = check_l3(sections, second, state_dir=tmp_path / "state")
    assert result.verdict == PASS
    statuses = {e["item_id"]: e["status"] for e in result.metrics["watchlist_resolved"]}
    assert statuses["it_abc123def456"] == "still_on"
    assert statuses["it_def456abc123"] == "dropped"


# ── L4 ─────────────────────────────────────────────────────────────────────


def test_l4_first_issue_only_builds_baseline(tmp_path: Path) -> None:
    index = _index(tmp_path, ("2026-10-20", "2026-10-21"))
    sections = parse_markdown(
        _report_text(
            {
                "structural_changes": "推测：it_abc123def456 所在板块结构变化。",
                "second_order_effects": "",
            }
        )
    )
    result = check_l4(sections, index, state_dir=tmp_path / "state")
    assert result.verdict == BASELINE_ONLY
    assert result.metrics["claimed_ids"] == ["it_abc123def456"]


def test_l4_computes_survival_rate_on_next_issue(tmp_path: Path) -> None:
    first = _index(tmp_path, ("2026-10-20", "2026-10-21"))
    sections = parse_markdown(
        _report_text(
            {
                "structural_changes": "推测：it_abc123def456 与 it_def456abc123 结构变化。",
                "second_order_effects": "",
            }
        )
    )
    check_l4(sections, first, state_dir=tmp_path / "state")

    _day(
        tmp_path,
        "2026-10-22",
        [_item("it_abc123def456", "alpha topic", 85.0)],
        sections=[_section("开源项目", ["it_abc123def456"])],
    )
    second = load_cross_period(tmp_path)
    result = check_l4(sections, second, state_dir=tmp_path / "state")
    assert result.verdict == PASS  # 50% 存活，刚好达阈值
    assert "50%" in result.summary


def test_l4_flags_overclaiming_when_nothing_survives(tmp_path: Path) -> None:
    first = _index(tmp_path, ("2026-10-20", "2026-10-21"))
    sections = parse_markdown(
        _report_text(
            {"structural_changes": "推测：it_abc123def456 结构变化。", "second_order_effects": ""}
        )
    )
    check_l4(sections, first, state_dir=tmp_path / "state")

    _day(tmp_path, "2026-10-22", [_item("it_zzz999yyy888", "other", 10.0)])
    second = load_cross_period(tmp_path)
    result = check_l4(sections, second, state_dir=tmp_path / "state")
    assert result.verdict == FAIL
    assert any("提高准入门槛" in f for f in result.findings)


# ── 端到端 ─────────────────────────────────────────────────────────────────


def test_run_selfcheck_returns_four_layers(tmp_path: Path) -> None:
    index = _index(tmp_path)
    report = run_selfcheck(
        _report_text(_full_bodies()), index, state_dir=tmp_path / "state", write_state=False
    )
    assert [layer.layer for layer in report.layers] == ["L1", "L2", "L3", "L4"]
    assert report.to_dict()["layers"][0]["metrics"]["total_chars"] > 0
    assert "自验证" in report.to_markdown()
