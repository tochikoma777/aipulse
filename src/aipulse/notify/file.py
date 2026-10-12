"""FileNotifier：唯一的默认通知渠道（写 `data/reports/YYYY/MM/DD/`）。"""

from __future__ import annotations

from pathlib import Path

from aipulse.core.logging import get_logger
from aipulse.notify.base import NotifyResult, RenderedReport

log = get_logger(__name__)


class FileNotifier:
    """把渲染产物写到报告目录。"""

    name = "file"

    def __init__(self, base_dir: str | Path = "data/reports") -> None:
        self.base_dir = Path(base_dir)

    def _target_dir(self, report: RenderedReport) -> Path:
        # date 形如 2026-10-13 → data/reports/2026/10/13/
        parts = str(report.date).split("-")
        if len(parts) != 3:
            return self.base_dir / str(report.date)
        return self.base_dir / parts[0] / parts[1] / parts[2]

    async def send(self, report: RenderedReport) -> NotifyResult:
        target = self._target_dir(report)
        try:
            target.mkdir(parents=True, exist_ok=True)
            written: list[str] = []
            for filename, content in report.files.items():
                path = target / filename
                path.write_text(content, encoding="utf-8")
                written.append(str(path))
            log.info("notify.file.ok", files=written)
            return NotifyResult(
                channel=self.name, ok=True, detail=f"已写入 {len(written)} 个文件 → {target}"
            )
        except OSError as exc:
            log.error("notify.file.error", error=repr(exc))
            return NotifyResult(channel=self.name, ok=False, detail=str(exc))
