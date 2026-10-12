import os

import pytest

from aipulse.core.config import (
    RunMode,
    Settings,
    interpolate_env,
    load_settings,
    load_sources,
    load_yaml,
    project_root,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    load_settings.cache_clear()
    yield
    load_settings.cache_clear()


def test_project_root_is_repo_root():
    assert (project_root() / "pyproject.toml").exists()


def test_interpolate_env_with_default():
    os.environ["AIPULSE_TEST_VAR"] = "hello"
    try:
        assert interpolate_env("${AIPULSE_TEST_VAR}") == "hello"
        assert interpolate_env("${AIPULSE_MISSING_VAR}") == ""
        assert interpolate_env("${AIPULSE_MISSING_VAR:-fallback}") == "fallback"
    finally:
        os.environ.pop("AIPULSE_TEST_VAR", None)


def test_load_settings_interpolates_env_into_yaml(monkeypatch):
    monkeypatch.setenv("AIPULSE_LLM__API_KEY", "sk-unit-test")
    settings = load_settings()
    assert settings.llm.api_key == "sk-unit-test"
    assert settings.app.timezone == "Asia/Shanghai"
    assert settings.http.timeout_read_s == 20


def test_effective_mode_degrades_without_api_key(monkeypatch):
    monkeypatch.delenv("AIPULSE_LLM__API_KEY", raising=False)
    settings = Settings(llm={"api_key": ""})  # type: ignore[arg-type]
    assert settings.effective_mode() == RunMode.OFF

    settings_full = Settings(mode=RunMode.FULL, llm={"api_key": "sk-x"})  # type: ignore[arg-type]
    assert settings_full.effective_mode() == RunMode.FULL


def test_load_yaml_missing_file_returns_empty(tmp_path):
    assert load_yaml(tmp_path / "nope.yaml") == {}


def test_load_sources_reads_feeds_and_tiers():
    sources = load_sources()
    rss = sources.sources["rss"]
    assert rss.feeds, "sources.yaml 至少要有一个 RSS feed"
    tiers = {f.tier for f in rss.feeds}
    assert tiers <= {"core", "optional"}
    assert any(f.tier == "core" for f in rss.feeds), "英文主干源必须存在"
    assert sources.sources["arxiv"].rate_limit == "3/s"


def test_source_config_allows_source_specific_fields():
    cfg = load_sources().sources["hackernews"]
    # extra=allow：各源特有字段（queries / min_points ...）不应被丢弃
    assert cfg.queries  # type: ignore[attr-defined]
    assert cfg.weight > 0


def test_data_dir_and_db_path(monkeypatch, tmp_path):
    monkeypatch.setenv("AIPULSE_ROOT", str(tmp_path))
    settings = load_settings.__wrapped__() if hasattr(load_settings, "__wrapped__") else Settings()
    assert settings.data_dir() == tmp_path / "data"
    assert settings.db_path().name == "aipulse.db"
