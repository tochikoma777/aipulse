"""M5 S4 debate 单测：纯离线（FakeLLM / 桩 client），不读仓库 data/reports。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from aipulse.analysis.cross_period import CrossPeriodIndex, load_cross_period
from aipulse.core.errors import LLMTruncationError
from aipulse.llm.base import LLMResult
from aipulse.reasoning.debate import (
    EVIDENCE_LIMIT,
    EVIDENCE_LINE_CHARS,
    build_evidence,
    run_debate,
)
from aipulse.schema.debate import Falsification, falsification_violations

# ── 造日报 ────────────────────────────────────────────────────────────────


_SECTION_OF = {0: "论文与研究", 1: "社区舆论", 2: "开源项目", 3: "产业与新闻"}


def _daily(day: str, count: int = 20) -> dict[str, Any]:
    items: dict[str, Any] = {}
    sections: dict[str, list[str]] = {}
    for i in range(count):
        item_id = f"it_{i:016x}"
        section = _SECTION_OF[i % 4]
        items[item_id] = {
            "title": f"开源大模型推理框架第 {i} 版发布，社区热度上升"
            if i < 10
            else f"无关条目 {i}",
            "url": f"https://example.com/{i}",
            "source": "github_trending" if i < 10 else "rss",
            "hot_score": 90.0 - i,
            "summary": "这是一段不应该出现在证据包里的摘要正文" * 3,
        }
        sections.setdefault(section, []).append(item_id)
    return {
        "date": day,
        "items": items,
        "sections": [{"name": k, "item_ids": v} for k, v in sections.items()],
    }


@pytest.fixture()
def index(tmp_path: Path) -> CrossPeriodIndex:
    for offset, day in enumerate(("2026-10-20", "2026-10-21", "2026-10-22")):
        target = tmp_path / "2026" / "10" / day.split("-")[-1]
        target.mkdir(parents=True, exist_ok=True)
        (target / "daily.json").write_text(
            json.dumps(_daily(day, 20 + offset), ensure_ascii=False), encoding="utf-8"
        )
    return load_cross_period(tmp_path)


# ── 证据包 ────────────────────────────────────────────────────────────────


def test_evidence_capped_and_compact(index: CrossPeriodIndex) -> None:
    items = build_evidence(index, "开源大模型推理框架")
    assert len(items) <= EVIDENCE_LIMIT
    for item in items:
        assert len(item.line) <= EVIDENCE_LINE_CHARS
        assert item.item_id.startswith("it_")
        # ★ 绝不回显原文：摘要不得出现在证据行里
        assert "摘要正文" not in item.line


def test_evidence_balances_sections(index: CrossPeriodIndex) -> None:
    """★ 证据包不得被单一板块锁死（S4 首跑 15 条里 14 条是论文，四方被锁进同一框架）。"""
    items = build_evidence(index, "开源大模型推理框架")
    counts: dict[str, int] = {}
    for item in items:
        counts[item.section] = counts.get(item.section, 0) + 1
    assert len(counts) >= 3, counts
    # 4 个板块 × 15 条上限 → 每板块不超过 4~5 条
    assert max(counts.values()) <= 5, counts


def test_evidence_prefers_topic_matches_within_section(index: CrossPeriodIndex) -> None:
    """同板块内议题命中的条目优先。"""
    items = build_evidence(index, "开源大模型推理框架")
    matched = [i for i in items if "开源大模型推理框架" in i.title]
    assert matched, "议题相关条目应当进证据包"


# ── 证伪条件：互斥且穷尽 ──────────────────────────────────────────────────


def test_falsification_rejects_point_value() -> None:
    bad = falsification_violations(
        claim="它还会继续涨",
        observable="2026-10-23 热度是否不低于 82.89",
        if_observed="维持",
        if_not_observed="证伪",
    )
    assert any("点值阈值" in v for v in bad)


def test_falsification_accepts_binary_state() -> None:
    ok = falsification_violations(
        claim="这是一次真实采用而非一次性曝光",
        observable="2026-10-23 该条目是否仍在 Top30",
        if_observed="按真实采用处理，继续跟踪",
        if_not_observed="按一次性曝光处理，从观察名单移除",
    )
    assert ok == []
    f = Falsification(
        claim="这是一次真实采用",
        observable="2026-10-23 该条目是否仍在 Top30",
        if_observed="继续跟踪",
        if_not_observed="移出观察名单",
    )
    assert f.selfcheck() == []
    assert f.ok


def test_falsification_flags_conjunction_of_two_questions() -> None:
    """两个独立问句合取 → 组合状态 4 种而分支 2 个，必然覆盖不全。"""
    out = falsification_violations(
        claim="这是真实采用",
        observable="下一窗口是否出现新的非论文类条目，同时本窗口两条是否仍在榜？",
        if_observed="维持",
        if_not_observed="证伪",
    )
    assert any("两个以上独立问句" in v for v in out)


def test_single_question_with_multiple_objects_is_fine() -> None:
    """『是否同时公开 A、B、C 三项』只是单一问句，仍是二元可判定的。"""
    out = falsification_violations(
        claim="该仓库不构成可集成件",
        observable="该项目是否同时公开许可证、依赖清单与近期维护者响应记录三项？",
        if_observed="按可集成候选重估",
        if_not_observed="维持待评估",
    )
    assert out == []


def test_falsification_flags_identical_branches() -> None:
    out = falsification_violations(
        claim="X",
        observable="2026-10-23 是否仍在 Top30",
        if_observed="同样处理",
        if_not_observed="同样处理",
    )
    assert any("分支结论相同" in v for v in out)


def test_date_is_not_treated_as_threshold() -> None:
    out = falsification_violations(
        claim="X",
        observable="2026-10-23 至 2026-10-25 之间是否出现同板块第二条新进榜",
        if_observed="A",
        if_not_observed="B",
    )
    assert out == []


# ── 编排 ──────────────────────────────────────────────────────────────────


class StubLLM:
    """按 purpose 返回预置 JSON；`raise_for` 可让指定环节抛异常。"""

    def __init__(self, responses: dict[str, str], *, raise_for: tuple[str, ...] = ()) -> None:
        self.responses = responses
        self.raise_for = raise_for
        self.saw_purposes: list[str] = []

    async def chat(
        self,
        messages: list[Any],
        *,
        temperature: float = 0.3,
        max_tokens: int = 2000,
        purpose: str = "general",
        model_tier: str = "fast",
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        self.saw_purposes.append(purpose)
        for needle in self.raise_for:
            if needle in messages[0].content:
                raise LLMTruncationError("截断", prompt_tokens=10, completion_tokens=20)
        return LLMResult(
            content=self.responses.get(purpose, "{}"),
            model="fake/strong",
            prompt_tokens=100,
            completion_tokens=200,
        )


_PERSONA_JSON = json.dumps(
    {
        "persona": "optimist",
        "stance": "这是真实采用",
        "reasoning": (
            "连续三天在榜 it_0000000000000000 与 it_0000000000000001 都在，说明不是单日脉冲。"
        ),
        "cited_item_ids": ["it_0000000000000000", "it_0000000000000001"],
        "falsification": {
            "claim": "这是真实采用",
            "observable": "2026-10-23 该条目是否仍在 Top30",
            "if_observed": "按真实采用继续跟踪",
            "if_not_observed": "按一次性曝光移出名单",
            "target_item_ids": ["it_0000000000000000"],
        },
    },
    ensure_ascii=False,
)

_CROSS_JSON = json.dumps(
    {
        "persona": "optimist",
        "challenges": [
            {
                "target": "怀疑派",
                "point": "用被质疑的指标去验真，等于没验",
                "outcome": "部分让步",
                "cited_item_ids": ["it_0000000000000002"],
            }
        ],
        "concessions": ["承认样本只有三天"],
        "revised_stance": "维持，但降低强度",
        "cited_item_ids": ["it_0000000000000002"],
    },
    ensure_ascii=False,
)

_MODERATOR_JSON = json.dumps(
    {
        "consensus": ["样本只有三天，不足以定论"],
        "key_disagreements": [
            "乐观派认为是真实采用，怀疑派认为只是一次性曝光",
            "工程派看重集成成本，投资派认为窗口期已过",
        ],
        "actionable_conclusions": ["盯 2026-10-23 是否仍在 Top30"],
        "overall_confidence": 0.45,
        "falsifications": [
            {
                "claim": "这是真实采用",
                "observable": "2026-10-23 该条目是否仍在 Top30",
                "if_observed": "维持判断",
                "if_not_observed": "推翻判断",
                "target_item_ids": ["it_0000000000000000"],
            }
        ],
        "cited_item_ids": ["it_0000000000000000"],
    },
    ensure_ascii=False,
)


@pytest.mark.asyncio
async def test_run_debate_happy_path(index: CrossPeriodIndex) -> None:
    client = StubLLM(
        {
            "debate_persona": _PERSONA_JSON,
            "debate_cross": _CROSS_JSON,
            "debate_moderator": _MODERATOR_JSON,
        }
    )
    report = await run_debate(index, client, topic="开源大模型推理框架")
    # 4 persona + 4 cross + 1 moderator
    assert report.llm_calls == 9
    assert len(report.statements) == 4
    assert all(s.valid for s in report.statements)
    assert report.moderator.key_disagreements
    assert report.ok, report.failures
    assert report.cost_cny >= 0
    # 证据包进了报告，且不含摘要正文
    assert len(report.evidence_lines) <= EVIDENCE_LIMIT
    assert all("摘要正文" not in line for line in report.evidence_lines)
    # 预热探测先跑了一次
    assert "debate_probe" in client.saw_purposes


@pytest.mark.asyncio
async def test_empty_disagreements_is_failure(index: CrossPeriodIndex) -> None:
    bland = json.dumps(
        {
            "consensus": ["大家都同意数据还不够"],
            "key_disagreements": [],
            "actionable_conclusions": ["继续观察"],
            "overall_confidence": 0.5,
            "falsifications": [],
        },
        ensure_ascii=False,
    )
    client = StubLLM(
        {
            "debate_persona": _PERSONA_JSON,
            "debate_cross": _CROSS_JSON,
            "debate_moderator": bland,
        }
    )
    report = await run_debate(index, client, topic="开源大模型推理框架")
    assert not report.ok
    assert any("key_disagreements 为空" in f for f in report.failures)


@pytest.mark.asyncio
async def test_persona_without_item_id_is_invalid(index: CrossPeriodIndex) -> None:
    no_cite = json.dumps(
        {
            "persona": "optimist",
            "stance": "会涨",
            "reasoning": "我看好它，因为趋势很好，没有任何具体依据。",
            "cited_item_ids": [],
            "falsification": {},
        },
        ensure_ascii=False,
    )
    client = StubLLM(
        {
            "debate_persona": no_cite,
            "debate_cross": _CROSS_JSON,
            "debate_moderator": _MODERATOR_JSON,
        }
    )
    report = await run_debate(index, client, topic="开源大模型推理框架")
    assert all(not s.valid for s in report.statements)
    assert any("未引用任何证据包内的 item_id" in f for f in report.failures)


@pytest.mark.asyncio
async def test_truncation_does_not_kill_other_personas(index: CrossPeriodIndex) -> None:
    """一个 persona 截断时，其余三方必须照常产出（gather 不得炸整轮）。"""
    client = StubLLM(
        {
            "debate_persona": _PERSONA_JSON,
            "debate_cross": _CROSS_JSON,
            "debate_moderator": _MODERATOR_JSON,
        },
        raise_for=("怀疑派",),
    )
    report = await run_debate(index, client, topic="开源大模型推理框架")
    skeptic = [s for s in report.statements if s.persona == "skeptic"]
    others = [s for s in report.statements if s.persona != "skeptic"]
    assert len(skeptic) == 1
    assert not skeptic[0].valid
    assert "截断" in skeptic[0].invalid_reason
    assert others and all(s.valid for s in others)
    assert report.truncated
    # 截断的 token 也要记账，不能漏
    assert report.prompt_tokens > 0


@pytest.mark.asyncio
async def test_bad_falsification_is_reported(index: CrossPeriodIndex) -> None:
    with_threshold = json.dumps(
        {
            "persona": "optimist",
            "stance": "会涨",
            "reasoning": "it_0000000000000000 值得看好",
            "cited_item_ids": ["it_0000000000000000"],
            "falsification": {
                "claim": "会涨",
                "observable": "热度是否不低于 82.89",
                "if_observed": "维持",
                "if_not_observed": "证伪",
            },
        },
        ensure_ascii=False,
    )
    client = StubLLM(
        {
            "debate_persona": with_threshold,
            "debate_cross": _CROSS_JSON,
            "debate_moderator": _MODERATOR_JSON,
        }
    )
    report = await run_debate(index, client, topic="开源大模型推理框架")
    # 不合格只标记、不判整场失败（可用证伪仍 >0，因为主持人那几条是好的）
    assert all(s.falsification.violations for s in report.statements)
    assert report.falsification_usable < report.falsification_total
    assert report.falsification_usable > 0
    assert "可用证伪" not in " ".join(report.failures)
    assert report.ok, report.failures
    assert "不可用" in report.to_markdown()


@pytest.mark.asyncio
async def test_zero_usable_falsification_is_failure(index: CrossPeriodIndex) -> None:
    """可用证伪为 0 = 真的没有可判定结论 → 这才判失败。"""
    all_bad = json.dumps(
        {
            "consensus": ["a"],
            "key_disagreements": ["b", "c"],
            "actionable_conclusions": ["d"],
            "overall_confidence": 0.3,
            "falsifications": [
                {
                    "claim": "X",
                    "observable": "热度是否不低于 82.89",
                    "if_observed": "维持",
                    "if_not_observed": "证伪",
                }
            ],
        },
        ensure_ascii=False,
    )
    client = StubLLM(
        {
            "debate_persona": json.dumps(
                {
                    "persona": "optimist",
                    "stance": "s",
                    "reasoning": "it_0000000000000000",
                    "cited_item_ids": ["it_0000000000000000"],
                    "falsification": {
                        "claim": "X",
                        "observable": "热度是否不低于 82.89",
                        "if_observed": "维持",
                        "if_not_observed": "证伪",
                    },
                },
                ensure_ascii=False,
            ),
            "debate_cross": _CROSS_JSON,
            "debate_moderator": all_bad,
        }
    )
    report = await run_debate(index, client, topic="开源大模型推理框架")
    assert report.falsification_usable == 0
    assert not report.ok
    assert any("可用证伪条件为 0" in f for f in report.failures)


def test_to_markdown_contains_five_outputs() -> None:
    from aipulse.schema.debate import DebateReport, ModeratorOutput

    report = DebateReport(
        topic="X",
        moderator=ModeratorOutput(
            consensus=["a"],
            key_disagreements=["b"],
            actionable_conclusions=["c"],
            overall_confidence=0.4,
        ),
    )
    md = report.to_markdown()
    for needle in ("已达成共识", "关键分歧", "可执行结论", "整体置信度", "什么证据会让我改变判断"):
        assert needle in md


# ── CLI ────────────────────────────────────────────────────────────────────


def _seed_reports(root: Path) -> Path:
    reports = root / "reports"
    for day in ("2026-10-21", "2026-10-22"):
        target = reports.joinpath(*day.split("-"))
        target.mkdir(parents=True, exist_ok=True)
        (target / "daily.json").write_text(
            json.dumps(_daily(day), ensure_ascii=False), encoding="utf-8"
        )
    return reports


def test_debate_cli_writes_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from aipulse.cli.commands import debate as debate_cmd
    from aipulse.cli.main import app as cli_app
    from aipulse.core.config import Settings

    root = tmp_path / "root"
    reports = _seed_reports(root)
    settings = Settings(
        app={"data_dir": str(root)},
        mode="hybrid",
        llm={"api_key": "sk-test-key"},
    )
    monkeypatch.setattr(debate_cmd, "load_settings", lambda *a, **k: settings)
    monkeypatch.setattr(
        debate_cmd,
        "build_client",
        lambda *a, **k: StubLLM(
            {
                "debate_persona": _PERSONA_JSON,
                "debate_cross": _CROSS_JSON,
                "debate_moderator": _MODERATOR_JSON,
            }
        ),
    )

    result = CliRunner().invoke(
        cli_app, ["debate", "--topic", "Agent 议题", "--reports-dir", str(reports)]
    )
    assert result.exit_code == 0, result.output
    # 产物按窗口末日分目录（不再用固定名覆盖，跨期历史才留得住）
    written = root / "reports" / "debate" / "2026-10-22" / "debate-Agent-议题.md"
    assert written.exists()
    assert written.with_suffix(".json").exists()
    assert "关键分歧" in written.read_text(encoding="utf-8")


def test_debate_cli_requires_topic_when_auto_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """weekly_debate_enabled=false → 不给 --topic 直接报错，并指出开关。"""
    from typer.testing import CliRunner

    from aipulse.cli.commands import debate as debate_cmd
    from aipulse.cli.main import app as cli_app
    from aipulse.core.config import Settings

    reports = _seed_reports(tmp_path / "root")
    settings = Settings(
        app={"data_dir": str(tmp_path / "root")},
        mode="hybrid",
        llm={"api_key": "sk-test-key"},
        pipeline={"weekly_debate_enabled": False},
    )
    monkeypatch.setattr(debate_cmd, "load_settings", lambda *a, **k: settings)
    result = CliRunner().invoke(cli_app, ["debate", "--reports-dir", str(reports)])
    assert result.exit_code == 2
    assert "必须给 --topic" in result.output
    assert "weekly_debate_enabled" in result.output


def _write_trend(reports: Path, issue: str, cited_id: str) -> None:
    target = reports / "trend" / issue
    target.mkdir(parents=True, exist_ok=True)
    (target / "weekly.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "window": {"start": "2026-10-16", "end": issue, "days": 7},
                "judgements": [
                    {
                        "key": "structural_changes",
                        "title": "结构变化",
                        "claim": "开源项目份额上升，社区舆论收缩",
                        "cited_item_ids": [cited_id],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (target / "watchlist.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "issue": issue,
                        "item_id": cited_id,
                        "check_on": issue,
                        "expectation": "下期是否仍在榜",
                        "status": "dropped",
                        "resolved_on": issue,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_pick_auto_topic_scores_and_explains(index: CrossPeriodIndex, tmp_path: Path) -> None:
    """选题依据必须可复核：每条加分都要能在原因里看到。"""
    from aipulse.reasoning.auto_topic import pick_auto_topic

    _write_trend(tmp_path, "2026-10-22", "it_0000000000000000")
    picked = pick_auto_topic(index, tmp_path)
    assert picked is not None
    assert picked.section == "论文与研究"
    assert picked.source == "trend/2026-10-22"
    assert "真实迁移还是单日脉冲" in picked.topic
    assert any("上期周报明确下过判断" in r for r in picked.reasons)
    assert any("dropped" in r for r in picked.reasons)
    assert picked.score >= 4
    announcement = picked.announcement()
    assert announcement.startswith("已自动选题：")
    assert "选择依据：" in announcement


def test_pick_auto_topic_returns_none_without_trend(
    index: CrossPeriodIndex, tmp_path: Path
) -> None:
    from aipulse.reasoning.auto_topic import pick_auto_topic

    assert pick_auto_topic(index, tmp_path) is None


def test_debate_cli_auto_topic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """auto 模式：无 --topic 也能跑，且提示选题来源与依据。"""
    from typer.testing import CliRunner

    from aipulse.cli.commands import debate as debate_cmd
    from aipulse.cli.main import app as cli_app
    from aipulse.core.config import Settings

    reports = _seed_reports(tmp_path / "root")
    _write_trend(reports, "2026-10-22", "it_0000000000000000")
    settings = Settings(
        app={"data_dir": str(tmp_path / "root")},
        mode="hybrid",
        llm={"api_key": "sk-test-key"},
    )
    monkeypatch.setattr(debate_cmd, "load_settings", lambda *a, **k: settings)
    monkeypatch.setattr(
        debate_cmd,
        "build_client",
        lambda *a, **k: StubLLM(
            {
                "debate_persona": _PERSONA_JSON,
                "debate_cross": _CROSS_JSON,
                "debate_moderator": _MODERATOR_JSON,
            }
        ),
    )

    result = CliRunner().invoke(cli_app, ["debate", "--reports-dir", str(reports)])
    assert result.exit_code == 0, result.output
    assert "已自动选题" in result.output
    assert "来源：trend/2026-10-22" in result.output
    assert "选择依据" in result.output
    written = list((reports / "debate").glob("*/debate-*.md"))
    assert len(written) == 1
    assert "论文与研究" in written[0].name


def test_debate_cli_auto_topic_without_trend_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """开关开着但没有 trend 产物 → 明确告诉用户先跑 trend，而不是静默选一个空话题。"""
    from typer.testing import CliRunner

    from aipulse.cli.commands import debate as debate_cmd
    from aipulse.cli.main import app as cli_app
    from aipulse.core.config import Settings

    reports = _seed_reports(tmp_path / "root")
    settings = Settings(
        app={"data_dir": str(tmp_path / "root")},
        mode="hybrid",
        llm={"api_key": "sk-test-key"},
    )
    monkeypatch.setattr(debate_cmd, "load_settings", lambda *a, **k: settings)
    result = CliRunner().invoke(cli_app, ["debate", "--reports-dir", str(reports)])
    assert result.exit_code == 2
    assert "自动选题失败" in result.output
    assert "aipulse trend" in result.output


def test_pick_auto_topic_maps_dropped_item_from_earlier_day(tmp_path: Path) -> None:
    """掉出榜单的条目不在最新快照里，仍要靠历史快照找回它的板块。"""
    from aipulse.reasoning.auto_topic import pick_auto_topic

    reports = tmp_path / "reports"
    day1 = _daily("2026-10-21", 20)
    day2 = _daily("2026-10-22", 20)
    dropped_id = f"it_{19:016x}"  # 只出现在 day1
    day2["items"].pop(dropped_id)
    day2["sections"] = [
        {"name": s["name"], "item_ids": [i for i in s["item_ids"] if i != dropped_id]}
        for s in day2["sections"]
    ]
    for day, payload in (("2026-10-21", day1), ("2026-10-22", day2)):
        target = reports.joinpath(*day.split("-"))
        target.mkdir(parents=True, exist_ok=True)
        (target / "daily.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    index = load_cross_period(reports)

    _write_trend(reports, "2026-10-22", dropped_id)
    picked = pick_auto_topic(index, reports)
    assert picked is not None
    assert picked.section == "产业与新闻"  # 19 % 4 = 3
    assert any("dropped" in r for r in picked.reasons)


def test_debate_cli_fails_when_key_disagreements_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """空共识/无分歧 = 失败（退出码 1），不是"跑完了"。"""
    from aipulse.cli.commands import debate as debate_cmd
    from aipulse.cli.main import app as cli_app
    from aipulse.core.config import Settings

    reports = _seed_reports(tmp_path / "root")
    settings = Settings(
        app={"data_dir": str(tmp_path / "root")},
        mode="hybrid",
        llm={"api_key": "sk-test-key"},
    )
    empty_moderator = json.dumps(
        {
            "consensus": ["四方都同意"],
            "key_disagreements": [],
            "actionable_conclusions": [],
            "overall_confidence": 0.9,
            "falsifications": [],
            "cited_item_ids": ["it_0000000000000000"],
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(debate_cmd, "load_settings", lambda *a, **k: settings)
    monkeypatch.setattr(
        debate_cmd,
        "build_client",
        lambda *a, **k: StubLLM(
            {
                "debate_persona": _PERSONA_JSON,
                "debate_cross": _CROSS_JSON,
                "debate_moderator": empty_moderator,
            }
        ),
    )

    result = CliRunner().invoke(
        cli_app, ["debate", "--topic", "Agent 议题", "--json", "--reports-dir", str(reports)]
    )
    assert result.exit_code == 1, result.output
    assert "⛔" in result.output
    assert "key_disagreements 为空" in result.output


def test_debate_cli_missing_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from aipulse.cli.commands import debate as debate_cmd
    from aipulse.cli.main import app as cli_app
    from aipulse.core.config import Settings

    settings = Settings(app={"data_dir": str(tmp_path)}, mode="hybrid", llm={"api_key": "sk-x"})
    monkeypatch.setattr(debate_cmd, "load_settings", lambda *a, **k: settings)
    result = CliRunner().invoke(
        cli_app, ["debate", "--topic", "x", "--reports-dir", str(tmp_path / "none")]
    )
    assert result.exit_code == 2
    assert "没有找到任何日报" in result.output
