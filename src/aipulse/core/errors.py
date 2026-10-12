"""统一异常层级。

约定：项目内所有自定义异常都继承 :class:`AipulseError`，上层（CLI / pipeline）
只需捕获这一个基类即可做兜底处理，同时又能针对子类给出不同的降级策略。
"""

from __future__ import annotations


class AipulseError(Exception):
    """项目所有异常的基类。"""


class ConfigError(AipulseError):
    """配置缺失、格式错误或取值非法。"""


class CollectorError(AipulseError):
    """单个数据源采集失败。

    采集层必须捕获并转成该异常（携带 source），由编排层记录到 `source_runs`
    后继续跑其余源，绝不让单源失败打断整条流水线。
    """

    def __init__(self, source: str, message: str, *, cause: BaseException | None = None) -> None:
        self.source = source
        self.message = message
        self.cause = cause
        super().__init__(f"[{source}] {message}")


class LLMError(AipulseError):
    """LLM 调用失败或输出校验失败（调用方应降级跳过，而不是中断）。"""


class StoreError(AipulseError):
    """数据库读写失败。"""
