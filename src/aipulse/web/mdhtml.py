"""把报告 Markdown 安全地转成 HTML（Web 层只读展示用）。

只支持报告实际用到的语法：H1–H3、引用、表格、列表、行内粗/斜/代码/链接，
以及白名单的 ``<details>`` / ``<summary>`` / ``<sub>`` / ``<br>``。

安全模型：所有文本先 ``html.escape``，输出只由「固定标签串 + 转义文本 +
校验过的 href」组成；模板只对 ``render_md`` 的返回值使用 ``|safe``。
链接 scheme 只允许 http/https/arxiv 与站内锚点，拒绝 javascript:/data:。
"""

from __future__ import annotations

import html
import re
from urllib.parse import urlsplit

MAX_BYTES = 512_000

_ALLOWED_SCHEMES = {"http", "https", "arxiv"}

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_HR = re.compile(r"^-{3,}\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_LIST_UL = re.compile(r"^\s*[-*]\s+(.*)$")
_LIST_OL = re.compile(r"^\s*\d+\.\s+(.*)$")
_DETAILS_OPEN = re.compile(r"^\s*<details(?:\s[^>]*)?>\s*$", re.IGNORECASE)
_DETAILS_CLOSE = re.compile(r"^\s*</details>\s*$", re.IGNORECASE)
_SUMMARY = re.compile(r"^\s*<summary>(.*?)</summary>\s*$", re.IGNORECASE | re.DOTALL)
_SUB = re.compile(r"^\s*<sub>(.*?)</sub>\s*$", re.IGNORECASE | re.DOTALL)
_BR = re.compile(r"&lt;br\s*/?&gt;", re.IGNORECASE)

_CODE_STASH = "\x00{}\x00"
_CODE_STASH_RE = re.compile(r"\x00(\d+)\x00")


def render_md(md: str, *, max_bytes: int = MAX_BYTES) -> str:
    """把受限 Markdown 渲染成 HTML；超长输入按 UTF-8 字节截断。"""
    raw = md.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(_blocks(raw.split("\n")))


def _blocks(lines: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        if _DETAILS_OPEN.match(line):
            out.append("<details>")
            i += 1
            continue
        if _DETAILS_CLOSE.match(line):
            out.append("</details>")
            i += 1
            continue
        m = _SUMMARY.match(line)
        if m:
            out.append(f"<summary>{_inline(m.group(1))}</summary>")
            i += 1
            continue
        m = _SUB.match(line)
        if m:
            out.append(f'<p class="md-sub"><sub>{_inline(m.group(1))}</sub></p>')
            i += 1
            continue

        m = _HEADING.match(line)
        if m:
            level = min(len(m.group(1)), 3)
            out.append(f"<h{level}>{_inline(m.group(2).strip())}</h{level}>")
            i += 1
            continue
        if _HR.match(line):
            out.append("<hr>")
            i += 1
            continue
        if _is_table_start(lines, i):
            table, i = _table(lines, i)
            out.append(table)
            continue
        if line.lstrip().startswith(">"):
            quote, i = _blockquote(lines, i)
            out.append(quote)
            continue
        if _LIST_UL.match(line) or _LIST_OL.match(line):
            lst, i = _list(lines, i)
            out.append(lst)
            continue

        para, i = _paragraph(lines, i)
        out.append(para)
    return out


def _is_table_start(lines: list[str], i: int) -> bool:
    if i + 1 >= len(lines):
        return False
    return "|" in lines[i] and bool(_TABLE_SEP.match(lines[i + 1]))


def _split_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def _table(lines: list[str], i: int) -> tuple[str, int]:
    header = _split_row(lines[i])
    rows: list[list[str]] = []
    j = i + 2
    while j < len(lines) and lines[j].strip().startswith("|"):
        rows.append(_split_row(lines[j]))
        j += 1
    head = "".join(f"<th>{_inline(cell)}</th>" for cell in header)
    body = "".join(
        "<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in row) + "</tr>" for row in rows
    )
    return (
        f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>",
        j,
    )


def _blockquote(lines: list[str], i: int) -> tuple[str, int]:
    inner: list[str] = []
    while i < len(lines) and lines[i].lstrip().startswith(">"):
        text = lines[i].lstrip()[1:]
        inner.append(text[1:] if text.startswith(" ") else text)
        i += 1
    return "<blockquote>\n" + "\n".join(_blocks(inner)) + "\n</blockquote>", i


def _list(lines: list[str], i: int) -> tuple[str, int]:
    ordered = bool(_LIST_OL.match(lines[i]))
    pattern = _LIST_OL if ordered else _LIST_UL
    items: list[str] = []
    while i < len(lines):
        m = pattern.match(lines[i])
        if not m:
            # 允许列表项之间的空行；遇到非列表内容即结束
            if not lines[i].strip() and i + 1 < len(lines) and pattern.match(lines[i + 1]):
                i += 1
                continue
            break
        items.append(_inline(m.group(1).strip()))
        i += 1
    tag = "ol" if ordered else "ul"
    body = "".join(f"<li>{item}</li>" for item in items)
    return f"<{tag}>{body}</{tag}>", i


def _paragraph(lines: list[str], i: int) -> tuple[str, int]:
    parts: list[str] = []
    while i < len(lines):
        line = lines[i]
        if not line.strip() or _starts_block(lines, i):
            break
        parts.append(_inline(line.strip()))
        i += 1
    return "<p>" + "<br>".join(parts) + "</p>", i


def _starts_block(lines: list[str], i: int) -> bool:
    line = lines[i]
    return bool(
        _HEADING.match(line)
        or _HR.match(line)
        or _DETAILS_OPEN.match(line)
        or _DETAILS_CLOSE.match(line)
        or _SUMMARY.match(line)
        or _SUB.match(line)
        or line.lstrip().startswith(">")
        or _LIST_UL.match(line)
        or _LIST_OL.match(line)
        or _is_table_start(lines, i)
    )


def _inline(text: str) -> str:
    out = html.escape(text, quote=False)

    codes: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        codes.append(match.group(1))
        return _CODE_STASH.format(len(codes) - 1)

    out = re.sub(r"`([^`]+)`", _stash, out)

    def _link(match: re.Match[str]) -> str:
        label = match.group(1)
        url = html.unescape(match.group(2)).strip()
        if not _safe_url(url):
            return label
        return f'<a href="{html.escape(url, quote=True)}" rel="noopener noreferrer">{label}</a>'

    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<em>\1</em>", out)
    out = _BR.sub("<br>", out)

    def _restore(match: re.Match[str]) -> str:
        code = html.escape(codes[int(match.group(1))], quote=False)
        return f"<code>{code}</code>"

    return _CODE_STASH_RE.sub(_restore, out)


def _safe_url(url: str) -> bool:
    if not url or any(ord(char) < 32 for char in url):
        return False
    if url.startswith("#") or url.startswith("/"):
        return True
    return urlsplit(url).scheme.lower() in _ALLOWED_SCHEMES
