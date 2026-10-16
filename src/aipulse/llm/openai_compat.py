"""OpenAI 兼容协议的 LLM 客户端（设计方案 §8.2，v1.7 改为 httpx 直连）。

默认厂商 DeepSeek（`deepseek-chat` fast / `deepseek-reasoner` strong），换厂商只改
环境变量 `AIPULSE_LLM__BASE_URL` / `AIPULSE_LLM__API_KEY`，不改代码。

v1.7 变更（★）：
- **移除 `openai` SDK**，改用项目自带的 `HttpClient`（httpx）直连
  `POST {base_url}/chat/completions`。理由：openai 3.x 自带 httpx 2.x，与项目 httpx 冲突，
  且导致 `respx` 无法 mock。
- **json_schema 运行时自动降级**（§8.3）：`llm.json_schema=auto` 时首次带 json_schema，
  收到 400 且错误体含 json_schema / response_format / unsupported 等关键词 → 自动改用
  json_object + prompt 内嵌 schema 重试，并进程内记住"该模型不支持"，后续直接走 json_object。

错误分类：
- 401/403 → `ConfigError`（立即失败、不重试，提示检查 key）
- 429/5xx/超时 → 由 HttpClient 的 tenacity 退避重试
- 其余 4xx → 记录并降级（抛 `LLMError`，调用方降级跳过）
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from aipulse.core.config import LLMSettings
from aipulse.core.errors import ConfigError, LLMError
from aipulse.core.logging import get_logger
from aipulse.llm.base import ChatMessage, LLMResult
from aipulse.llm.budget import BudgetTracker
from aipulse.llm.cache import LLMCache, cache_key
from aipulse.utils.http import HttpClient

log = get_logger(__name__)

# 进程内"该模型是否支持 json_schema"的记忆（auto 模式用，避免每次重启重探/每次白试一次）
_JSON_SCHEMA_SUPPORT: dict[str, bool] = {}

# json_schema 不支持时的错误体关键词（§8.3 判定依据）
_JSON_SCHEMA_UNSUPPORTED_KEYWORDS = ("json_schema", "response_format", "unsupported", "not support")


def json_schema_support(model: str) -> bool | None:
    """模型是否支持 json_schema（None 表示尚无记忆，应尝试）。"""
    return _JSON_SCHEMA_SUPPORT.get(model)


def remember_json_schema_support(model: str, supported: bool) -> None:
    """进程内记住探测结果。"""
    _JSON_SCHEMA_SUPPORT[model] = supported


def reset_json_schema_memory() -> None:
    """清空进程内记忆（测试用）。"""
    _JSON_SCHEMA_SUPPORT.clear()


def _json_schema_name(schema: dict[str, Any] | None) -> str:
    """从 JSON Schema 取一个稳定的 name（response_format 需要；用 title 兜底）。"""
    if not schema:
        return "response"
    return str(schema.get("title") or "response").replace(" ", "_")


def _error_text(response: Any) -> str:
    """把错误响应体压成一段可读文本，供"是否 json_schema 不支持"的判定与日志。"""
    try:
        data = response.json()
    except Exception:  # noqa: BLE001 - 非 JSON 错误体按纯文本处理
        return (response.text or "").strip()
    return json.dumps(data, ensure_ascii=False)


def _is_json_schema_unsupported(response: Any) -> bool:
    """HTTP 400 且错误体含 json_schema 相关关键词 → 判定为"不支持 json_schema"。"""
    text = _error_text(response).lower()
    return any(kw in text for kw in _JSON_SCHEMA_UNSUPPORTED_KEYWORDS)


class OpenAICompatClient:
    def __init__(
        self,
        llm_settings: LLMSettings,
        *,
        engine: Any | None = None,
        cache: LLMCache | None = None,
        budget: BudgetTracker | None = None,
        http: HttpClient | None = None,
    ) -> None:
        self.settings = llm_settings
        base_url = (llm_settings.base_url or "").strip()
        api_key = (llm_settings.api_key or "").strip()
        if not base_url or not api_key:
            # 理论上传入前已由 build_client 依据 effective_mode 拦截；这里再兜底一次
            raise ConfigError("LLM base_url / api_key 未配置，无法构造 OpenAI 兼容客户端")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.json_schema_mode: str = llm_settings.json_schema  # auto | true | false

        # 缓存/预算均为可选注入；未注入时退化为直连（测试/最小可用）
        self.cache = (
            cache
            if cache is not None
            else (LLMCache(engine) if llm_settings.cache_enabled else None)
        )
        self.budget = budget

        # 必须走 HttpClient（复用限速/重试/缓存/代理/UA），不得裸建 httpx 客户端。
        # LLM 响应不走 HTTP 层缓存（另有 llm_cache 表），故 cache_enabled 恒为 False。
        if http is not None:
            self._http = http
            self._owns_http = False
        else:
            self._http = HttpClient(cache_enabled=False)
            self._owns_http = True

    def _model(self, model_tier: str) -> str:
        return self.settings.strong_model if model_tier == "strong" else self.settings.fast_model

    def _endpoint(self) -> str:
        return f"{self._base_url}/chat/completions"

    def _decide_use_schema(self, model: str, wants_schema: bool) -> bool:
        if not wants_schema:
            return False
        if self.json_schema_mode == "true":
            return True
        if self.json_schema_mode == "false":
            return False
        # auto：按进程内记忆决定，无记忆时默认先试 json_schema
        return _JSON_SCHEMA_SUPPORT.get(model, True)

    def _build_body(
        self,
        payload: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
        use_schema: bool,
    ) -> dict[str, Any]:
        messages = [dict(m) for m in payload]
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_schema is not None:
            if use_schema:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": _json_schema_name(json_schema), "schema": json_schema},
                }
            else:
                # json_object 降级：schema 内嵌进 system prompt，模型自约束输出纯 JSON
                body["response_format"] = {"type": "json_object"}
                schema_text = json.dumps(json_schema, ensure_ascii=False)
                body["messages"] = [
                    *messages,
                    {
                        "role": "system",
                        "content": f"你必须只输出符合以下 JSON Schema 的 JSON：{schema_text}",
                    },
                ]
        return body

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _parse_success(data: dict[str, Any]) -> tuple[str, int, int]:
        choices = data.get("choices") or []
        content = ""
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content") or ""
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        return content, prompt_tokens, completion_tokens

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
        payload = [{"role": m.role, "content": m.content} for m in messages]
        wants_schema = json_schema is not None
        use_schema = self._decide_use_schema(model, wants_schema)
        error_note: str | None = None
        # ★ 读超时必须显式传：不传就会吃 HttpClient 的默认 20s（那是给采集请求定的），
        #   `llm.timeout_s` / `llm.timeout_strong_s` 会变成死配置。strong 档（思维链）
        #   比 fast 慢得多，故分档给不同的读超时。
        read_timeout_s = (
            self.settings.timeout_strong_s if model_tier == "strong" else self.settings.timeout_s
        )
        timeout = httpx.Timeout(None, read=read_timeout_s)

        for _attempt in range(2):  # 最多一次 json_schema → json_object 降级
            if json_schema is not None:
                # 把 json_schema / json_object 两种格式纳入缓存键，避免互相串缓存
                cache_mode = "js" if use_schema else "jo"
                rm_name = f"{_json_schema_name(json_schema)}:{cache_mode}"
            else:
                rm_name = ""
            key = cache_key(
                model,
                messages,
                response_model_name=rm_name,
                temperature=temperature,
            )

            # ── 缓存命中：不计费 ──────────────────────────────────
            if self.cache is not None:
                cached = self.cache.get(key)
                if cached is not None:
                    log.debug("llm.cache.hit", purpose=purpose, model=model)
                    self._record_usage(purpose, model, model_tier, 0, 0, cache_hit=True)
                    return LLMResult(content=cached, model=model, cached=True)

            # ── 预算护栏 ──────────────────────────────────────────
            if self.budget is not None and not self.budget.can_afford(purpose):
                raise LLMError(f"超出每日预算（{purpose}），已降级")

            body = self._build_body(
                payload,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                json_schema=json_schema,
                use_schema=use_schema,
            )
            response = await self._http.request(
                "POST",
                self._endpoint(),
                source="llm",
                headers=self._headers(),
                json_body=body,
                timeout=timeout,
            )

            # ── 成功 ──────────────────────────────────────────────
            if response.status_code == 200:
                try:
                    data = response.json()
                except Exception as exc:  # noqa: BLE001
                    raise LLMError(f"LLM 响应不是合法 JSON（{purpose}）: {exc}") from exc
                if use_schema and json_schema is not None:
                    remember_json_schema_support(model, True)  # 记住"支持"，后续沿用
                content, prompt_tokens, completion_tokens = self._parse_success(data)
                if json_schema is not None and self.cache is not None and content:
                    self.cache.put(
                        key,
                        prompt=json.dumps(body["messages"], ensure_ascii=False),
                        response=content,
                        model=model,
                    )
                self._record_usage(
                    purpose,
                    model,
                    model_tier,
                    prompt_tokens,
                    completion_tokens,
                    error=error_note,
                )
                return LLMResult(
                    content=content,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )

            # ── 401/403：配置错误，立即失败不重试 ──────────────────
            if response.status_code in (401, 403):
                raise ConfigError(
                    f"LLM 认证失败（HTTP {response.status_code}），请检查 AIPULSE_LLM__API_KEY"
                )

            # ── json_schema 运行时自动降级（§8.3）──────────────────
            if (
                response.status_code == 400
                and use_schema
                and self.json_schema_mode == "auto"
                and _is_json_schema_unsupported(response)
            ):
                log.warning(
                    "llm.json_schema_unsupported",
                    model=model,
                    purpose=purpose,
                    msg="降级为 json_object + prompt 内嵌 schema",
                )
                remember_json_schema_support(model, False)
                error_note = "json_schema unsupported → json_object"
                use_schema = False
                continue

            # ── 其余失败：记录并降级（抛给上层，不中断流水线）──────
            log.warning(
                "llm.request_failed",
                purpose=purpose,
                model=model,
                status=response.status_code,
                error=_error_text(response)[:200],
            )
            raise LLMError(f"LLM 调用失败（{purpose}）：HTTP {response.status_code}")

        # 理论上不会走到（第二次已走 json_object，不再触发降级）
        raise LLMError(
            f"LLM 调用失败（{purpose}）：json_schema 降级重试后仍失败"
        )  # pragma: no cover

    def _record_usage(
        self,
        purpose: str,
        model: str,
        model_tier: str,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        cache_hit: bool = False,
        error: str | None = None,
    ) -> None:
        if self.budget is not None:
            self.budget.record(
                purpose=purpose,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model_tier=model_tier,
                cache_hit=cache_hit,
                error=error,
            )

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()


__all__ = [
    "OpenAICompatClient",
    "json_schema_support",
    "remember_json_schema_support",
    "reset_json_schema_memory",
]
