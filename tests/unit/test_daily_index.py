"""M6c S2.5：daily.json 索引解析。"""

from __future__ import annotations

import json
from pathlib import Path

from aipulse.knowledge.daily_index import (
    build_daily_index,
    find_by_url,
    search_by_query,
)


def _write_daily(
    root: Path,
    day: str,
    *,
    items: dict[str, object],
    comments: list[object] | None = None,
    sections: list[object] | None = None,
    extra: dict[str, object] | None = None,
) -> Path:
    year, month, day_num = day.split("-")
    path = root / year / month / day_num / "daily.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "date": day,
        "items": items,
        "comments": comments if comments is not None else [],
        "sections": sections if sections is not None else [],
    }
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _item(title: str, url: str, *, hot: float = 10.0) -> dict[str, object]:
    return {"title": title, "url": url, "hot_score": hot}


def test_build_parses_four_historical_shapes_and_merges_by_item(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    _write_daily(root, "2026-10-15", items={"it_1": _item("Agent One", "https://e/1")})
    _write_daily(root, "2026-10-16", items={"it_1": _item("Agent One", "https://e/1")})
    _write_daily(
        root,
        "2026-10-17",
        items={"it_1": _item("Agent One", "https://e/1")},
        comments=[
            {"item_id": "it_1", "one_liner": "旧要点", "why_it_matters": "旧 why"},
        ],
        sections=[{"name": "开源项目", "item_ids": ["it_1"]}],
        extra={"headline_item_id": "it_1", "overview_bullets": []},
    )
    _write_daily(
        root,
        "2026-10-18",
        items={"it_1": _item("Agent One", "https://e/1", hot=88.0)},
        comments=[{"item_id": "it_1", "one_liner": "新要点", "why": "新 why"}],
        sections=[{"name": "开源项目", "item_ids": ["it_1"]}],
        extra={"headline_item_id": "it_1", "overview_bullets": []},
    )

    index = build_daily_index(root)

    assert list(index.items) == ["it_1"]
    item = index.items["it_1"]
    assert item.title == "Agent One"
    assert item.url == "https://e/1"
    assert item.section == "开源项目"
    assert item.date == "2026-10-18"
    assert item.hot_score == 88.0
    assert item.why == "新 why"
    assert item.one_liner == "新要点"
    assert index.url_to_id["https://e/1"] == "it_1"
    assert index.title_to_ids["Agent One"] == ["it_1"]


def test_merge_prefers_why_bearing_record(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    _write_daily(
        root,
        "2026-10-17",
        items={"it_1": _item("Agent One", "https://e/1")},
        comments=[{"item_id": "it_1", "one_liner": "旧要点", "why_it_matters": "旧 why"}],
    )
    _write_daily(
        root,
        "2026-10-18",
        items={"it_1": _item("Agent One", "https://e/1")},
        comments=[{"item_id": "it_1", "one_liner": "新要点"}],
    )

    item = build_daily_index(root).items["it_1"]
    assert item.why == "旧 why"
    assert item.date == "2026-10-17"
    assert item.one_liner == "旧要点"


def test_url_lookup_and_title_query(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    _write_daily(
        root,
        "2026-10-18",
        items={
            "it_1": _item("Agent Framework", "https://e/agent"),
            "it_2": _item("Building an agent", "https://e/build"),
            "it_3": _item("Other", "https://e/other"),
        },
    )
    index = build_daily_index(root)

    assert find_by_url(index, "https://e/agent") is not None
    assert find_by_url(index, "https://e/agent").item_id == "it_1"  # type: ignore[union-attr]
    assert find_by_url(index, "https://e/missing") is None

    matches = search_by_query(index, "AGENT")
    assert [item.item_id for item in matches] == ["it_1", "it_2"]
    assert search_by_query(index, "") == []
    assert search_by_query(index, "zzz") == []


def test_tolerates_missing_fields_and_bad_json(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    _write_daily(
        root,
        "2026-10-18",
        items={
            "it_no_url": {"title": "只有标题"},
            "it_no_title": {"url": "https://e/no-title"},
            "it_no_title_or_url": {},
            "it_not_dict": "bad",
        },
        comments="not-a-list",  # type: ignore[arg-type]
        sections="not-a-list",  # type: ignore[arg-type]
    )
    bad = root / "2026" / "10" / "17" / "daily.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{broken json", encoding="utf-8")

    index = build_daily_index(root)
    assert set(index.items) == {"it_no_url", "it_no_title"}
    assert index.items["it_no_url"].url == ""
    assert index.items["it_no_title"].title == ""
    assert index.items["it_no_title"].url == "https://e/no-title"


def test_real_historical_reports_parse() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    reports = repo_root / "data" / "reports"
    paths = sorted(reports.rglob("daily.json"))
    assert len(paths) >= 4

    index = build_daily_index(reports)
    assert index.items
    assert any(item.why for item in index.items.values())
    assert any(item.one_liner for item in index.items.values())
