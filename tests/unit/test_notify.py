import pytest

from aipulse.notify.base import (
    Notifier,
    NotifyResult,
    RenderedReport,
    get_notifier,
)
from aipulse.notify.file import FileNotifier


async def test_file_notifier_writes_report(tmp_path):
    notifier = FileNotifier(base_dir=tmp_path)
    report = RenderedReport(
        date="2026-10-13",
        files={"brief.md": "# 日报", "meta.json": "{}"},
        meta={"mode": "off"},
    )
    result = await notifier.send(report)
    assert isinstance(result, NotifyResult)
    assert result.ok and result.channel == "file"
    assert (tmp_path / "2026" / "10" / "13" / "brief.md").read_text(encoding="utf-8") == "# 日报"


def test_file_notifier_satisfies_protocol():
    assert isinstance(FileNotifier(), Notifier)


def test_get_notifier_file_and_unimplemented_channels():
    assert isinstance(get_notifier("file"), FileNotifier)
    with pytest.raises(NotImplementedError):
        get_notifier("email")  # v1.2 决策：不做邮件/Telegram/飞书，只留接口
