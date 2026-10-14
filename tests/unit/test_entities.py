"""实体抽取单测（设计方案 §9.3）。"""

from __future__ import annotations

from datetime import date

from aipulse.analysis.entities import (
    build_entity_rows,
    count_entities,
    extract_entities,
    load_entity_entries,
)
from aipulse.store.models import Item


def test_load_entity_entries_has_models_and_frameworks():
    entries = load_entity_entries()
    by_type: dict[str, list[str]] = {}
    for name, etype, _aliases in entries:
        by_type.setdefault(etype, []).append(name)
    assert "model" in by_type and "GPT" in by_type["model"]
    assert "framework" in by_type and "vLLM" in by_type["framework"]


def test_extract_entities_matches_names_and_aliases():
    found = dict(extract_entities("OpenAI 发布 GPT-4，基于 vLLM 与 PyTorch，跑在 H100 集群上"))
    assert found["GPT"] == "model"
    assert found["vLLM"] == "framework"
    assert found["PyTorch"] == "framework"
    assert found["OpenAI"] == "company"
    assert found["H100"] == "hardware"


def test_extract_entities_is_case_insensitive_with_word_boundary():
    found = dict(extract_entities("we love gpt and deepseek"))
    assert found["GPT"] == "model"
    assert found["DeepSeek"] == "model"


def test_build_and_count_entity_rows():
    day = date(2026, 10, 14)
    items = [
        Item(id="i1", source="rss", external_id="e1", title="OpenAI GPT-5", url="https://x/1"),
        Item(id="i2", source="rss", external_id="e2", title="GPT 再次发布", url="https://x/2"),
    ]
    rows = build_entity_rows(items, day=day)
    counts = count_entities(rows)
    # i1 命中 OpenAI + GPT；i2 命中 GPT → GPT 计数 2
    assert counts["GPT"]["count"] == 2
    assert counts["OpenAI"]["count"] == 1
