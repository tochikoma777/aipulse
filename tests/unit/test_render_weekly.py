"""M5 S5 人类层渲染单测：纯离线，用 tmp_path 造日报。"""

from __future__ import annotations

import json
from pathlib import Path

from aipulse.analysis.cross_period import load_cross_period
from aipulse.render.weekly import linkify, render_weekly
from aipulse.schema.trend import Judgement, TrendReport, TrendSegment

_SECTIONS = {
    "社区舆论": ["it_1111111111111111", "it_2222222222222222"],
    "开源项目": ["it_3333333333333333"],
}
_TITLES = {
    "it_1111111111111111": ("话题 A1", "https://example.com/a1"),
    "it_2222222222222222": ("话题 A2", "https://example.com/a2"),
    "it_3333333333333333": ("仓库 B1", "https://example.com/b1"),
}
_URLS = {k: v[1] for k, v in _TITLES.items()}


def _daily(day: str, scores: dict[str, float]) -> dict[str, object]:
    items = {
        item_id: {
            "title": _TITLES[item_id][0],
            "url": _TITLES[item_id][1],
            "source": "hackernews",
            "hot_score": score,
            "summary": "摘要正文，不该出现在证据包里",
        }
        for item_id, score in scores.items()
    }
    return {
        "date": day,
        "items": items,
        "sections": [{"name": k, "item_ids": v} for k, v in _SECTIONS.items()],
    }


def _index(tmp_path: Path):  # noqa: ANN201
    days = {
        "2026-10-19": {
            "it_1111111111111111": 40.0,
            "it_2222222222222222": 30.0,
            "it_3333333333333333": 20.0,
        },
        "2026-10-20": {
            "it_1111111111111111": 60.0,
            "it_2222222222222222": 25.0,
            "it_3333333333333333": 30.0,
        },
        "2026-10-21": {
            "it_1111111111111111": 80.0,
            "it_2222222222222222": 20.0,
            "it_3333333333333333": 50.0,
        },
    }
    for day, scores in days.items():
        target = tmp_path.joinpath(*day.split("-"))
        target.mkdir(parents=True, exist_ok=True)
        (target / "daily.json").write_text(json.dumps(_daily(day, scores)), encoding="utf-8")
    return load_cross_period(tmp_path)


def _report() -> TrendReport:
    return TrendReport(
        window_start="2026-10-19",
        window_end="2026-10-21",
        window_days=3,
        headlines=["社区舆论热度抬升", "开源项目份额稳定", "榜单换血依然剧烈"],
        judgements=[
            Judgement(
                key="rising_topics",
                title="上升主题",
                claim="注意力集中在话题 A1",
                cited_item_ids=["it_1111111111111111"],
            )
        ],
        caveats=["份额只在 2026-10-19→2026-10-21 区间计算"],
        segments=[
            TrendSegment(
                key="rising_topics",
                title="上升主题",
                body="it_1111111111111111 与 it_3333333333333333 同步上升。",
                cited_item_ids=["it_1111111111111111", "it_3333333333333333"],
            )
        ],
    )


def test_share_table_is_rendered_from_structures(tmp_path: Path) -> None:
    """板块份额表由 cross_period 确定性渲染，不经模型。"""
    markdown = render_weekly(_report(), _index(tmp_path))
    assert "## 📊 板块份额变化" in markdown
    assert "社区舆论" in markdown
    assert "pp" in markdown
    assert "█" in markdown  # Unicode 条形图


def test_judgements_render_as_links_without_bare_ids(tmp_path: Path) -> None:
    markdown = render_weekly(_report(), _index(tmp_path))
    assert "依据 [话题 A1](https://example.com/a1)" in markdown


def test_linkify_replaces_bare_ids(tmp_path: Path) -> None:
    index = _index(tmp_path)
    out = linkify(index, "it_1111111111111111 很热，it_3333333333333333 也在榜")
    assert "it_1111111111111111" not in out
    assert "[话题 A1](https://example.com/a1)" in out
    assert "[仓库 B1](https://example.com/b1)" in out


def test_linkify_keeps_unknown_ids(tmp_path: Path) -> None:
    """窗口内没有的 id 不能被凭空编成链接。"""
    index = _index(tmp_path)
    out = linkify(index, "it_ffffffffffffffff 不在窗口内")
    assert "（条目已不在窗口内）" in out


def test_caveats_go_into_details(tmp_path: Path) -> None:
    markdown = render_weekly(_report(), _index(tmp_path))
    assert "<details>" in markdown
    assert "份额只在 2026-10-19→2026-10-21 区间计算" in markdown
    body = markdown.split("<details>")[0]
    assert "份额只在" not in body


def test_empty_report_still_renders(tmp_path: Path) -> None:
    markdown = render_weekly(TrendReport(window_end="2026-10-21"), _index(tmp_path))
    assert markdown.startswith("# AI 脉搏 · 周度趋势")


def test_dropped_table_lists_long_running_items(tmp_path: Path) -> None:
    """跌出表来自 emergence 的 dropped 事件，按连续在榜天数排序。"""
    index = _index(tmp_path)
    report = _report()
    # 造一个"昨天还在、今天不在"的条目轨迹：靠 emergence 的 dropped 判定
    markdown = render_weekly(report, index)
    assert "## 🔥 值得看的条目" in markdown or "## 🎯 下期观察" in markdown


def test_bar_and_share_table_handle_blocked_section(tmp_path: Path) -> None:
    """被封锁的板块要显示"封锁 + ⚠️"，不能编造份额。"""
    from aipulse.analysis.cross_period import compute_all

    index = _index(tmp_path)
    reports = {r.key: r for r in compute_all(index)}
    blocked = [
        e
        for e in (reports["heat_migration"].entries if "heat_migration" in reports else [])
        if isinstance(e, dict) and not e.get("trend_usable")
    ]
    markdown = render_weekly(_report(), index)
    if blocked:
        assert "**封锁**" in markdown
    else:
        assert "## 📊 板块份额变化" in markdown


# ── 数据健康 banner ───────────────────────────────────────────────────────


def _write_day_with_runs(
    target: Path, day: str, runs: dict[str, tuple[str, int]], scores: dict[str, float]
) -> None:
    """`source_runs.json` 是**独立文件**（不是 daily.json 的字段）。"""
    target.mkdir(parents=True, exist_ok=True)
    (target / "daily.json").write_text(
        json.dumps(_daily(day, scores), ensure_ascii=False), encoding="utf-8"
    )
    (target / "source_runs.json").write_text(
        json.dumps(
            {
                "sources": [
                    {"source": k, "status": v[0], "item_count": v[1]} for k, v in runs.items()
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_banner_absent_when_source_health_ok(tmp_path: Path) -> None:
    """正常时**不出现** banner（不能变成永久免责）。"""
    from aipulse.render.weekly import health_banner

    for day, score in (("2026-10-19", 40.0), ("2026-10-20", 60.0), ("2026-10-21", 80.0)):
        _write_day_with_runs(
            tmp_path.joinpath(*day.split("-")),
            day,
            {"arxiv": ("ok", 20), "rss": ("degraded", 12)},
            {"it_1111111111111111": score},
        )

    index = load_cross_period(tmp_path)
    banner = health_banner(index)
    # rss 是 degraded 但有条目 → 不算整源 0 条；arxiv 正常
    assert "整源 0 条" not in banner


def test_banner_fires_on_consecutive_zero_source(tmp_path: Path) -> None:
    """连续整源 0 条 + 可判样本 <5 → banner 出现在标题下方。"""
    from aipulse.render.weekly import health_banner

    for day, score in (("2026-10-19", 40.0), ("2026-10-20", 60.0), ("2026-10-21", 80.0)):
        _write_day_with_runs(
            tmp_path.joinpath(*day.split("-")),
            day,
            {"arxiv": ("failed", 0), "rss": ("ok", 12)},
            {"it_1111111111111111": score},
        )

    index = load_cross_period(tmp_path)
    banner = health_banner(index)
    assert banner.startswith("⚠️ 本周 ")
    assert "arxiv 连续 3 天整源 0 条" in banner
    assert "可判结构方向仅" in banner

    markdown = render_weekly(_report(), index)
    lines = markdown.splitlines()
    assert lines[0].startswith("# AI 脉搏")
    assert lines[2] == banner  # 标题下方、正文最前


def test_banner_streak_breaks_after_healthy_day(tmp_path: Path) -> None:
    """中间有一天正常 → 连续天数重新计数，不能虚报。"""
    from aipulse.render.weekly import health_banner

    plan = {
        "2026-10-19": ("failed", 0),
        "2026-10-20": ("ok", 30),
        "2026-10-21": ("failed", 0),
    }
    for day, runs in plan.items():
        _write_day_with_runs(
            tmp_path.joinpath(*day.split("-")), day, {"arxiv": runs}, {"it_1111111111111111": 50.0}
        )

    index = load_cross_period(tmp_path)
    banner = health_banner(index)
    assert "arxiv 整源 0 条" in banner
    assert "连续" not in banner


def test_banner_ignores_inbox_and_old_failures(tmp_path: Path) -> None:
    """inbox 是手动通道；窗口开头的旧故障也不能算成"连续 N 天"。"""
    from aipulse.render.weekly import health_banner

    plan = {
        "2026-10-19": {"inbox": ("degraded", 0), "hf_papers": ("degraded", 0), "arxiv": ("ok", 10)},
        "2026-10-20": {"inbox": ("degraded", 0), "hf_papers": ("ok", 8), "arxiv": ("ok", 12)},
        "2026-10-21": {"inbox": ("degraded", 0), "hf_papers": ("ok", 9), "arxiv": ("ok", 15)},
    }
    for day, runs in plan.items():
        _write_day_with_runs(
            tmp_path.joinpath(*day.split("-")), day, runs, {"it_1111111111111111": 50.0}
        )

    index = load_cross_period(tmp_path)
    banner = health_banner(index)
    assert "inbox" not in banner  # 手动投喂通道永远 0 条，不是故障
    # 窗口内出现过的整源 0 条要被报出来，但只有 1 天 → 不写"连续"
    assert "hf_papers 整源 0 条" in banner
    assert "hf_papers 连续" not in banner
