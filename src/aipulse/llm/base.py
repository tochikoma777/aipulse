"""LLM 抽象层（设计方案 §8.1 / §8.5）。

三档运行模式的落地关键：
- `NullLLM`：off 档注入，**零网络请求**（红线 8）。chat 直接返回空结果。
- `FakeLLM`：测试/CI 用，返回预置模板化输出，让 hybrid/full 代码路径能在无 key 下被测试。
- `OpenAICompatClient`：真实实现（见 openai_compat.py），hybrid/full 档使用。

应用代码（reasoning/）只依赖 `LLMClient` Protocol，不 import 具体实现——
这就是"禁止直接调 SDK"（执行手册 §0.2）的工程表达。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel


@dataclass
class ChatMessage:
    role: str  # system | user | assistant
    content: str


@dataclass
class LLMResult:
    content: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached: bool = False
    parsed: BaseModel | None = None
    # 厂商返回的结束原因。`"length"` = 撞 max_tokens 被截断（调用方必须当失败处理，
    # 不能把半截内容当成功）。缓存命中时为 None——能进缓存的只有完整输出。
    finish_reason: str | None = None


class LLMClient(Protocol):
    """LLM 调用协议。`json_schema` 非空时要求返回 JSON（content 为 JSON 字符串）。"""

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int = 2000,
        purpose: str = "general",
        model_tier: str = "fast",  # fast | strong（prompt front-matter 决定）
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResult: ...


class NullLLM:
    """off 档：零调用、零网络。所有能力降级为「数据版」输出。"""

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
        return LLMResult(content="", model="null")


class FakeLLM:
    """测试/CI 用：返回预置响应，绝不打网络。

    `responses` 按 `purpose` 键存原始 JSON 字符串；命中时若给了 `response_model`
    则顺带解析成 `parsed`，便于结构化链路测试。
    """

    def __init__(self, responses: Mapping[str, str] | None = None) -> None:
        self.responses: dict[str, str] = dict(responses or {})
        self.calls: list[tuple[str, list[ChatMessage]]] = []

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
        self.calls.append((purpose, messages))
        raw = self.responses.get(purpose, "{}")
        parsed: BaseModel | None = None
        return LLMResult(content=raw, model=f"fake/{model_tier}", parsed=parsed)


def build_client(settings: Any, *, engine: Any | None = None) -> LLMClient:
    """按有效运行模式构造 LLM 客户端。

    - off（或未配置 key）→ NullLLM（零网络）。
    - hybrid / full → OpenAICompatClient（懒加载，避免 off 档 import openai SDK）。
    """
    mode = settings.effective_mode()
    if mode.value == "off":
        return NullLLM()

    from aipulse.llm.budget import BudgetTracker
    from aipulse.llm.openai_compat import OpenAICompatClient

    budget = BudgetTracker(
        engine,
        daily_limit_cny=settings.budget.daily_limit_cny,
        price_fast_cny_per_1m=settings.budget.price_fast_cny_per_1m,
        price_strong_cny_per_1m=settings.budget.price_strong_cny_per_1m,
        degrade_order=settings.budget.degrade_order,
    )
    return OpenAICompatClient(settings.llm, engine=engine, budget=budget)


__all__ = [
    "ChatMessage",
    "FakeLLM",
    "LLMClient",
    "LLMResult",
    "NullLLM",
    "build_client",
]
