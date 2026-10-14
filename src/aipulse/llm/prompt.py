"""Prompt 加载器（设计方案 §8.5）。

所有 prompt 外置于 `prompts/**.j2`，头部含 YAML front-matter：
    ---
    version: 1
    model_tier: strong       # fast | strong
    temperature: 0.4
    purpose: predict_generate
    ---
`prompt_version` = 文件全文的 sha256 前 8 位，随预言/简报入库，便于分析
"换了 prompt 之后命中率有没有变"。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from aipulse.core.config import project_root

_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@dataclass
class PromptTemplate:
    name: str
    version: int
    model_tier: str  # fast | strong
    temperature: float
    purpose: str
    body: str
    version_hash: str  # 文件全文 sha256 前 8 位


def prompts_dir() -> Path:
    return project_root() / "prompts"


def _parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        raise ValueError("prompt 文件缺少 front-matter（--- 包裹的 YAML 头）")
    meta = yaml.safe_load(match.group(1)) or {}
    return meta, text[match.end() :]


def load_prompt(name: str) -> PromptTemplate:
    """按相对路径加载 prompt，如 `brief/daily_brief`（自动补 .j2）。"""
    path = prompts_dir() / f"{name}.j2"
    raw = path.read_text(encoding="utf-8")
    meta, body = _parse_front_matter(raw)
    version_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return PromptTemplate(
        name=name,
        version=int(meta.get("version", 1)),
        model_tier=str(meta.get("model_tier", "fast")),
        temperature=float(meta.get("temperature", 0.4)),
        purpose=str(meta.get("purpose", name.replace("/", "_"))),
        body=body,
        version_hash=version_hash,
    )


def render_prompt(name: str, **variables: Any) -> tuple[str, PromptTemplate]:
    """渲染 prompt 正文，返回 (渲染后文本, 模板元信息)。"""
    template = load_prompt(name)
    env = Environment(
        loader=FileSystemLoader(prompts_dir()),
        undefined=StrictUndefined,  # 缺变量立刻报错，而不是静默渲染成空
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    body = env.from_string(template.body).render(**variables)
    return body, template


__all__ = ["PromptTemplate", "load_prompt", "prompts_dir", "render_prompt"]
