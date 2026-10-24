"""trend / debate CLI 的关键路径（C6：把 cli/commands 覆盖率拉到 ≥70%）。

只走离线路径：StubLLM 固定返回、临时目录造日报，不碰网络、不碰主库。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from aipulse.cli.commands import debate as debate_cmd
from aipulse.cli.commands import trend as trend_cmd
from aipulse.cli.main import app
from aipulse.core.config import Settings
from aipulse.llm.base import ChatMessage, LLMResult
from aipulse.reasoning.trend import SEGMENTS

BODY = (
    "论文板块份额从 0.231 升到 0.3495（+11.86pp），代表条目 it_d56bf7f0d55e498a 与 "
    "it_2132166d14a053db 同步上升；这一判断属推测，依据是斜率 +11.86pp/天。"
)
HEADLINES = json.dumps(
    {
        "headlines": ["份额收缩最明显", "论文板块不作判断", "换血依然剧烈"],
        "judgements": [
            {
                "key": "structural_changes",
                "title": "结构变化",
                "claim": "开源在涨，社区在收缩",
                "cited_item_ids": ["it_d56bf7f0d55e498a"],
            }
        ],
    },
    ensure_ascii=False,
)


class StubLLM:
    def __init__(self) -> None:
        self.purposes: list[str] = []
        self.prompts: list[str] = []

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
        self.purposes.append(purpose)
        self.prompts.append(messages[-1].content if messages else "")
        return LLMResult(
            content=HEADLINES if purpose == "trend_headlines" else BODY,
            model=f"fake/{model_tier}",
            prompt_tokens=100,
            completion_tokens=50,
        )


def _seed(root: Path, days: int = 4) -> Path:
    reports = root / "reports"
    for offset in range(days):
        day = f"2026-10-{20 + offset:02d}"
        target = reports.joinpath(*day.split("-"))
        target.mkdir(parents=True, exist_ok=True)
        items = {
            "it_d56bf7f0d55e498a": {
                "title": "alpha",
                "url": "https://example.com/a",
                "source": "github_trending",
                "hot_score": 90.0 + offset,
            },
            "it_2132166d14a053db": {
                "title": "beta",
                "url": "https://example.com/b",
                "source": "rss",
                "hot_score": 80.0 - offset,
            },
        }
        (target / "daily.json").write_text(
            json.dumps(
                {
                    "date": day,
                    "items": items,
                    "sections": [
                        {"name": "开源项目", "item_ids": ["it_d56bf7f0d55e498a"]},
                        {"name": "社区舆论", "item_ids": ["it_2132166d14a053db"]},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return reports


def _settings(root: Path, **overrides: Any) -> Settings:
    payload: dict[str, Any] = {
        "app": {"data_dir": str(root)},
        "mode": "hybrid",
        "llm": {"api_key": "sk-test-key"},
    }
    payload.update(overrides)
    return Settings(**payload)


def test_trend_cli_fails_fast_in_off_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(app={"data_dir": str(tmp_path)}, mode="off")
    monkeypatch.setattr(trend_cmd, "load_settings", lambda *a, **k: settings)
    result = CliRunner().invoke(app, ["trend"])
    assert result.exit_code == 2
    assert "off 档" in result.output


def test_trend_cli_reports_missing_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(trend_cmd, "load_settings", lambda *a, **k: settings)
    result = CliRunner().invoke(app, ["trend", "--reports-dir", str(tmp_path / "nope")])
    assert result.exit_code == 2
    assert "没有找到任何日报" in result.output


def test_trend_cli_rejects_unknown_segment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reports = _seed(tmp_path)
    monkeypatch.setattr(trend_cmd, "load_settings", lambda *a, **k: _settings(tmp_path))
    result = CliRunner().invoke(app, ["trend", "--reports-dir", str(reports), "--segments", "nope"])
    assert result.exit_code == 2
    assert "未知的段" in result.output


def test_trend_cli_warns_on_shortfall_and_writes_both_layers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--range 30d 但只有 4 天：必须打印缺口，仍正常出产物（两层）。"""
    reports = _seed(tmp_path)
    monkeypatch.setattr(trend_cmd, "load_settings", lambda *a, **k: _settings(tmp_path))
    monkeypatch.setattr(trend_cmd, "build_client", lambda *a, **k: StubLLM())

    result = CliRunner().invoke(
        app, ["trend", "--reports-dir", str(reports), "--range", "30d", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert "请求 30 天" in result.output
    assert "还需再攒" in result.output

    issue_dir = reports / "trend" / "2026-10-23"
    assert (issue_dir / "weekly.md").exists()
    payload = json.loads((issue_dir / "weekly.json").read_text(encoding="utf-8"))
    assert payload["caveats"][0].startswith("请求 30 天")
    assert payload["llm"]["calls"] == len(SEGMENTS) + 1


def test_trend_cli_applies_admission_rule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reports = _seed(tmp_path)
    issue_dir = reports / "trend" / "2026-10-20"
    issue_dir.mkdir(parents=True)
    (issue_dir / "admission.json").write_text(
        json.dumps(
            {
                "level": "strict",
                "max_structure_claims": 1,
                "reason": "上期结构方向未延续",
                "based_on": "2026-10-20",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(trend_cmd, "load_settings", lambda *a, **k: _settings(tmp_path))
    stub = StubLLM()
    monkeypatch.setattr(trend_cmd, "build_client", lambda *a, **k: stub)

    # 显式 --range 优先于配置的 interval
    result = CliRunner().invoke(app, ["trend", "--reports-dir", str(reports), "--range", "7d"])
    assert result.exit_code == 0, result.output
    assert "准入收紧" in result.output
    # 约束要真的进 prompt，而不只是打印
    assert any("最多给出 1 条结构判断" in prompt for prompt in stub.prompts)


def test_debate_cli_off_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(app={"data_dir": str(tmp_path)}, mode="off")
    monkeypatch.setattr(debate_cmd, "load_settings", lambda *a, **k: settings)
    result = CliRunner().invoke(app, ["debate", "--topic", "x"])
    assert result.exit_code == 2
    assert "off 档" in result.output


def test_debate_cli_rejects_bad_range(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reports = _seed(tmp_path)
    monkeypatch.setattr(debate_cmd, "load_settings", lambda *a, **k: _settings(tmp_path))
    result = CliRunner().invoke(
        app, ["debate", "--topic", "x", "--range", "week", "--reports-dir", str(reports)]
    )
    assert result.exit_code == 2
    # ★ 不断言错误文本里的 "--range"：rich 会按终端宽度折断长选项
    # （CI 上会被截成 "--ran…"）。BadParameter 的退出码本身就是判据。


def test_trend_cli_uses_interval_when_range_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """省略 --range → 按 pipeline.trend.interval 取上一个完整自然月。"""
    from datetime import date

    reports = _seed(tmp_path)  # 10-20 → 10-23
    monkeypatch.setattr(trend_cmd, "load_settings", lambda *a, **k: _settings(tmp_path))
    monkeypatch.setattr(trend_cmd, "today_local", lambda *a, **k: date(2026, 11, 1))
    monkeypatch.setattr(trend_cmd, "build_client", lambda *a, **k: StubLLM())

    result = CliRunner().invoke(app, ["trend", "--reports-dir", str(reports)])
    assert result.exit_code == 0, result.output
    assert "按 pipeline.trend.interval=1m（日历月）取 2026-10-01 → 2026-10-31" in result.output
    payload = json.loads(
        (reports / "trend" / "2026-10-23" / "weekly.json").read_text(encoding="utf-8")
    )
    assert payload["window"] == {"start": "2026-10-20", "end": "2026-10-23", "days": 4}
    # 缺口按"日历月应有几天"算，不是按请求的 N 天
    assert "分析范围 2026-10-01 → 2026-10-31（应有 31 天）" in payload["caveats"][0]


def test_trend_cli_errors_when_interval_window_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """interval 推导出的范围一篇日报都没有 → exit 2（用法/数据错误，该红）。"""
    from datetime import date

    reports = _seed(tmp_path)  # 10-20 → 10-23
    monkeypatch.setattr(trend_cmd, "load_settings", lambda *a, **k: _settings(tmp_path))
    monkeypatch.setattr(trend_cmd, "today_local", lambda *a, **k: date(2026, 12, 1))

    result = CliRunner().invoke(app, ["trend", "--reports-dir", str(reports)])
    assert result.exit_code == 2
    assert "分析范围 2026-11-01 → 2026-11-30 内没有日报" in result.output
    assert "现有 2026-10-20 → 2026-10-23" in result.output


def test_trend_cli_disabled_requires_explicit_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """trigger_mode=disabled：不给 --range 直接劝退；给了就放行（手动覆盖）。"""
    from datetime import date

    reports = _seed(tmp_path)
    monkeypatch.setattr(
        trend_cmd,
        "load_settings",
        lambda *a, **k: _settings(tmp_path, pipeline={"trend": {"trigger_mode": "disabled"}}),
    )
    monkeypatch.setattr(trend_cmd, "today_local", lambda *a, **k: date(2026, 11, 1))

    result = CliRunner().invoke(app, ["trend", "--reports-dir", str(reports)])
    assert result.exit_code == 2
    assert "trigger_mode=disabled" in result.output
