"""周度趋势长文的数据结构（M5 S2）。

分段生成：每段一次 LLM 调用，最后合并。这样每段上下文更聚焦、可单独校验，
也不会让单次输出同时承载 2000-4000 字正文与表格（撞 max_tokens 的根源）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TrendSegment(BaseModel):
    """长文中的一节（对应一次 LLM 调用）。"""

    key: str
    title: str
    body: str = ""
    char_count: int = 0
    cited_item_ids: list[str] = Field(default_factory=list)
    boilerplate_hits: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    skipped_reason: str = ""


class TrendReport(BaseModel):
    """一份周报：七节 + 运行指标。"""

    window_start: str = ""
    window_end: str = ""
    window_days: int = 0
    # 份额/斜率实际使用的比较区间（源集合同构）；与取数窗口不同时必须显式标注，
    # 否则读者会把"7 天窗口"和"5 天比较"混为一谈。
    comparison_start: str = ""
    comparison_end: str = ""
    comparison_days: int = 0
    segments: list[TrendSegment] = Field(default_factory=list)
    llm_calls: int = 0
    attempts: int = 0
    truncated_segments: list[str] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_cny: float = 0.0
    model_tier: str = "strong"

    def to_markdown(self) -> str:
        lines = [
            f"# AI 脉搏 · 周度趋势（取数 {self.window_start} → {self.window_end}，"
            f"{self.window_days} 天）",
            "",
        ]
        if self.comparison_start and self.comparison_days:
            lines.append(
                f"> 比较区间 {self.comparison_start} → {self.comparison_end}"
                f"（{self.comparison_days} 天，源集合同构）。份额与斜率只在比较区间内计算，"
                "跨源集合变更日的对比已禁用。"
            )
            lines.append("")
        for index, segment in enumerate(self.segments, 1):
            lines.append(f"## {index}. {segment.title}")
            lines.append("")
            if segment.skipped_reason:
                lines.append(f"> 本节未生成：{segment.skipped_reason}")
            elif segment.body.strip():
                lines.append(segment.body.strip())
            else:
                lines.append("> 本节为空。")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def summary(self) -> dict[str, object]:
        """给 --json 的指标摘要（不含正文，避免刷屏）。"""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "window_days": self.window_days,
            "comparison_start": self.comparison_start,
            "comparison_end": self.comparison_end,
            "comparison_days": self.comparison_days,
            "llm_calls": self.llm_calls,
            "attempts": self.attempts,
            "truncated_segments": self.truncated_segments,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_cny": round(self.cost_cny, 6),
            "segments": [
                {
                    "key": s.key,
                    "title": s.title,
                    "char_count": s.char_count,
                    "cited_item_ids": len(s.cited_item_ids),
                    "boilerplate_hits": s.boilerplate_hits,
                    "violations": s.violations,
                    "skipped_reason": s.skipped_reason,
                    "llm_calls": s.llm_calls,
                    "prompt_tokens": s.prompt_tokens,
                    "completion_tokens": s.completion_tokens,
                }
                for s in self.segments
            ],
        }


__all__ = ["TrendReport", "TrendSegment"]
