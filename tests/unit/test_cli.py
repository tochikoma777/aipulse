import pytest
from typer.testing import CliRunner

from aipulse.cli.commands import debate, topics
from aipulse.cli.commands.doctor import run_doctor
from aipulse.cli.main import app
from aipulse.core.config import load_settings

runner = CliRunner()

ALL_COMMANDS = [
    "init",
    "doctor",
    "collect",
    "normalize",
    "analyze",
    "brief",
    "predict",
    "debate",
    "trend",
    "daily",
    "stats",
    "topics",
    "search",
    "inbox",
    "knowledge",
    "sources",
    "serve",
]


def test_help_shows_all_subcommands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ALL_COMMANDS:
        assert command in result.output, f"{command} 未在 --help 中出现"


def test_subcommand_help_visible():
    result = runner.invoke(app, ["predict", "--help"])
    assert result.exit_code == 0
    for sub in ("add", "list", "verify", "review"):
        assert sub in result.output


def test_placeholder_commands_raise_not_implemented():
    # debate 已在 M5 S4 实现，此处改用仍未实现的 topics 验证占位行为
    with pytest.raises(NotImplementedError):
        topics.app.registered_commands[0].callback()


def test_debate_is_implemented_and_needs_topic():
    # 真命令不再抛 NotImplementedError。
    # ★ 不断言 --help 文本：rich 会按终端宽度折断长选项（CI 上 COLUMNS 较窄，
    #   实测 "--topic" 会被截成 "--topi…"）。需要 topic 的行为由
    #   test_debate_cli_requires_topic 用退出码覆盖。
    result = runner.invoke(app, ["debate", "--help"])
    assert result.exit_code == 0
    assert not debate.app.registered_commands


def test_doctor_without_network_returns_zero(tmp_path):
    # 数据库缺失只算警告（提示先跑 init），不应让 doctor 直接判死
    code = run_doctor(json_output=True, skip_network=True)
    assert code == 0


def test_init_creates_db(tmp_path):
    load_settings.cache_clear()
    result = runner.invoke(app, ["init", "--db", str(tmp_path / "init.db")])
    load_settings.cache_clear()
    assert result.exit_code == 0, result.output
    assert (tmp_path / "init.db").exists()
