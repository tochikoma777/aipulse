"""手动投喂采集器（设计方案 §5.8）。

v1.1 起这是**微信 / X 内容的唯一合规入口**——不抓取任何微信或 X 内容。

两种用法：
1. `fetch()`：扫描 `data/inbox/*.md`，每行一条 URL（可带 `--note` 之外的自由文本）；
2. `item_from_url()`：CLI `aipulse inbox add <url>` 用它抓标题与摘要。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import httpx

from aipulse.core.config import SourceConfig
from aipulse.core.hashing import canonical_url
from aipulse.core.logging import get_logger
from aipulse.core.timeutil import utcnow
from aipulse.normalize.clean import clean_text, detect_language
from aipulse.schema.items import RawItem, SourceEnum, SourceMetrics
from aipulse.utils.http import HttpClient

from .base import BaseCollector

log = get_logger(__name__)

URL_RE = re.compile(r"https?://[^\s)>\]]+")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_DESC_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]*content=["\'](.*?)["\']',
    re.S | re.I,
)


def parse_inbox_markdown(text: str) -> list[dict[str, str]]:
    """解析 inbox 文本：每行一条，URL 后的同一行内容视为备注。"""
    entries: list[dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = URL_RE.search(line)
        if not match:
            continue
        url = match.group(0).rstrip(".,;")
        note = line.replace(match.group(0), "").strip(" -–—\t")
        entries.append({"url": url, "note": note})
    return entries


def parse_html_meta(html_text: str) -> dict[str, str]:
    """从 HTML 里取 title 与 description（够用即可，不做正文抽取）。"""
    title_match = _TITLE_RE.search(html_text or "")
    desc_match = _DESC_RE.search(html_text or "")
    return {
        "title": clean_text(title_match.group(1)) if title_match else "",
        "description": clean_text(desc_match.group(1)) if desc_match else "",
    }


class InboxCollector(BaseCollector):
    source = SourceEnum.INBOX
    display_name = "手动投喂"

    def __init__(self, cfg: SourceConfig, http: HttpClient, inbox_dir: Path | None = None) -> None:
        super().__init__(cfg, http)
        self.inbox_dir = Path(inbox_dir) if inbox_dir else Path("data/inbox")

    def healthcheck_url(self) -> str | None:
        return None  # 本地源，无需网络探活

    async def fetch(self, since: datetime, until: datetime) -> list[RawItem]:
        if not self.inbox_dir.exists():
            log.info("collector.inbox.no_dir", path=str(self.inbox_dir))
            return []
        items: list[RawItem] = []
        for path in sorted(self.inbox_dir.glob("*.md")):
            entries = parse_inbox_markdown(path.read_text(encoding="utf-8", errors="ignore"))
            for entry in entries:
                item = await self.item_from_url(entry["url"], note=entry["note"])
                if item is not None:
                    items.append(item)
        return [item for item in items if item is not None]

    async def item_from_url(self, url: str, *, note: str = "") -> RawItem | None:
        """抓一个 URL 的标题与摘要，转成 RawItem；抓不到也要保留条目（标题退化为 URL）。"""
        title, summary = "", ""
        try:
            response = await self.http.get(
                url, source=self.source.value, rate_limit=self.cfg.rate_limit
            )
            if response.status_code < 400:
                meta = parse_html_meta(response.text)
                title, summary = meta["title"], meta["description"]
        except httpx.HTTPError as exc:
            log.warning("collector.inbox.fetch_failed", url=url, error=repr(exc))

        if not title:
            title = url
            log.warning("collector.inbox.no_title", url=url)

        return RawItem(
            source=self.source,
            external_id=canonical_url(url),
            title=title,
            url=canonical_url(url),
            summary=summary or note,
            published_at=utcnow(),
            metrics=SourceMetrics(),
            tags=["inbox"],
            language=detect_language(f"{title} {summary}"),
            extra={
                "note": note,  # 使用者自己的观察：简报与推演里按高价值上下文使用
                "source_weight": self.weight,
            },
        )
