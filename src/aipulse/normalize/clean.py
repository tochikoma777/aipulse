"""文本清洗（归一化层 L2 的公共部分）。

所有采集器拿到的 title / summary 都必须先过这里，保证入库文本：
无 HTML 标签、无连续空白、长度可控、带语言标记（供中文 jieba 分词与聚类使用）。
"""

from __future__ import annotations

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\u00a0]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_CJK_RE = re.compile(r"[一-鿿]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def strip_html(text: str) -> str:
    """去 HTML 标签并把实体还原成字符（RSS/Reddit 的正文通常是 HTML）。"""
    if not text:
        return ""
    without_tags = _TAG_RE.sub(" ", text)
    return html.unescape(without_tags)


def normalize_whitespace(text: str) -> str:
    """合并空白与多余空行，去掉首尾空白。"""
    if not text:
        return ""
    collapsed = _WS_RE.sub(" ", text)
    collapsed = _BLANK_LINES_RE.sub("\n\n", collapsed)
    return "\n".join(line.strip() for line in collapsed.split("\n")).strip()


def clean_text(text: str, *, limit: int | None = None) -> str:
    """清洗流水线：去标签 → 规整空白 → 可选截断。"""
    cleaned = normalize_whitespace(strip_html(text))
    if limit is not None and len(cleaned) > limit:
        return truncate(cleaned, limit)
    return cleaned


def truncate(text: str, limit: int, suffix: str = "…") -> str:
    """按字符截断（中文按字符计），留出省略号位置。"""
    if len(text) <= limit:
        return text
    keep = max(0, limit - len(suffix))
    return text[:keep].rstrip() + suffix


def detect_language(text: str) -> str | None:
    """简易语言检测：只区分 zh / en / None。

    不上第三方库是因为这里只需要二分类——中日韩字符占比足够判定，
    而韩文日文混排的情况在 V1 数据源里基本不存在。
    """
    if not text:
        return None
    cjk = len(_CJK_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    if cjk == 0 and latin == 0:
        return None
    # 汉字出现即判中文（中英混排的技术文章也按中文处理，便于 jieba 分词）
    return "zh" if cjk >= max(2, latin * 0.1) else "en"
