"""M5 S5 debate 人类层渲染单测：结论卡片 / 交锋矩阵 / 证伪表格 / 折叠全文。"""

from __future__ import annotations

import json
from pathlib import Path

from aipulse.analysis.cross_period import load_cross_period
from aipulse.render.debate import render_debate
from aipulse.schema.debate import (
    Challenge,
    CrossResponse,
    DebateReport,
    Falsification,
    ModeratorOutput,
    PersonaStatement,
)

_TITLES = {
    "it_1111111111111111": ("话题 A1", "https://example.com/a1"),
    "it_2222222222222222": ("仓库 B1", "https://example.com/b1"),
}


def _index(tmp_path: Path):  # noqa: ANN201
    for day, score in (("2026-10-20", 40.0), ("2026-10-21", 60.0)):
        target = tmp_path.joinpath(*day.split("-"))
        target.mkdir(parents=True, exist_ok=True)
        payload = {
            "date": day,
            "items": {
                item_id: {"title": title, "url": url, "hot_score": score}
                for item_id, (title, url) in _TITLES.items()
            },
            "sections": [],
        }
        (target / "daily.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    return load_cross_period(tmp_path)


def _report() -> DebateReport:
    falsification = Falsification(
        claim="这是真实采用",
        observable="2026-10-24 该条目是否仍在 Top30",
        if_observed="继续跟踪",
        if_not_observed="移出名单",
        target_item_ids=["it_1111111111111111"],
    )
    statements = [
        PersonaStatement(
            persona="optimist",
            persona_label="乐观派",
            stance="这是真实采用的前哨",
            key_points=["配套层同步升温", "多主题同窗共现", "早期受益者清晰"],
            reasoning="it_1111111111111111 与 it_2222222222222222 同时在榜。",
            cited_item_ids=["it_1111111111111111", "it_2222222222222222"],
            falsification=falsification.model_copy(deep=True),
        ),
        PersonaStatement(
            persona="skeptic",
            persona_label="怀疑派",
            stance="证据不足",
            invalid_reason="未引用任何证据包内的 item_id",
        ),
    ]
    cross = [
        CrossResponse(
            persona="optimist",
            persona_label="乐观派",
            challenges=[
                Challenge(
                    target="怀疑派",
                    point="用被质疑的指标去验真，等于没验",
                    outcome="部分让步",
                    cited_item_ids=["it_1111111111111111"],
                )
            ],
            concessions=["承认样本只有三天"],
            revised_stance="维持，但降低强度",
            cited_item_ids=["it_1111111111111111"],
        )
    ]
    moderator = ModeratorOutput(
        consensus=["四方都承认证据只有单窗口"],
        key_disagreements=["能否直接判脉冲 vs 只能判证据不足"],
        actionable_conclusions=["下一窗口核对留存"],
        overall_confidence=0.44,
        falsifications=[falsification.model_copy(deep=True)],
    )
    return DebateReport(
        topic="测试议题",
        window_start="2026-10-20",
        window_end="2026-10-21",
        window_days=2,
        evidence_lines=["it_1111111111111111｜话题 A1｜热度 60.0｜社区舆论"],
        statements=statements,
        cross=cross,
        moderator=moderator,
        llm_calls=9,
        attempts=9,
        cost_cny=0.1683,
    )


def test_confidence_card_is_prominent(tmp_path: Path) -> None:
    markdown = render_debate(_report(), _index(tmp_path))
    assert "## 🧭 结论卡片" in markdown
    assert "| 整体置信度 | **0.44** |" in markdown
    assert "关键分歧" in markdown


def test_key_points_and_collapsed_full_text(tmp_path: Path) -> None:
    markdown = render_debate(_report(), _index(tmp_path))
    assert "配套层同步升温" in markdown
    assert "<details>" in markdown and "展开 乐观派 全文" in markdown
    # 折叠全文里的裸 ID 也要转成链接
    assert "展开 乐观派 全文" in markdown


def test_challenge_matrix_keeps_the_essence(tmp_path: Path) -> None:
    markdown = render_debate(_report(), _index(tmp_path))
    assert "## ⚔️ 交锋矩阵（Round 2）" in markdown
    assert "乐观派 → 怀疑派" in markdown
    assert "用被质疑的指标去验真" in markdown
    assert "部分让步" in markdown


def test_falsification_table_columns(tmp_path: Path) -> None:
    markdown = render_debate(_report(), _index(tmp_path))
    assert "| 断言 | 观测什么 | 成立 → | 不成立 → |" in markdown
    assert "2026-10-24 该条目是否仍在 Top30" in markdown


def test_invalid_persona_is_marked(tmp_path: Path) -> None:
    markdown = render_debate(_report(), _index(tmp_path))
    assert "本方陈述无效：未引用任何证据包内的 item_id" in markdown


def test_body_has_no_bare_ids(tmp_path: Path) -> None:
    markdown = render_debate(_report(), _index(tmp_path))
    body = markdown.split("## 数据溯源")[0]
    assert "it_1111111111111111" not in body
    assert "[话题 A1](https://example.com/a1)" in body
    assert "it_1111111111111111" in markdown.split("## 数据溯源")[1]


def test_render_without_index_still_works() -> None:
    markdown = render_debate(_report())
    assert "## 🧭 结论卡片" in markdown
    assert "## 数据溯源" not in markdown


def test_failures_and_truncation_are_shown(tmp_path: Path) -> None:
    report = _report()
    report.failures = ["key_disagreements 为空：判失败"]
    report.truncated = ["工程派(R1)"]
    markdown = render_debate(report, _index(tmp_path))
    assert "⛔ 本次辩论判失败" in markdown
    assert "截断：工程派(R1)" in markdown


def test_bad_falsification_goes_to_details(tmp_path: Path) -> None:
    report = _report()
    bad = Falsification(
        claim="会涨",
        observable="热度是否不低于 82.89",
        if_observed="维持",
        if_not_observed="证伪",
    )
    bad.selfcheck()
    report.moderator.falsifications = [bad]
    markdown = render_debate(report, _index(tmp_path))
    assert "不可用证伪条件与运行异常" in markdown
    assert "点值阈值" in markdown
