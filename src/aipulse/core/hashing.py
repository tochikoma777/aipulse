"""指纹与 URL 规范化。

去重分三级：L1 精确（content_hash）、L2 跨源（cross_source_key）、
L3 近似（simhash64 + 汉明距离）。本模块只提供纯函数，便于单测。
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# 追踪参数：去掉它们才能让"同一篇文章的多个分享链接"归一到同一条
_TRACKING_PREFIXES = ("utm_", "share_", "spm", "at_")
_TRACKING_EXACT = {
    "ref",
    "source",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "s_cid",
    "utm",
    "from",
    "spm",
}
_DEFAULT_PORTS = {"http": 80, "https": 443}

_ARXIV_RE = re.compile(r"^/(?:abs|pdf|html|format|eprint)/(?P<aid>\d{4}\.\d{4,5})(?:\.pdf|v\d+)?$")
_ARXIV_ID_RE = re.compile(r"^(?P<aid>\d{4}\.\d{4,5})(?:v\d+)?$")
_HF_PAPER_RE = re.compile(r"^/papers/(?P<aid>\d{4}\.\d{4,5})$")

_CJK_RE = re.compile(r"[一-鿿]+")
_WORD_RE = re.compile(r"[a-z0-9]+")


def _is_tracking(key: str) -> bool:
    low = key.lower()
    return low in _TRACKING_EXACT or low.startswith(_TRACKING_PREFIXES)


def canonical_url(url: str) -> str:
    """URL 规范化：小写 scheme/host、去默认端口、去末尾斜杠、剔除追踪参数。

    对 arXiv / HF Papers 做跨源等价映射，统一成 `arxiv:{id}`——这是
    arXiv 与 HuggingFace Daily Papers 能合并成一条 Item 的前提。
    """
    raw = url.strip()
    if not raw:
        return ""
    # 已是规范形态（如 arxiv:2501.12345）或不是 URL 时原样返回
    if "://" not in raw:
        return raw

    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        return raw

    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host if port in (None, _DEFAULT_PORTS[scheme]) else f"{host}:{port}"

    path = parts.path
    # 论文类 URL：无论来自 arxiv.org 还是 huggingface.co，都归一到 arxiv:{id}
    if host.endswith("arxiv.org"):
        match = _ARXIV_RE.match(path)
        if match:
            return f"arxiv:{match.group('aid')}"
    if host.endswith("huggingface.co"):
        match = _HF_PAPER_RE.match(path)
        if match:
            return f"arxiv:{match.group('aid')}"

    if path.endswith("/") and len(path) > 1:
        path = path.rstrip("/")

    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)],
        doseq=True,
    )
    return urlunsplit((scheme, netloc, path, query, ""))


def arxiv_id(url_or_id: str) -> str | None:
    """从 URL 或裸 id 中提取 arXiv 编号（含版本号时剥离）。"""
    text = url_or_id.strip()
    match = _ARXIV_ID_RE.match(text)
    if match:
        return match.group("aid")
    canonical = canonical_url(text)
    if canonical.startswith("arxiv:"):
        return canonical.split(":", 1)[1]
    match = re.search(r"(\d{4}\.\d{4,5})", text)
    return match.group(1) if match else None


def cross_source_key(url: str) -> str | None:
    """跨源去重键：论文 → `arxiv:{id}`，仓库 → `repo:{owner/name}`。"""
    canonical = canonical_url(url)
    if canonical.startswith("arxiv:"):
        return canonical
    parts = urlsplit(canonical if "://" in canonical else f"https://{canonical}")
    if parts.netloc.endswith("github.com"):
        segments = [s for s in parts.path.split("/") if s]
        if len(segments) >= 2:
            return f"repo:{segments[0]}/{segments[1].removesuffix('.git')}"
    return None


def content_hash(*parts: str) -> str:
    """L1 精确去重指纹：`sha1(canonical_url + source)`。"""
    digest = hashlib.sha1("|".join(parts).encode("utf-8"))
    return digest.hexdigest()


def short_hash(text: str, length: int = 8) -> str:
    """短哈希（prompt_version / 缓存键等展示用）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def _tokens(text: str) -> list[str]:
    """分词：英文按词，中文按 bigram。

    中文必须切成 bigram——整句当成一个 token 会让 SimHash 对"换了两个字的标题"
    完全不敏感，而按单字切又会让无关文本偶然相似。bigram 是精度/召回的折中。
    """
    low = text.lower()
    tokens: list[str] = list(_WORD_RE.findall(low))
    for segment in _CJK_RE.findall(low):
        if len(segment) == 1:
            tokens.append(segment)
        else:
            tokens.extend(segment[i : i + 2] for i in range(len(segment) - 1))
    return tokens


def simhash64(text: str) -> int:
    """64 位 SimHash 指纹（L3 近似去重用）。

    算法：每个 token 取 64 位哈希，按位累加 +1/-1，最终每位取符号。
    相似文本的汉明距离小，可在 O(1) 内比较。
    """
    tokens = _tokens(text or "")
    if not tokens:
        return 0
    counters = [0] * 64
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for i in range(64):
            counters[i] += 1 if (value >> i) & 1 else -1
    fingerprint = 0
    for i, counter in enumerate(counters):
        if counter > 0:
            fingerprint |= 1 << i
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    """两个 SimHash 的汉明距离（≤3 视为同一事件）。"""
    return (a ^ b).bit_count()
