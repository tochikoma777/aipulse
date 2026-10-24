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
from aipulse.llm.base import NullLLM, build_client


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

    settings_full = Settings(  # type: ignore[arg-type]
        mode=RunMode.FULL, llm={"api_key": "sk-x", "base_url": "https://api.example.com/v1"}
    )
    assert settings_full.effective_mode() == RunMode.FULL


def test_effective_mode_degrades_without_base_url():
    """只有 key 没有 base_url（Actions 漏配环境变量的现场）必须降级 off，而不是崩溃。

    回归防线：`build_client` 拿到非 off 档就会构造 `OpenAICompatClient`，
    后者在 base_url 为空时抛 ConfigError——daily 会被这一条直接带崩。
    """
    settings = Settings(  # type: ignore[arg-type]
        mode=RunMode.FULL, llm={"api_key": "sk-x", "base_url": ""}
    )
    assert settings.effective_mode() == RunMode.OFF

    blank = Settings(  # type: ignore[arg-type]
        mode=RunMode.HYBRID, llm={"api_key": "sk-x", "base_url": "   "}
    )
    assert blank.effective_mode() == RunMode.OFF


def test_build_client_returns_null_without_base_url():
    """effective_mode 之后是真客户端还是 NullLLM——这条断言直接锁住运行行为。"""
    settings = Settings(  # type: ignore[arg-type]
        mode=RunMode.FULL, llm={"api_key": "sk-x", "base_url": ""}
    )
    assert isinstance(build_client(settings), NullLLM)


def test_env_overrides_placeholders_in_yaml(monkeypatch):
    """★ 回归防线：`load_settings` 是 `Settings(**yaml)`，init kwargs 优先级高于环境变量。

    所以 YAML 里写成字面量的字段**永远**吃不到 `AIPULSE_*` 覆盖——daily.yml 声明的
    `AIPULSE_MODE: hybrid` 就是这样被静默无视、实际跑成 full 档的。
    凡是"按环境需要覆盖"的字段，都必须写成 `${VAR:-default}` 占位符。
    """
    monkeypatch.setenv("AIPULSE_MODE", "hybrid")
    monkeypatch.setenv("AIPULSE_LLM__BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("AIPULSE_LLM__API_KEY", "sk-x")
    monkeypatch.setenv("AIPULSE_LLM__STRONG_MODEL", "deepseek-chat")
    monkeypatch.setenv("AIPULSE_LOG_LEVEL", "DEBUG")

    settings = load_settings()

    assert settings.mode == RunMode.HYBRID
    assert settings.effective_mode() == RunMode.HYBRID
    assert settings.llm.strong_model == "deepseek-chat"
    assert settings.app.log_level == "DEBUG"


def test_strong_timeout_is_longer_than_fast():
    """strong 档走思维链，读超时必须比 fast 更长，否则预言生成会被中途掐断。"""
    settings = load_settings.__wrapped__() if hasattr(load_settings, "__wrapped__") else Settings()
    assert settings.llm.timeout_strong_s > settings.llm.timeout_s


def test_load_yaml_missing_file_returns_empty(tmp_path):
    assert load_yaml(tmp_path / "nope.yaml") == {}


def test_load_sources_reads_feeds_and_tiers():
    sources = load_sources()
    rss = sources.sources["rss"]
    assert rss.feeds, "sources.yaml 至少要有一个 RSS feed"
    tiers = {f.tier for f in rss.feeds}
    assert tiers <= {"core", "optional"}
    assert any(f.tier == "core" for f in rss.feeds), "英文主干源必须存在"
    assert sources.sources["arxiv"].rate_limit == "1/3s"  # arXiv 官方 3 秒 1 次


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


def test_load_settings_invokes_dotenv_before_yaml(monkeypatch):
    """★ 回归：`Settings(**yaml)` 的 init 参数优先于 env_file，
    不先 load_dotenv()，本地按 README 写进 .env 的 key 永远读不到。"""
    from aipulse.core import config as config_module

    monkeypatch.delenv("AIPULSE_LLM__API_KEY", raising=False)

    def fake_load_dotenv(*args, **kwargs):  # noqa: ANN001, ARG001
        os.environ["AIPULSE_LLM__API_KEY"] = "sk-from-dotenv"
        return True

    monkeypatch.setattr(config_module, "load_dotenv", fake_load_dotenv)
    load_settings.cache_clear()
    settings = load_settings()
    assert settings.llm.api_key == "sk-from-dotenv"
    load_settings.cache_clear()


def test_stale_weekly_debate_enabled_key_is_harmless() -> None:
    """★ 旧配置残留无害（SSOT v1.24 已删该字段，但老 yaml 里可能还写着）。

    `PipelineSettings` 是 pydantic 默认 `extra=ignore`：残留键被静默忽略，
    不报错、不影响行为。记成测试，避免下个会话把它当 bug 修。
    """
    settings = Settings(
        mode="hybrid", llm={"api_key": "sk-x"}, pipeline={"weekly_debate_enabled": True}
    )
    assert settings.pipeline.debate.trigger_mode == "auto"
    assert not hasattr(settings.pipeline, "weekly_debate_enabled")
