"""数据源探测（M0 必跑）。

用真实请求探测每一个数据源，打印响应结构样例，并把原始响应落盘到 `tests/fixtures/`。
**失败的源必须明确记录 HTTP 状态 / 异常类型与错误信息，不允许静默跳过。**

用法：
    uv run python scripts/probe_sources.py
    uv run python scripts/probe_sources.py --no-cache      # 不用 SQLite 响应缓存
    uv run python scripts/probe_sources.py --only rss      # 只探测 RSS feed
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import feedparser
import httpx
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aipulse.core.config import load_settings, load_sources, project_root  # noqa: E402
from aipulse.core.timeutil import utcnow  # noqa: E402
from aipulse.utils.http import HttpClient  # noqa: E402

console = Console()

FIXTURES = project_root() / "tests" / "fixtures"

# ── 5 个 API 类源的探测目标 ────────────────────────────────────────────
API_TARGETS: list[dict[str, str]] = [
    {
        "name": "github_trending",
        "url": "https://github.com/trending?since=daily",
        "fixture": "github_trending.html",
        "rate_limit": "1/6h",
        # 该环境偶发返回损坏的 gzip，明确要求不压缩以提高探测成功率
        "headers": {"Accept-Encoding": "identity"},
    },
    {
        "name": "arxiv",
        "url": (
            "https://export.arxiv.org/api/query"
            "?search_query=cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL"
            "&sortBy=submittedDate&sortOrder=descending&max_results=20"
        ),
        "fixture": "arxiv_atom.xml",
        "rate_limit": "3/s",
    },
    {
        "name": "hf_papers",
        "url": "https://huggingface.co/api/daily_papers",
        # 备用端点：仅当主端点在当前网络不可达时使用（数据结构与官方 API 一致）
        "fallback_url": "https://hf-mirror.com/api/daily_papers",
        "fixture": "hf_daily_papers.json",
        "rate_limit": "1/1s",
    },
    {
        "name": "hackernews",
        "url": (
            "https://hn.algolia.com/api/v1/search_by_date"
            "?query=AI&tags=story&numericFilters=created_at_i>1735689600&hitsPerPage=20"
        ),
        "fixture": "hn_search.json",
        "rate_limit": "10/1s",
    },
    {
        "name": "reddit",
        "url": "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day",
        "fixture": "reddit_top.json",
        "rate_limit": "1/2s",
    },
]


@dataclass
class ProbeResult:
    name: str
    url: str
    kind: str  # api / rss
    status: int | None = None
    error: str | None = None
    entries: int | None = None
    has_content: bool | None = None
    updated: str | None = None
    size_bytes: int = 0
    fields: list[str] = field(default_factory=list)
    sample: list[dict[str, Any]] = field(default_factory=list)
    fixture: str | None = None
    note: str = ""
    conclusion: str = ""

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300 and not self.error


# ── 各源的"关键字段"抽取（仅用于探测报告，不是采集器解析逻辑）──────────


def _probe_github_trending(text: str) -> tuple[int, list[str], list[dict[str, Any]]]:
    # 只用稳定结构：article 容器 + <a href="/owner/repo">
    repos = re.findall(r'<h2[^>]*>\s*<a[^>]+href="/([\w.\-]+/[\w.\-]+)"', text)
    articles = len(re.findall(r"<article\b", text))
    sample = [{"repo": r} for r in repos[:2]]
    return (len(repos) or articles), ["repo(h2>a[href])", "article_count"], sample


def _probe_arxiv(text: str) -> tuple[int, list[str], list[dict[str, Any]]]:
    feed = feedparser.parse(text)
    entries = list(feed.entries)
    sample = [
        {
            "id": e.get("id", "")[:60],
            "title": (e.get("title") or "").replace("\n", " ")[:70],
            "published": e.get("published", ""),
            "authors": [a.get("name") for a in e.get("authors", [])][:2],
            "categories": [t.get("term") for t in e.get("tags", [])],
        }
        for e in entries[:2]
    ]
    fields = [
        "id",
        "title",
        "summary",
        "published",
        "updated",
        "authors[].name",
        "tags[].term",
        "link",
    ]
    return len(entries), fields, sample


def _probe_hf(text: str) -> tuple[int, list[str], list[dict[str, Any]]]:
    data = json.loads(text)
    items = data if isinstance(data, list) else data.get("items", data.get("data", []))
    if isinstance(items, dict):
        items = [items]
    sample = []
    for item in list(items)[:2]:
        paper = (item or {}).get("paper") or item or {}
        sample.append(
            {
                "id": item.get("id") or paper.get("id"),
                "title": (paper.get("title") or item.get("title") or "")[:70],
                "upvotes": item.get("upvotes", paper.get("upvotes")),
                "publishedAt": item.get("publishedAt") or paper.get("publishedAt"),
                "paper.id": paper.get("id"),
            }
        )
    fields = ["id", "title", "paper{id,title,summary,upvotes}", "publishedAt", "upvotes"]
    return len(items), fields, sample


def _probe_hn(text: str) -> tuple[int, list[str], list[dict[str, Any]]]:
    data = json.loads(text)
    hits = data.get("hits", [])
    sample = [
        {
            "objectID": h.get("objectID"),
            "title": (h.get("title") or "")[:70],
            "url": (h.get("url") or "")[:60],
            "author": h.get("author"),
            "points": h.get("points"),
            "num_comments": h.get("num_comments"),
            "created_at": h.get("created_at"),
        }
        for h in hits[:2]
    ]
    fields = [
        "objectID",
        "title",
        "url",
        "author",
        "points",
        "num_comments",
        "created_at",
        "created_at_i",
        "story_text",
    ]
    return len(hits), fields, sample


def _probe_reddit(text: str) -> tuple[int, list[str], list[dict[str, Any]]]:
    feed = feedparser.parse(text)
    entries = list(feed.entries)
    sample = [
        {
            "id": e.get("id"),
            "title": (e.get("title") or "")[:70],
            "link": (e.get("link") or "")[:60],
            "published": e.get("published", ""),
            "author": e.get("author"),
            "content_len": len(e.get("content", [{}])[0].get("value", "") or e.get("summary", "")),
        }
        for e in entries[:2]
    ]
    fields = [
        "id",
        "title",
        "link",
        "published",
        "author",
        "content(HTML)",
        "（RSS 无 score 字段）",
    ]
    return len(entries), fields, sample


def _probe_feed(text: str) -> tuple[int, list[str], list[dict[str, Any]], bool, str]:
    """RSS/Atom 通用探测：条数、字段、是否含正文、最后更新时间。"""
    feed = feedparser.parse(text)
    entries = list(feed.entries)
    sample = [
        {
            "title": (e.get("title") or "")[:70],
            "link": (e.get("link") or "")[:60],
            "published": e.get("published") or e.get("updated") or "",
            "author": e.get("author"),
            "summary_len": len(e.get("summary", "") or ""),
            "content_len": len((e.get("content") or [{}])[0].get("value", "") or ""),
        }
        for e in entries[:2]
    ]
    fields = ["title", "link", "published/updated", "author", "summary", "content(可选)"]
    has_content = bool(entries) and any(
        (e.get("content") or [{}])[0].get("value") or len(e.get("summary", "") or "") > 300
        for e in entries
    )
    updated = ""
    for candidate in (feed.feed.get("updated"), feed.feed.get("published")):
        if candidate:
            updated = candidate
            break
    if not updated and entries:
        updated = entries[0].get("published") or entries[0].get("updated") or ""
    return len(entries), fields, sample, has_content, updated


_EXTRACTORS = {
    "github_trending": _probe_github_trending,
    "arxiv": _probe_arxiv,
    "hf_papers": _probe_hf,
    "hackernews": _probe_hn,
    "reddit": _probe_reddit,
}


def _pretty_json(obj: Any, limit: int = 400) -> str:
    text = json.dumps(obj, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


async def probe_api(
    client: HttpClient, target: dict[str, str], out_dir: Path, *, retries: int = 4
) -> ProbeResult:
    name = target["name"]
    result = ProbeResult(name=name, url=target["url"], kind="api", fixture=target["fixture"])
    # 主端点失败（异常或非 2xx）时依次退到备用端点，保证"尽力拿到真实数据 + 说清来源"
    urls = [target["url"]]
    if target.get("fallback_url"):
        urls.append(target["fallback_url"])

    response: httpx.Response | None = None
    for index, url in enumerate(urls):
        try:
            response = await client.get(
                url,
                source=name,
                rate_limit=target.get("rate_limit"),
                headers=target.get("headers"),
                max_retries=retries,
            )
        except Exception as exc:  # 网络层异常：记录后换下一个端点
            result.error = f"{type(exc).__name__}: {exc}"
            continue
        if 200 <= response.status_code < 300:
            if index > 0:
                result.url = url
                result.note = "备用端点（主端点在本环境不可达，schema 与官方一致）"
                result.error = None
                console.print(f"[yellow]{name} 改用备用端点：{url}[/yellow]")
            break
        result.error = f"HTTP {response.status_code}"
        response = None

    try:
        if response is None:
            raise httpx.HTTPError(result.error or "无可用响应")
        result.status = response.status_code
        result.size_bytes = len(response.content)
        text = response.text
        if 200 <= response.status_code < 300:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / target["fixture"]).write_bytes(response.content)
            try:
                extractor = _EXTRACTORS[name]
                if name == "reddit":
                    n, fields_, sample = _probe_reddit(text)
                    result.has_content = bool(sample and sample[0].get("content_len", 0) > 200)
                else:
                    n, fields_, sample = extractor(text)  # type: ignore[operator]
                result.entries = n
                result.fields = fields_
                result.sample = sample
            except Exception as exc:  # 解析失败不算源失败，但必须暴露
                result.error = f"响应已保存但字段抽取失败：{type(exc).__name__}: {exc}"
        else:
            result.error = f"HTTP {response.status_code}"
        result.conclusion = "可用" if result.ok else "不可用（详见手册）"
    except httpx.HTTPError as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.conclusion = "不可用（网络层失败）"
    except Exception as exc:  # 兜底：任何异常都必须被记录，不允许静默
        result.error = f"{type(exc).__name__}: {exc}"
        result.conclusion = "不可用（未知异常）"
    return result


async def probe_rss(
    client: HttpClient, feed_name: str, url: str, tier: str, out_dir: Path, *, retries: int = 4
) -> ProbeResult:
    result = ProbeResult(name=feed_name, url=url, kind="rss")
    try:
        response = await client.get(
            url,
            source="rss",
            rate_limit="1/1s",
            # 同 github_trending：该环境偶发返回损坏的 gzip，明确要求不压缩
            headers={"Accept-Encoding": "identity"},
            max_retries=retries,
        )
        result.status = response.status_code
        result.size_bytes = len(response.content)
        if 200 <= response.status_code < 300:
            text = response.text
            entries, fields_, sample, has_content, updated = _probe_feed(text)
            result.entries = entries
            result.fields = fields_
            result.sample = sample
            result.has_content = has_content
            result.updated = updated
            result.conclusion = "可用" if entries > 0 else "不可用（feed 解析出 0 条）"
            if entries > 0:
                out_dir.mkdir(parents=True, exist_ok=True)
                fixture_path = out_dir / _fixture_name(feed_name, tier)
                # 每档只保留第一个成功 feed 的快照（英/中各一份），避免被后面的源覆盖
                if not fixture_path.exists():
                    fixture_path.write_bytes(response.content)
                result.fixture = _fixture_name(feed_name, tier)
        else:
            result.error = f"HTTP {response.status_code}"
            result.conclusion = "替换" if tier == "core" else "删除/保留为 optional"
    except httpx.HTTPError as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.conclusion = "替换" if tier == "core" else "删除/保留为 optional"
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.conclusion = "替换" if tier == "core" else "删除/保留为 optional"
    return result


def _fixture_name(feed_name: str, tier: str) -> str:
    """英文主干存 rss_feed.xml，中文源存 rss_feed_zh.xml（M0 要求各留 1 份真实快照）。"""
    return "rss_feed.xml" if tier == "core" else "rss_feed_zh.xml"


def _print_api_table(results: list[ProbeResult]) -> None:
    table = Table(title="API 类数据源探测", header_style="bold cyan")
    table.add_column("源")
    table.add_column("HTTP", justify="center")
    table.add_column("条数", justify="right")
    table.add_column("字节", justify="right")
    table.add_column("关键字段")
    for r in results:
        status = str(r.status) if r.status is not None else "—"
        table.add_row(
            r.name,
            f"[green]{status}[/green]" if r.ok else f"[red]{status}[/red]",
            str(r.entries) if r.entries is not None else "—",
            f"{r.size_bytes}",
            ", ".join(r.fields[:6]) if r.fields else (r.error or "—"),
        )
    console.print(table)
    for r in results:
        if r.error:
            console.print(f"[red]✗ {r.name}[/red] {r.url}\n  {r.error}")
        if r.sample:
            console.print(f"[cyan]样本 · {r.name}[/cyan]")
            for i, item in enumerate(r.sample, 1):
                console.print(f"  [{i}] {_pretty_json(item)}")


def _print_rss_table(results: list[ProbeResult]) -> None:
    table = Table(title="RSS feed 逐个探测（v1.2 重点）", header_style="bold cyan")
    table.add_column("feed")
    table.add_column("URL")
    table.add_column("HTTP", justify="center")
    table.add_column("条数", justify="right")
    table.add_column("含正文", justify="center")
    table.add_column("最后更新")
    table.add_column("结论")
    for r in results:
        status = str(r.status) if r.status is not None else "—"
        table.add_row(
            r.name,
            r.url if len(r.url) <= 60 else r.url[:57] + "…",
            f"[green]{status}[/green]" if r.ok else f"[red]{status}[/red]",
            str(r.entries) if r.entries is not None else "—",
            "是" if r.has_content else ("否" if r.has_content is False else "—"),
            (r.updated or "—")[:25],
            r.conclusion or "—",
        )
    console.print(table)
    for r in results:
        if r.error:
            console.print(f"[red]✗ {r.name}[/red] {r.url}\n  {r.error}")


async def main_async(args: argparse.Namespace) -> int:
    settings = load_settings()
    out_dir = Path(args.out) if args.out else FIXTURES
    out_dir.mkdir(parents=True, exist_ok=True)

    cache_path = None if args.no_cache else settings.cache_path() / "http.sqlite"
    client = HttpClient(
        connect_timeout_s=float(args.connect_timeout),
        read_timeout_s=float(args.timeout),
        max_retries=args.retries,
        cache_enabled=not args.no_cache,
        cache_path=cache_path,
        cache_ttl_s=settings.http.cache_ttl_s,
        user_agent=settings.http.user_agent,
    )

    results: list[ProbeResult] = []
    try:
        if args.only in ("all", "api"):
            api_results = [
                await probe_api(client, t, out_dir, retries=args.retries) for t in API_TARGETS
            ]
            _print_api_table(api_results)
            results.extend(api_results)
        if args.only in ("all", "rss"):
            sources = load_sources().sources
            feeds = sources.get("rss").feeds if sources.get("rss") else []
            rss_results = [
                await probe_rss(client, f.name, f.url, f.tier, out_dir, retries=args.retries)
                for f in feeds
            ]
            _print_rss_table(rss_results)
            results.extend(rss_results)
    finally:
        await client.aclose()

    report = {
        "probed_at": utcnow().isoformat(),
        "python": sys.version.split()[0],
        "proxy": __import__("os").environ.get("HTTPS_PROXY")
        or __import__("os").environ.get("HTTP_PROXY"),
        "results": [asdict(r) for r in results],
    }
    (out_dir / "probe_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    console.print(f"\n[dim]探测报告已写入 {out_dir / 'probe_report.json'}[/dim]")

    failed = [r for r in results if not r.ok]
    if failed:
        console.print(
            f"[yellow]{len(failed)}/{len(results)} 个源探测失败，"
            f"原因见上表与 docs/数据源手册.md[/yellow]"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="探测全部数据源并保存真实响应快照")
    parser.add_argument("--no-cache", action="store_true", help="禁用 SQLite 响应缓存")
    parser.add_argument("--timeout", type=float, default=30.0, help="读取超时（秒）")
    parser.add_argument("--connect-timeout", type=float, default=10.0, help="连接超时（秒）")
    parser.add_argument("--retries", type=int, default=4, help="每源最大尝试次数")
    parser.add_argument("--only", choices=["all", "api", "rss"], default="all")
    parser.add_argument("--out", type=str, default=None, help="fixtures 输出目录")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
