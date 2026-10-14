"""LLM 响应缓存（设计方案 §8.4）。

缓存键 = sha256(model + messages + response_model_name + temperature)；命中则不计费。
落点在 `store/models.py::LLMCache` 表（prompt_hash PK / prompt / response / model / created_at）。
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import Engine
from sqlmodel import Session

from aipulse.llm.base import ChatMessage
from aipulse.store.models import LLMCache as LLMCacheRow


def cache_key(
    model: str,
    messages: list[ChatMessage],
    *,
    response_model_name: str = "",
    temperature: float = 0.3,
) -> str:
    payload = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "response_model": response_model_name,
        "temperature": temperature,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class LLMCache:
    """基于 llm_cache 表的响应缓存。无 engine 时退化为 no-op（禁用）。"""

    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine

    def get(self, key: str) -> str | None:
        if self.engine is None:
            return None
        with Session(self.engine) as session:
            row = session.get(LLMCacheRow, key)
            return row.response if row is not None else None

    def put(self, key: str, *, prompt: str, response: str, model: str) -> None:
        if self.engine is None:
            return
        with Session(self.engine) as session:
            existing = session.get(LLMCacheRow, key)
            if existing is not None:
                return
            session.add(LLMCacheRow(prompt_hash=key, prompt=prompt, response=response, model=model))
            session.commit()

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"LLMCache(engine={'set' if self.engine else 'none'})"


__all__ = ["LLMCache", "cache_key"]
