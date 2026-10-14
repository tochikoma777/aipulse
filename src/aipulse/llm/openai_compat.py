"""OpenAI 兼容协议的 LLM 客户端（设计方案 §8.2）。

默认厂商 DeepSeek（`deepseek-chat` fast / `deepseek-reasoner` strong），换厂商只改
环境变量 `AIPULSE_LLM__BASE_URL` / `AIPULSE_LLM__API_KEY`，不改代码。

职责：把 `LLMClient.chat()` 翻译成官方 openai SDK 调用，并接入缓存 / 预算 / 用量记账。
结构化 JSON 输出：优先 `response_format={"type":"json_schema"}`，`llm.json_schema=false`
时降级为 `json_object` + 把 schema 内嵌进 system prompt（§8.3）。
"""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from aipulse.core.config import LLMSettings
from aipulse.core.errors import LLMError
from aipulse.core.logging import get_logger
from aipulse.llm.base import ChatMessage, LLMResult
from aipulse.llm.budget import BudgetTracker
from aipulse.llm.cache import LLMCache, cache_key

log = get_logger(__name__)


def _json_schema_name(schema: dict[str, Any] | None) -> str:
    """从 JSON Schema 取一个稳定的 name（response_format 需要；用 title 兜底）。"""
    if not schema:
        return "response"
    return str(schema.get("title") or "response").replace(" ", "_")


class OpenAICompatClient:
    def __init__(
        self,
        llm_settings: LLMSettings,
        *,
        engine: Any | None = None,
        cache: LLMCache | None = None,
        budget: BudgetTracker | None = None,
    ) -> None:
        self.settings = llm_settings
        base_url = (llm_settings.base_url or "").strip()
        api_key = (llm_settings.api_key or "").strip()
        if not base_url or not api_key:
            # 理论上传入前已由 build_client 依据 effective_mode 拦截；这里再兜底一次
            raise LLMError("LLM base_url / api_key 未配置，无法构造 OpenAI 兼容客户端")
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=llm_settings.timeout_s,
            max_retries=llm_settings.max_retries,
        )
        self.use_json_schema = bool(getattr(llm_settings, "json_schema", True))
        # 缓存/预算均为可选注入；未注入时退化为直连（测试/最小可用）
        self.cache = (
            cache
            if cache is not None
            else (LLMCache(engine) if llm_settings.cache_enabled else None)
        )
        self.budget = budget

    def _model(self, model_tier: str) -> str:
        return self.settings.strong_model if model_tier == "strong" else self.settings.fast_model

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int = 2000,
        purpose: str = "general",
        model_tier: str = "fast",
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        model = self._model(model_tier)

        # ── 缓存命中：不计费 ──────────────────────────────────────
        key = cache_key(
            model,
            messages,
            response_model_name=_json_schema_name(json_schema) if json_schema else "",
            temperature=temperature,
        )
        if self.cache is not None:
            cached = self.cache.get(key)
            if cached is not None:
                log.debug("llm.cache.hit", purpose=purpose, model=model)
                self._record_usage(purpose, model, model_tier, 0, 0, cache_hit=True)
                return LLMResult(content=cached, model=model, cached=True)

        # ── 预算护栏 ──────────────────────────────────────────────
        if self.budget is not None and not self.budget.can_afford(purpose):
            raise LLMError(f"超出每日预算（{purpose}），已降级")

        payload: list[dict[str, str]] = [{"role": m.role, "content": m.content} for m in messages]
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": payload,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_schema is not None:
            if self.use_json_schema:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": _json_schema_name(json_schema), "schema": json_schema},
                }
            else:
                # json_object 降级：schema 内嵌进 system prompt，模型自约束输出纯 JSON
                kwargs["response_format"] = {"type": "json_object"}
                schema_text = json.dumps(json_schema, ensure_ascii=False)
                payload = [
                    *payload,
                    {
                        "role": "system",
                        "content": f"你必须只输出符合以下 JSON Schema 的 JSON：{schema_text}",
                    },
                ]
                kwargs["messages"] = payload

        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # 网络/限流/厂商报错：交给上层降级，不中断流水线
            log.warning("llm.request_failed", purpose=purpose, model=model, error=repr(exc))
            raise LLMError(f"LLM 调用失败（{purpose}）：{type(exc).__name__}: {exc}") from exc

        choice = resp.choices[0] if resp.choices else None
        content = (choice.message.content if choice and choice.message else "") or ""
        usage = resp.usage
        prompt_tokens = int(usage.prompt_tokens) if usage else 0
        completion_tokens = int(usage.completion_tokens) if usage else 0

        if json_schema is not None and self.cache is not None and content:
            self.cache.put(
                key, prompt=json.dumps(payload, ensure_ascii=False), response=content, model=model
            )
        self._record_usage(purpose, model, model_tier, prompt_tokens, completion_tokens)
        return LLMResult(
            content=content,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def _record_usage(
        self,
        purpose: str,
        model: str,
        model_tier: str,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        cache_hit: bool = False,
    ) -> None:
        if self.budget is not None:
            self.budget.record(
                purpose=purpose,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model_tier=model_tier,
                cache_hit=cache_hit,
            )


__all__ = ["OpenAICompatClient"]
