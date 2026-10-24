"""S3 自验证单测（L1-L4）。

全部离线：临时目录造假日报，不碰网络、不碰主库。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aipulse.analysis.cross_period import compute_all, load_cross_period
from aipulse.reasoning.selfcheck import (
    BASELINE_ONLY,
    FAIL,
    INSUFFICIENT,
    NO_DATA,
    PASS,
    WARN,
    admission_rule_for,
    build_admission,
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


def test_l4_survival_rate_is_auxiliary_not_decisive(tmp_path: Path) -> None:
    """★ 条目全跌出不再判 fail：1 天间隔 + 3 条样本 → insufficient。

    结构判断是板块/来源层面的；板块份额上升不代表代表条目必须在榜。
    拿"三条全跌出"证伪"社区舆论在收缩"，是量错了对象。
    """
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

    _day(tmp_path, "2026-10-22", [_item("it_zzz999yyy888", "other", 10.0)])
    second = load_cross_period(tmp_path)
    result = check_l4(sections, second, state_dir=tmp_path / "state")

    assert result.verdict == INSUFFICIENT
    assert result.metrics["recent_survival_rate"] == 0.0  # 观测点保留，不丢
    assert any("辅助指标" in f for f in result.findings)
    # 0/3 没有被当作结论，也没有被丢弃


def test_l4_insufficient_when_interval_too_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """间隔 <7 天 → insufficient（即使样本足够）。"""
    from aipulse.reasoning import selfcheck as sc_mod

    claims = [{"scope": "section", "name": f"板块{i}", "direction": "up"} for i in range(6)]
    monkeypatch.setattr(sc_mod, "_structural_claims", lambda index: claims)
    state = tmp_path / "state"
    state.mkdir()
    (state / "calibration.json").write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "issue": "2026-10-21",
                        "window_end": "2026-10-21",
                        "claimed_ids": [],
                        "claims": [{**c, "direction": "down"} for c in claims],
                        "resolved": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    index = _index(tmp_path / "data", ("2026-10-20", "2026-10-21", "2026-10-22"))
    result = check_l4({}, index, state_dir=state)
    assert result.verdict == INSUFFICIENT
    assert "间隔仅 1 天" in result.summary


def test_l4_fails_when_continuity_low_and_sample_enough(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """间隔 ≥7 天 + 样本 ≥5 + 方向延续率 <50% → 这才是 fail。"""
    from aipulse.reasoning import selfcheck as sc_mod

    claims = [{"scope": "section", "name": f"板块{i}", "direction": "up"} for i in range(6)]
    monkeypatch.setattr(sc_mod, "_structural_claims", lambda index: claims)
    state = tmp_path / "state"
    state.mkdir()
    (state / "calibration.json").write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "issue": "2026-10-21",
                        "window_end": "2026-10-21",
                        "claimed_ids": [],
                        "claims": [{**c, "direction": "down"} for c in claims],
                        "resolved": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    index = _index(tmp_path / "data", ("2026-10-20", "2026-10-21", "2026-10-28"))
    result = check_l4({}, index, state_dir=state)
    assert result.verdict == FAIL
    assert "结构方向延续率 0%" in result.summary


def test_admission_is_normal_when_insufficient(tmp_path: Path) -> None:
    """证据不足时**不得**收紧门槛（避免用噪声定罪）。"""
    first = _index(tmp_path, ("2026-10-20", "2026-10-21"))
    sections = parse_markdown(
        _report_text(
            {"structural_changes": "推测：it_abc123def456 结构变化。", "second_order_effects": ""}
        )
    )
    check_l4(sections, first, state_dir=tmp_path / "state")
    _day(tmp_path, "2026-10-22", [_item("it_zzz999yyy888", "other", 10.0)])
    second = load_cross_period(tmp_path)
    check_l4(sections, second, state_dir=tmp_path / "state")

    admission = build_admission(second, state_dir=tmp_path / "state")
    assert admission["level"] == "normal"
    assert admission_rule_for(admission) == ""


def test_admission_is_strict_after_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """fail → strict（下期只允许 1 条结构判断），并翻成 prompt 约束。"""
    from aipulse.reasoning import selfcheck as sc_mod

    claims = [{"scope": "section", "name": f"板块{i}", "direction": "up"} for i in range(6)]
    monkeypatch.setattr(sc_mod, "_structural_claims", lambda index: claims)
    state = tmp_path / "state"
    state.mkdir()
    (state / "calibration.json").write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "issue": "2026-10-21",
                        "window_end": "2026-10-21",
                        "claimed_ids": [],
                        "claims": [{**c, "direction": "down"} for c in claims],
                        "resolved": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    index = _index(tmp_path / "data", ("2026-10-20", "2026-10-21", "2026-10-28"))
    check_l4({}, index, state_dir=state)

    admission = build_admission(index, state_dir=state)
    assert admission["level"] == "strict"
    assert admission["max_structure_claims"] == 1
    rule = admission_rule_for(admission)
    assert "最多给出 1 条结构判断" in rule


def test_old_calibration_without_claims_is_insufficient(tmp_path: Path) -> None:
    """历史 calibration 只有 claimed_ids 没有 claims → 无法判方向 → insufficient。"""
    state = tmp_path / "state"
    state.mkdir()
    (state / "calibration.json").write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "issue": "2026-10-21",
                        "window_end": "2026-10-21",
                        "claimed_ids": ["it_abc123def456"],
                        "resolved": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    index = _index(tmp_path / "data", ("2026-10-20", "2026-10-21", "2026-10-28"))
    result = check_l4({}, index, state_dir=state)
    assert result.verdict == INSUFFICIENT
    assert "可判样本 0 条" in result.summary


# ── 端到端 ─────────────────────────────────────────────────────────────────


def test_run_selfcheck_returns_four_layers(tmp_path: Path) -> None:
    index = _index(tmp_path)
    report = run_selfcheck(
        _report_text(_full_bodies()), index, state_dir=tmp_path / "state", write_state=False
    )
    assert [layer.layer for layer in report.layers] == ["L1", "L2", "L3", "L4"]
    assert report.to_dict()["layers"][0]["metrics"]["total_chars"] > 0
    assert "自验证" in report.to_markdown()


def test_selfcheck_reads_machine_json(tmp_path: Path) -> None:
    """S5 起 L1-L4 读机器层 weekly.json：sections 与 Markdown 解析结果一致。"""
    from aipulse.reasoning.selfcheck import sections_from_machine

    bodies = _full_bodies()
    payload = {
        "schema_version": 2,
        "segments": [
            {"key": key, "title": title, "body": bodies.get(key, ""), "cited_item_ids": []}
            for key, title, _ in SEGMENTS
        ],
    }
    sections = sections_from_machine(payload)
    assert set(sections) == {key for key, _, _ in SEGMENTS}
    assert sections == parse_markdown(_report_text(bodies))


# ── CLI（S5：读机器层、落盘、写准入）──────────────────────────────────────


def test_selfcheck_cli_reads_machine_json_and_writes_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from aipulse.cli.commands import selfcheck as sc_cli
    from aipulse.cli.main import app as cli_app
    from aipulse.core.config import Settings

    index = _index(tmp_path, ("2026-10-20", "2026-10-21"))
    issue = "2026-10-21"
    issue_dir = tmp_path / "trend" / issue
    issue_dir.mkdir(parents=True)
    bodies = _full_bodies()
    (issue_dir / "weekly.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "segments": [
                    {"key": key, "title": title, "body": bodies.get(key, "")}
                    for key, title, _ in SEGMENTS
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert index.days

    settings = Settings(app={"data_dir": str(tmp_path)}, mode="off")
    monkeypatch.setattr(sc_cli, "load_settings", lambda *a, **k: settings)
    result = CliRunner().invoke(cli_app, ["selfcheck", "--reports-dir", str(tmp_path)])

    assert result.exit_code in (0, 1), result.output
    assert (issue_dir / "selfcheck.md").exists()
    assert (issue_dir / "selfcheck.json").exists()
    assert (issue_dir / "admission.json").exists()


def test_selfcheck_cli_reports_missing_machine_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from aipulse.cli.commands import selfcheck as sc_cli
    from aipulse.cli.main import app as cli_app
    from aipulse.core.config import Settings

    _index(tmp_path, ("2026-10-20", "2026-10-21"))
    settings = Settings(app={"data_dir": str(tmp_path)}, mode="off")
    monkeypatch.setattr(sc_cli, "load_settings", lambda *a, **k: settings)
    result = CliRunner().invoke(cli_app, ["selfcheck", "--reports-dir", str(tmp_path)])
    assert result.exit_code == 2
    assert "先跑" in result.output


# ── L2：跨条目 = 0 降为 warn + 必须显式回答替代/背离（C3）─────────────────


def _structure_only_body(repeats: int = 4) -> str:
    """只产生 structure 类增量（有 id + 板块/份额 + 数字），不产生跨条目关系。"""
    return "it_abc123def456 份额从 0.21 升到 0.35，推测结构集中。" * repeats


def test_l2_cross_item_zero_is_warn_not_pass(tmp_path: Path) -> None:
    index = _index(tmp_path)
    reports = {r.key: r for r in compute_all(index)}
    bodies = {key: _structure_only_body() for key, _, _ in SEGMENTS}
    result = check_l2(parse_markdown(_report_text(bodies)), index, reports)
    assert result.metrics["increments"] >= 3
    assert result.metrics["cross_item_zero"] is True
    assert result.verdict == WARN
    assert any("沉默略过" in f for f in result.findings)


def test_l2_explicit_no_relation_still_warn_but_acknowledged(tmp_path: Path) -> None:
    """明说"无可验证的替代/背离"仍算 warn（不是 pass），但 finding 认可这句。"""
    index = _index(tmp_path)
    reports = {r.key: r for r in compute_all(index)}
    bodies = {key: _structure_only_body() for key, _, _ in SEGMENTS}
    bodies["structural_changes"] = _structure_only_body() + "本期无可验证的替代/背离关系。"
    result = check_l2(parse_markdown(_report_text(bodies)), index, reports)
    assert result.verdict == WARN
    assert result.metrics["explicit_no_relation"] is True
    assert any("已显式说明" in f for f in result.findings)


def test_l2_pass_requires_cross_item(tmp_path: Path) -> None:
    index = _index(tmp_path)
    reports = {r.key: r for r in compute_all(index)}
    bodies = {key: _structure_only_body() for key, _, _ in SEGMENTS}
    bodies["structural_changes"] = (
        _structure_only_body() + "it_abc123def456 与 it_def456abc123 承接关系明显，推测替代成立。"
    )
    result = check_l2(parse_markdown(_report_text(bodies)), index, reports)
    assert result.metrics["kinds"]["cross_item"] >= 1
    assert result.verdict == PASS


def test_structural_changes_prompt_demands_relation_answer() -> None:
    """prompt 层预防：只有「结构变化」一节要求显式回答替代/背离。"""
    from aipulse.llm.prompt import render_prompt

    common = dict(
        segment_title="结构变化",
        segment_goal="写结构",
        window_start="2026-10-17",
        window_end="2026-10-23",
        window_days=7,
        evidence="（无）",
        word_budget="300-600 字",
        admission_rule="",
    )
    structural, _ = render_prompt("trend/weekly", segment_key="structural_changes", **common)
    rising, _ = render_prompt("trend/weekly", segment_key="rising_topics", **common)
    assert "无可验证的替代/背离关系" in structural
    assert "无可验证的替代/背离关系" not in rising


def test_selfcheck_cli_falls_back_to_latest_weekly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """日报每天有、周报按周产：最新一天没有周报时要回退，而不是直接判死。"""
    from typer.testing import CliRunner

    from aipulse.cli.commands import selfcheck as sc_cli
    from aipulse.cli.main import app as cli_app
    from aipulse.core.config import Settings

    _index(tmp_path, ("2026-10-20", "2026-10-21"))
    _day(tmp_path, "2026-10-22", [_item("it_abc123def456", "later", 10.0)])
    issue_dir = tmp_path / "trend" / "2026-10-21"
    issue_dir.mkdir(parents=True)
    bodies = _full_bodies()
    (issue_dir / "weekly.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "segments": [
                    {"key": key, "title": title, "body": bodies.get(key, "")}
                    for key, title, _ in SEGMENTS
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    settings = Settings(app={"data_dir": str(tmp_path)}, mode="off")
    monkeypatch.setattr(sc_cli, "load_settings", lambda *a, **k: settings)

    result = CliRunner().invoke(cli_app, ["selfcheck", "--reports-dir", str(tmp_path)])
    assert result.exit_code in (0, 1), result.output
    assert "回退到 2026-10-21" in result.output
    assert (issue_dir / "selfcheck.json").exists()
