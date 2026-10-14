"""文本工具：token 粗估与摘要截断（设计方案 §8.5.3 / M2 约束）。

不引入 tiktoken 等重依赖——LLM 上下文控制只需要一个**保守**的粗估：
宁可多算几个 token 把上下文压得更短，也不要低估导致超限。
"""

from __future__ import annotations

import math
import re

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

# 保守折算：非中文按约 3.5 字符/token 计（英文单词平均 4 字符，再留余量）；
# 中文按 1 字 1 token（DeepSeek 中文 tokenizer 通常 1 汉字 ≈ 1 token，取 1 偏保守）。
_LATIN_CHARS_PER_TOKEN = 3.5


def estimate_tokens(text: str) -> int:
    """粗估一段文本的 token 数（保守上界，用于预算控制，不做精确计量）。"""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    return cjk + math.ceil(other / _LATIN_CHARS_PER_TOKEN)


def truncate_summary(text: str, limit: int = 300) -> str:
    """按字符截断摘要（中文按字符计），留出省略号位置。

    与 `normalize/clean.py::truncate` 语义一致，独立实现避免分析层反向依赖归一化层。
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    keep = max(0, limit - 1)
    return text[:keep].rstrip() + "…"


def fits_token_budget(parts: list[str], budget: int = 12000) -> tuple[bool, int]:
    """判断一组文本片段合计是否在 token 预算内；返回 (是否超限, 估算 token 数)。"""
    total = sum(estimate_tokens(p) for p in parts)
    return total <= budget, total
