"""结构化 LLM 输出保障（设计方案 §8.3）。

流程：response_model.model_json_schema() → 要求 JSON 输出 → model_validate_json 校验 →
失败触发**一次**修复重试（把错误与原输出回传，要求"修正为合法 JSON"）→
再失败则记录日志并返回 None（降级跳过，**绝不 raise 到 pipeline**）。
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from aipulse.core.logging import get_logger
from aipulse.llm.base import ChatMessage, LLMClient, LLMResult

log = get_logger(__name__)


def _validate(model: type[BaseModel], content: str) -> BaseModel | None:
    """把原始输出解析成模型；任何失败都返回 None，不抛异常。"""
    if not content or not content.strip():
        return None
    try:
        return model.model_validate_json(content)
    except (ValidationError, ValueError) as exc:
        log.debug("llm.structured.validate_fail", model=model.__name__, error=repr(exc))
        return None


async def generate_structured(
    client: LLMClient,
    messages: list[ChatMessage],
    *,
    response_model: type[BaseModel],
    temperature: float = 0.3,
    max_tokens: int = 2000,
    purpose: str = "general",
    model_tier: str = "fast",
) -> tuple[BaseModel | None, LLMResult | None]:
    """生成并校验结构化输出。

    返回 `(解析结果, 最后一次 LLMResult)`；解析结果为 None 表示已降级跳过。
    网络异常由调用方捕获（此处只负责"校验失败 → 修复重试"）。
    """
    schema = response_model.model_json_schema()

    result = await client.chat(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        purpose=purpose,
        model_tier=model_tier,
        json_schema=schema,
    )
    parsed = _validate(response_model, result.content)
    if parsed is not None:
        return parsed, result

    # ── 一次修复重试：把原始输出 + 错误回传，要求只输出修正后的 JSON ──
    log.warning("llm.structured.retry", purpose=purpose, model=response_model.__name__)
    repair_messages = [
        *messages,
        ChatMessage(role="assistant", content=result.content),
        ChatMessage(
            role="user",
            content=(
                "你上一条输出无法解析为合法 JSON。请**只**输出修正后的合法 JSON，"
                "不要任何解释、代码块围栏或多余文字。"
            ),
        ),
    ]
    retried = await client.chat(
        repair_messages,
        temperature=temperature,
        max_tokens=max_tokens,
        purpose=purpose,
        model_tier=model_tier,
        json_schema=schema,
    )
    parsed = _validate(response_model, retried.content)
    if parsed is not None:
        return parsed, retried

    log.error("llm.structured.degraded", purpose=purpose, model=response_model.__name__)
    return None, retried


__all__ = ["generate_structured"]
