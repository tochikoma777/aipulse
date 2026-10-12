import pytest
from typer.testing import CliRunner

from aipulse.cli.commands import collect, predict
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
    with pytest.raises(NotImplementedError):
        collect.app.registered_commands[0].callback()
    with pytest.raises(NotImplementedError):
        predict.app.registered_commands[0].callback()


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
