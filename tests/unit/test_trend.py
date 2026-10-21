"""trend 分段生成单测（M5 S2）。

全部用脚本化假客户端，不打网络；真实质量验证靠配 key 实跑（见 S2 报告）。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aipulse.analysis.cross_period import load_cross_period
from aipulse.core.errors import LLMError, LLMTruncationError
from aipulse.llm.base import ChatMessage, LLMResult
from aipulse.reasoning.trend import (
    SEGMENTS,
    boilerplate_hits,
    build_evidence,
    char_count,
    generate_trend,
    slice_index,
    violations,
)
from aipulse.schema.trend import TrendReport, TrendSegment

from .test_cross_period import _day, _item, _section


class _ScriptedClient:
    """按调用顺序返回预置正文；可指定某一次调用抛 LLMError。"""

    def __init__(self, bodies: list[str], *, fail_at: int | None = None) -> None:
        self.bodies = bodies
        self.fail_at = fail_at
        self.calls: list[str] = []
        self.purposes: list[str] = []

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int = 2000,
        purpose: str = "general",
        model_tier: str = "fast",
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        index = len(self.calls)
        self.calls.append(messages[-1].content if messages else "")
        self.purposes.append(purpose)
        if self.fail_at is not None and index == self.fail_at:
            raise LLMError("模拟失败：finish_reason=length")
        return LLMResult(
            content=self.bodies[index % len(self.bodies)],
            model=f"fake/{model_tier}",
            prompt_tokens=100,
            completion_tokens=50,
        )


GOOD_BODY = (
    "论文板块份额从 0.231 升到 0.3495（+11.86pp），代表条目 it_d56bf7f0d55e498a 与 "
    "it_2132166d14a053db 同步上升；这一判断属推测，依据是斜率 +11.86pp/天。"
)


def _index(tmp_path):  # noqa: ANN001
    _day(tmp_path, "2026-10-19", [_item("it_a", "alpha", 10.0)])
    _day(tmp_path, "2026-10-20", [_item("it_a", "alpha", 20.0)])
    _day(tmp_path, "2026-10-21", [_item("it_a", "alpha", 30.0), _item("it_b", "beta", 40.0)])
    return load_cross_period(tmp_path)


@pytest.mark.asyncio
async def test_generate_trend_runs_seven_segments(tmp_path) -> None:  # noqa: ANN001
    index = _index(tmp_path)
    client = _ScriptedClient([GOOD_BODY])
    report = await generate_trend(index, client, window_days=7)

    assert len(report.segments) == 7
    assert [s.key for s in report.segments] == [key for key, _, _ in SEGMENTS]
    assert report.llm_calls == 7
    assert len(client.calls) == 7
    assert set(client.purposes) == {"trend_weekly"}
    assert all(segment.llm_calls == 1 for segment in report.segments)
    assert all(segment.char_count == char_count(GOOD_BODY) for segment in report.segments)
    assert "it_d56bf7f0d55e498a" in report.segments[0].cited_item_ids
    assert report.window_start == "2026-10-19"
    assert report.window_end == "2026-10-21"
    assert report.cost_cny == pytest.approx((100 + 50) * 7 * 4.0 / 1_000_000)


@pytest.mark.asyncio
async def test_segment_failure_is_isolated(tmp_path) -> None:  # noqa: ANN001
    client = _ScriptedClient([GOOD_BODY], fail_at=2)
    report = await generate_trend(_index(tmp_path), client)
    failed = report.segments[2]
    assert failed.skipped_reason.startswith("LLM 调用失败")
    assert report.llm_calls == 6
    assert sum(1 for s in report.segments if s.body) == 6


@pytest.mark.asyncio
async def test_subset_of_segments(tmp_path) -> None:  # noqa: ANN001
    client = _ScriptedClient([GOOD_BODY])
    report = await generate_trend(
        _index(tmp_path), client, segment_keys=("rising_topics", "watchlist")
    )
    assert [s.key for s in report.segments] == ["rising_topics", "watchlist"]


@pytest.mark.asyncio
async def test_each_segment_prompt_is_isolated(tmp_path) -> None:  # noqa: ANN001
    """每段 prompt 必须带自己的节名，而不是同一份上下文复用 7 次。"""
    client = _ScriptedClient([GOOD_BODY])
    await generate_trend(_index(tmp_path), client)
    for (_, title, _), prompt in zip(SEGMENTS, client.calls, strict=True):
        assert title in prompt


def test_char_count_ignores_whitespace() -> None:
    assert char_count("中文 字符\n\n测试") == 6


def test_boilerplate_hits() -> None:
    hits = boilerplate_hits("值得关注的是，这一方向未来可期，或将迎来转折。")
    assert "值得关注" in hits
    assert "未来可期" in hits
    assert "或将" in hits


def test_violations_detect_red_lines() -> None:
    from aipulse.reasoning.trend import Evidence

    body = "这个话题已经消失，值得关注。没有 id。"
    out = violations(body, Evidence(text=""), requires_speculation=True, weak_corr=True)
    assert any("消失" in item for item in out)
    assert any("item_id" in item for item in out)
    assert any("推测" in item for item in out)


def test_violations_flag_restating_titles() -> None:
    from aipulse.reasoning.trend import Evidence

    evidence = Evidence(text="", titles=("一个足够长的标题用于检测复述",))
    body = "一个足够长的标题用于检测复述，说明它在升温 it_abcdef123456。"
    out = violations(body, evidence, requires_speculation=False, weak_corr=False)
    assert any("复述" in item for item in out)


def test_violations_flag_correlation_wording() -> None:
    from aipulse.reasoning.trend import Evidence

    out = violations(
        "这两条存在相关，it_abcdef123456 同步上升。",
        Evidence(text=""),
        requires_speculation=False,
        weak_corr=True,
    )
    assert any("相关" in item for item in out)


def test_evidence_excludes_section_empty_drops(tmp_path) -> None:  # noqa: ANN001
    """10-18 式异常：板块整块为空导致的跌出不得进入趋势证据。"""
    _day(
        tmp_path,
        "2026-10-19",
        [_item("it_paper", "paper", 50.0)],
        sections=[_section("论文与研究", ["it_paper"])],
    )
    _day(
        tmp_path,
        "2026-10-20",
        [_item("it_paper", "paper", 50.0)],
        sections=[_section("论文与研究", ["it_paper"])],
    )
    _day(
        tmp_path,
        "2026-10-21",
        [_item("it_other", "other", 40.0)],
        sections=[_section("社区舆论", ["it_other"])],
    )
    index = load_cross_period(tmp_path)
    from aipulse.analysis.cross_period import compute_all

    reports = {r.key: r for r in compute_all(index)}
    evidence = build_evidence(index, reports, "falling_topics")
    assert "it_paper" not in evidence.text


def test_evidence_marks_single_day_items(tmp_path) -> None:  # noqa: ANN001
    _day(tmp_path, "2026-10-20", [_item("it_a", "alpha", 10.0)])
    _day(tmp_path, "2026-10-21", [_item("it_a", "alpha", 11.0), _item("it_b", "beta", 40.0)])
    index = load_cross_period(tmp_path)
    from aipulse.analysis.cross_period import compute_all

    reports = {r.key: r for r in compute_all(index)}
    evidence = build_evidence(index, reports, "emerging_topics")
    assert "单日，不构成趋势" in evidence.text
    assert "it_b" in evidence.text


def test_slice_index_keeps_last_days(tmp_path) -> None:  # noqa: ANN001
    index = _index(tmp_path)
    sliced = slice_index(index, 2)
    assert sliced.days == index.days[-2:]
    assert set(sliced.snapshots) == set(sliced.days)


def test_markdown_has_seven_numbered_sections() -> None:
    report = TrendReport(
        window_start="2026-10-15",
        window_end="2026-10-21",
        window_days=7,
        segments=[TrendSegment(key=f"s{i}", title=f"节{i}", body="正文") for i in range(7)],
    )
    markdown = report.to_markdown()
    assert markdown.count("## ") == 7
    assert "## 1. 节0" in markdown
    assert "## 7. 节6" in markdown
    assert "周度趋势（2026-10-15 → 2026-10-21，7 天）" in markdown


def test_summary_is_json_serialisable() -> None:
    report = TrendReport(
        segments=[TrendSegment(key="a", title="A", body="x", char_count=1, cited_item_ids=["it_1"])]
    )
    payload = json.loads(json.dumps(report.summary(), ensure_ascii=False))
    assert payload["segments"][0]["cited_item_ids"] == 1


# ── CLI ────────────────────────────────────────────────────────────────────


def _fake_settings(mode: str) -> object:
    from types import SimpleNamespace

    return SimpleNamespace(
        app=SimpleNamespace(log_level="INFO", data_dir="data"),
        budget=SimpleNamespace(price_strong_cny_per_1m=4.0, daily_limit_cny=2.0),
        llm=SimpleNamespace(),
        effective_mode=lambda: SimpleNamespace(value=mode),
    )


def test_cli_refuses_off_mode(monkeypatch) -> None:  # noqa: ANN001
    from typer.testing import CliRunner

    from aipulse.cli.commands import trend as trend_cli

    monkeypatch.setattr(trend_cli, "load_settings", lambda: _fake_settings("off"))
    result = CliRunner().invoke(trend_cli.app, ["--range", "7d"])
    assert result.exit_code == 2
    assert "off 档" in result.output


def test_cli_rejects_bad_range(monkeypatch) -> None:  # noqa: ANN001
    from typer.testing import CliRunner

    from aipulse.cli.commands import trend as trend_cli

    monkeypatch.setattr(trend_cli, "load_settings", lambda: _fake_settings("off"))
    result = CliRunner().invoke(trend_cli.app, ["--range", "week"])
    assert result.exit_code != 0
    assert "--range" in result.output


class _TruncatingClient:
    """每次调用都抛截断异常（模拟 reasoner 思维链吃满 max_tokens）。"""

    def __init__(self) -> None:
        self.attempts = 0

    async def chat(self, messages, **kwargs: Any) -> LLMResult:  # noqa: ANN001
        self.attempts += 1
        raise LLMTruncationError("被截断", prompt_tokens=100, completion_tokens=200)


@pytest.mark.asyncio
async def test_truncation_is_counted_and_costed(tmp_path) -> None:  # noqa: ANN001
    """截断的调用也要计入 attempts / tokens / 成本，不能因为抛错就漏账。"""
    client = _TruncatingClient()
    report = await generate_trend(_index(tmp_path), client, max_tokens=2000)

    assert report.llm_calls == 0
    assert report.attempts == 7
    assert client.attempts == 7
    assert len(report.truncated_segments) == 7
    assert report.prompt_tokens == 700
    assert report.completion_tokens == 1400
    assert report.cost_cny == pytest.approx((700 + 1400) * 4.0 / 1_000_000)
    assert all("截断" in s.skipped_reason for s in report.segments)
