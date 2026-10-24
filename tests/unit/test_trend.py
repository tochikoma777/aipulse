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
        # 第 8 次调用（三句话）走结构化输出，正文脚本对它没意义
        body = (
            HEADLINES_JSON
            if purpose == "trend_headlines"
            else self.bodies[index % len(self.bodies)]
        )
        return LLMResult(
            content=body,
            model=f"fake/{model_tier}",
            prompt_tokens=100,
            completion_tokens=50,
        )


HEADLINES_JSON = json.dumps(
    {
        "headlines": ["社区舆论份额收缩最明显", "论文板块本周不作判断", "榜单换血依然剧烈"],
        "judgements": [
            {
                "key": "rising_topics",
                "title": "上升主题",
                "claim": "上升集中在开源项目，社区舆论在收缩",
                "cited_item_ids": ["it_d56bf7f0d55e498a"],
            }
        ],
    },
    ensure_ascii=False,
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
    # 7 节 + 第 8 次「三句话」调用
    assert report.llm_calls == 8
    assert len(client.calls) == 8
    assert set(client.purposes) == {"trend_weekly", "trend_headlines"}
    assert len(report.headlines) == 3
    assert report.judgements
    assert all(segment.llm_calls == 1 for segment in report.segments)
    assert all(segment.char_count == char_count(GOOD_BODY) for segment in report.segments)
    assert "it_d56bf7f0d55e498a" in report.segments[0].cited_item_ids
    assert report.window_start == "2026-10-19"
    assert report.window_end == "2026-10-21"
    assert report.cost_cny == pytest.approx((100 + 50) * 8 * 4.0 / 1_000_000)


@pytest.mark.asyncio
async def test_segment_failure_is_isolated(tmp_path) -> None:  # noqa: ANN001
    client = _ScriptedClient([GOOD_BODY], fail_at=2)
    report = await generate_trend(_index(tmp_path), client)
    failed = report.segments[2]
    assert failed.skipped_reason.startswith("LLM 调用失败")
    assert report.llm_calls == 7  # 6 节正文 + 三句话
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
    for (_, title, _), prompt in zip(SEGMENTS, client.calls[:7], strict=True):
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
    assert "周度趋势（取数 2026-10-15 → 2026-10-21，7 天）" in markdown


def test_markdown_marks_comparison_interval_separately() -> None:
    """取数窗口与比较区间不同时必须分别写明，避免读者把 7 天和 5 天混为一谈。"""
    report = TrendReport(
        window_start="2026-10-16",
        window_end="2026-10-22",
        window_days=7,
        comparison_start="2026-10-17",
        comparison_end="2026-10-22",
        comparison_days=6,
    )
    markdown = report.to_markdown()
    assert "比较区间 2026-10-17 → 2026-10-22（6 天，源集合同构）" in markdown
    assert "跨源集合变更日的对比已禁用" in markdown


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


def test_parse_range_rejects_bad_value() -> None:
    """直接测解析函数：CLI 输出会被 rich 按终端宽度换行，断言字符串在 CI 上不可靠。"""
    import typer

    from aipulse.cli.commands.trend import _parse_range

    with pytest.raises(typer.BadParameter, match="--range"):
        _parse_range("week")
    assert _parse_range("7d") == 7


def test_cli_rejects_bad_range(monkeypatch) -> None:  # noqa: ANN001
    from typer.testing import CliRunner

    from aipulse.cli.commands import trend as trend_cli

    monkeypatch.setattr(trend_cli, "load_settings", lambda: _fake_settings("off"))
    result = CliRunner().invoke(trend_cli.app, ["--range", "week"])
    # 只断言"非零退出"：错误框的具体排版随终端宽度变化（CI 上会把 --range 折断）
    assert result.exit_code != 0


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


def test_violations_flag_over_budget() -> None:
    from aipulse.reasoning.trend import Evidence

    out = violations(
        "it_abcdef123456 很热。" * 30,
        Evidence(text=""),
        requires_speculation=False,
        weak_corr=False,
        max_chars=100,
    )
    assert any("字数上限" in item for item in out)


def test_evidence_lists_collection_failures(tmp_path) -> None:  # noqa: ANN001
    """采集失败必须作为独立证据块出现，且被污染板块不出现在"上升/下降"里。"""
    ok = [{"source": "hf_papers", "status": "ok", "item_count": 10}]
    bad = [{"source": "hf_papers", "status": "degraded", "item_count": 0}]
    for day, has_items, runs in (
        ("2026-10-18", True, ok),
        ("2026-10-19", False, bad),
        ("2026-10-20", True, ok),
        ("2026-10-21", True, ok),
    ):
        items = [_item("it_p", "paper", 40.0, source="hf_papers")] if has_items else []
        _day(
            tmp_path,
            day,
            items,
            sections=[_section("论文与研究", ["it_p"] if has_items else [])],
            source_runs=runs,
        )
    index = load_cross_period(tmp_path)
    from aipulse.analysis.cross_period import compute_all

    reports = {r.key: r for r in compute_all(index)}
    evidence = build_evidence(index, reports, "falling_topics")
    assert "采集异常" in evidence.text
    assert "item_count=0" in evidence.text
    assert "禁止对这些板块作趋势判断" in evidence.text
    # 被污染的板块不得出现在份额清单里
    assert "论文与研究：份额" not in evidence.text


def test_correlation_negation_is_not_a_violation() -> None:
    """澄清句（不作相关解读 / 无共动证据）不应被判违规。"""
    from aipulse.reasoning.trend import Evidence

    out = violations(
        "it_abcdef123456 本周没有可核验的组内同步证据，因此不补充相关性或共动判断。",
        Evidence(text=""),
        requires_speculation=False,
        weak_corr=True,
    )
    assert out == []


# ── S5 人类层渲染 ─────────────────────────────────────────────────────────


def test_render_weekly_has_no_bare_ids_in_body() -> None:
    """正文（数据溯源区之前）不得出现裸 item_id；ID 只在文末溯源区。"""
    from aipulse.render.weekly import render_weekly

    report = TrendReport(
        window_start="2026-10-19",
        window_end="2026-10-21",
        window_days=3,
        headlines=["社区舆论份额收缩最明显", "论文板块本周不作判断", "榜单换血依然剧烈"],
        judgements=[],
        caveats=["份额只在 10-20→10-21 区间计算"],
        segments=[
            TrendSegment(
                key="rising_topics",
                title="上升主题",
                body="it_d56bf7f0d55e498a 与 it_2132166d14a053db 同步上升。",
                cited_item_ids=["it_d56bf7f0d55e498a"],
            )
        ],
    )
    markdown = render_weekly(report, _index_for_render())
    body = markdown.split("## 数据溯源")[0]
    assert "it_d56bf7f0d55e498a" not in body, body
    assert "📌 本周三句话" in markdown
    assert "🎯 下期观察" in markdown  # 表格由 cross_period 确定性渲染
    assert "<details>" in markdown and "份额只在" in markdown
    assert "it_d56bf7f0d55e498a" in markdown.split("## 数据溯源")[1]


def _index_for_render():
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp())
    _day(tmp, "2026-10-19", [_item("it_a", "alpha", 10.0)])
    _day(tmp, "2026-10-20", [_item("it_a", "alpha", 20.0)])
    _day(tmp, "2026-10-21", [_item("it_a", "alpha", 30.0), _item("it_b", "beta", 40.0)])
    return load_cross_period(tmp)


def test_machine_json_keeps_bodies_and_ids_for_l1() -> None:
    """机器层必须保留 L1-L4 依赖的全部数据（7 节正文 + 裸 ID + 免责）。"""
    report = TrendReport(
        window_end="2026-10-21",
        caveats=["比较区间 10-20 → 10-21"],
        segments=[
            TrendSegment(
                key="rising_topics",
                title="上升主题",
                body="it_d56bf7f0d55e498a 上升",
                cited_item_ids=["it_d56bf7f0d55e498a"],
                violations=["超字数"],
            )
        ],
    )
    payload = report.to_machine_json()
    assert payload["schema_version"] == 2
    assert payload["segments"][0]["body"] == "it_d56bf7f0d55e498a 上升"
    assert payload["segments"][0]["cited_item_ids"] == ["it_d56bf7f0d55e498a"]
    assert payload["segments"][0]["violations"] == ["超字数"]
    assert payload["caveats"] == ["比较区间 10-20 → 10-21"]


def test_headline_candidates_cover_all_structures(tmp_path) -> None:  # noqa: ANN001
    """三句话的候选池要覆盖 9 个结构，而不是只有板块份额。"""
    from aipulse.analysis.cross_period import compute_all
    from aipulse.reasoning.trend import build_headline_candidates

    index = _index_for_render()
    reports = {r.key: r for r in compute_all(index)}
    text = build_headline_candidates(index, reports)
    # 至少覆盖三类不同结构（份额 / 持续性 / 预言），而不是只有板块份额
    assert "只在榜 1-2 天的条目" in text
    assert "来源份额变化" in text
    assert "预言" in text
    assert text.startswith("- ")


# ── 30 天窗口（C5）────────────────────────────────────────────────────────


def test_direction_eps_scales_with_window() -> None:
    """阈值必须随窗口缩放：5 天是原始锚点，窗口越长越灵敏、越短越保守。"""
    from aipulse.analysis.cross_period import direction_eps

    assert direction_eps(5) == pytest.approx(0.5)
    assert direction_eps(3) > direction_eps(5) > direction_eps(7) > direction_eps(30)
    assert direction_eps(30) == pytest.approx(0.5 * (5 / 30) ** 0.5, rel=1e-6)
    # 退化输入不能炸：0/1 天按 2 天算
    assert direction_eps(0) == direction_eps(2)


def test_shortfall_note_says_how_many_days_missing() -> None:
    from aipulse.reasoning.trend import window_shortfall_note

    days = [f"2026-10-{d:02d}" for d in range(15, 25)]
    note = window_shortfall_note(30, days)
    assert "请求 30 天" in note
    assert "实际只有 10 天" in note
    assert "还需再攒 20 天" in note
    assert window_shortfall_note(7, days) == ""
    assert window_shortfall_note(0, days) == ""


def test_slice_index_returns_all_when_window_too_long() -> None:
    from aipulse.reasoning.trend import slice_index

    index = _index_for_render()
    sliced = slice_index(index, 30)
    assert sliced.days == index.days


@pytest.mark.asyncio
async def test_generate_trend_records_shortfall_caveat(tmp_path) -> None:  # noqa: ANN001
    """30 天请求 + 3 天数据：免责里必须写明缺口，不能假装跑满。"""
    from aipulse.reasoning.trend import generate_trend

    index = _index(tmp_path)
    client = _ScriptedClient([GOOD_BODY])
    report = await generate_trend(index, client, window_days=30, max_tokens=2000, requested_days=30)
    assert report.caveats
    assert "请求 30 天" in report.caveats[0]
    assert "还需再攒" in report.caveats[0]


def test_comparison_line_shows_short_segment() -> None:
    """P1-4 替代方案：短尾巴必须可见，不能让读者以为整个窗口都参与了比较。"""
    from aipulse.analysis.cross_period import compute_all
    from aipulse.reasoning.trend import _comparison_line

    index = _index_for_render()
    line = _comparison_line({r.key: r for r in compute_all(index)})[0]
    assert "对比区间" in line
    assert "全窗口" in line
