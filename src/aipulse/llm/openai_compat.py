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

# 结构化输出的降级阶梯（§8.3）。DeepSeek 实况：
#   deepseek-chat      支持 json_object，不支持 json_schema
#   deepseek-reasoner  两个结构化参数都不支持（R1 系列），只能走 plain
# 所以阶梯必须到三级：json_schema → json_object → plain（纯文本 + prompt 内嵌 schema）。
# plain 是万能兜底——任何模型都能输出一段文本，我们只要能从中抠出 JSON。
_FORMAT_LADDER = ("json_schema", "json_object", "plain")

# 进程内"模型 + 格式 → 是否支持"的记忆。**key 必须是 (model, format) 而不是全局布尔**：
# 同一进程里 chat 与 reasoner 混用，若用全局标记，先跑的 reasoner 会把 chat 也拖下水，
# 白白丢掉 chat 本可用的 json_object。
_JSON_FORMAT_SUPPORT: dict[tuple[str, str], bool] = {}

# 结构化格式不支持时的错误体关键词（§8.3 判定依据）
_JSON_SCHEMA_UNSUPPORTED_KEYWORDS = ("json_schema", "response_format", "unsupported", "not support")


def json_format_support(model: str, fmt: str) -> bool | None:
    """某模型对某结构化格式是否支持（None 表示尚无记忆，应尝试）。"""
    return _JSON_FORMAT_SUPPORT.get((model, fmt))


def _next_format(fmt: str) -> str:
    """降级阶梯的下一级（到底即为 `plain`，不再降级）。"""
    idx = _FORMAT_LADDER.index(fmt)
    return _FORMAT_LADDER[min(idx + 1, len(_FORMAT_LADDER) - 1)]


def remember_json_format_support(model: str, fmt: str, supported: bool) -> None:
    """进程内记住探测结果。"""
    _JSON_FORMAT_SUPPORT[(model, fmt)] = supported


def json_schema_support(model: str) -> bool | None:
    """便捷访问：该模型是否支持 json_schema。"""
    return json_format_support(model, "json_schema")


def remember_json_schema_support(model: str, supported: bool) -> None:
    remember_json_format_support(model, "json_schema", supported)


def reset_json_schema_memory() -> None:
    """清空进程内记忆（测试用）。"""
    _JSON_FORMAT_SUPPORT.clear()


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

    def _initial_format(self, model: str, wants_schema: bool) -> str:
        """本次调用的起始结构化格式。

        auto 模式下从阶梯里挑**第一个没被记住"不支持"**的格式——这样第二次运行
        就不用再白试一遍已被证伪的档位（首次运行仍会从最强的 json_schema 开始探）。
        """
        if not wants_schema:
            return "plain"
        if self.json_schema_mode == "true":
            return "json_schema"
        if self.json_schema_mode == "false":
            return "json_object"
        for fmt in _FORMAT_LADDER:
            if json_format_support(model, fmt) is False:
                continue
            return fmt
        return "plain"

    def _body_for_format(
        self,
        payload: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
        fmt: str,
    ) -> dict[str, Any]:
        """按结构化格式构造请求体。

        - `json_schema`：最强，模型被强制按 schema 输出
        - `json_object`：只保证输出是合法 JSON，schema 内嵌进 system prompt
        - `plain`：**不带任何 response_format**，schema 只写在 prompt 里，
          靠 `_extract_json` 从文本中抠出来——任何模型都支持，是万能兜底
        """
        messages = [dict(m) for m in payload]
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_schema is None:
            return body

        schema_text = json.dumps(json_schema, ensure_ascii=False)
        if fmt == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": _json_schema_name(json_schema), "schema": json_schema},
            }
        elif fmt == "json_object":
            body["response_format"] = {"type": "json_object"}
            body["messages"] = [
                *messages,
                {
                    "role": "system",
                    "content": f"你必须只输出符合以下 JSON Schema 的 JSON：{schema_text}",
                },
            ]
        else:  # plain
            body["messages"] = [
                *messages,
                {
                    "role": "system",
                    "content": (
                        "只输出一个 JSON 对象（不要解释、不要多余文字），"
                        f"其结构必须严格符合以下 JSON Schema：{schema_text}"
                    ),
                },
            ]
        return body

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _parse_success(data: dict[str, Any]) -> tuple[str, int, int, str | None]:
        choices = data.get("choices") or []
        content = ""
        finish_reason: str | None = None
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content") or ""
            # finish_reason == "length" 表示撞了 max_tokens 被截断；
            # 不检查它，截断就只会表现为"输出变短/JSON 解析失败"（静默失败）。
            raw_reason = choices[0].get("finish_reason")
            finish_reason = raw_reason if isinstance(raw_reason, str) else None
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        return content, prompt_tokens, completion_tokens, finish_reason

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
        # 起始格式：auto 时从阶梯里挑第一个没被证伪的档位
        fmt = self._initial_format(model, wants_schema)
        error_note: str | None = None
        # ★ 读超时必须显式传：不传就会吃 HttpClient 的默认 20s（那是给采集请求定的），
        #   `llm.timeout_s` / `llm.timeout_strong_s` 会变成死配置。strong 档（思维链）
        #   比 fast 慢得多，故分档给不同的读超时。
        read_timeout_s = (
            self.settings.timeout_strong_s if model_tier == "strong" else self.settings.timeout_s
        )
        timeout = httpx.Timeout(None, read=read_timeout_s)

        # 降级阶梯：json_schema → json_object → plain，最多三级
        for _step in range(len(_FORMAT_LADDER)):
            # 把结构化格式纳入缓存键，避免不同档位互相串缓存
            rm_name = f"{_json_schema_name(json_schema)}:{fmt}" if json_schema is not None else ""
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

            body = self._body_for_format(
                payload,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                json_schema=json_schema,
                fmt=fmt,
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
                if fmt == "json_schema" and json_schema is not None:
                    remember_json_schema_support(model, True)  # 记住"支持"，后续沿用
                content, prompt_tokens, completion_tokens, finish_reason = self._parse_success(data)
                # 计费先记账：截断也是真花了钱，不能因为 raise 就漏记
                self._record_usage(
                    purpose,
                    model,
                    model_tier,
                    prompt_tokens,
                    completion_tokens,
                    error=error_note
                    or (
                        "finish_reason=length（输出被 max_tokens 截断）"
                        if finish_reason == "length"
                        else None
                    ),
                )
                if finish_reason == "length":
                    # ★ 静默失败的防线：截断绝不返回、绝不写缓存。
                    # 缓存写进去会让后续所有同 prompt 调用都读到半截内容。
                    raise LLMError(
                        f"LLM 输出被 max_tokens={max_tokens} 截断（{purpose}，"
                        f"model={model}，completion_tokens={completion_tokens}）；"
                        "请提高 max_tokens 或缩短输入"
                    )
                if json_schema is not None and self.cache is not None and content:
                    self.cache.put(
                        key,
                        prompt=json.dumps(body["messages"], ensure_ascii=False),
                        response=content,
                        model=model,
                    )
                return LLMResult(
                    content=content,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    finish_reason=finish_reason,
                )

            # ── 401/403：配置错误，立即失败不重试 ──────────────────
            if response.status_code in (401, 403):
                raise ConfigError(
                    f"LLM 认证失败（HTTP {response.status_code}），请检查 AIPULSE_LLM__API_KEY"
                )

            # ── 结构化格式运行时自动降级（§8.3）──────────────────
            if (
                response.status_code == 400
                and fmt != "plain"
                and self.json_schema_mode == "auto"
                and _is_json_schema_unsupported(response)
            ):
                log.warning(
                    "llm.structured_format_unsupported",
                    model=model,
                    purpose=purpose,
                    fmt=fmt,
                    next=_next_format(fmt),
                )
                remember_json_format_support(model, fmt, False)
                error_note = f"{fmt} unsupported → {_next_format(fmt)}"
                fmt = _next_format(fmt)
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

        # 三级（json_schema / json_object / plain）都走完仍失败才算降级
        raise LLMError(f"LLM 调用失败（{purpose}）：三级结构化降级后仍失败")  # pragma: no cover

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
