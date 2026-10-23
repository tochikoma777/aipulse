"""周度趋势长文的数据结构（M5 S2；S5 增加人类层字段）。

分段生成：每段一次 LLM 调用，最后合并。这样每段上下文更聚焦、可单独校验，
也不会让单次输出同时承载 2000-4000 字正文与表格（撞 max_tokens 的根源）。

**S5 双层分离**（项目总原则：机器层看过程，人类层看结论）：

- `to_machine_json()` → `weekly.json`：7 节正文 + cited id + violations + caveats，
  全部过程与免责都在这里，**L1-L4 自验证读这一份**。
- `render/weekly.py::render_weekly()` → `weekly.md`：只给结论（三句话 + 判断 + 表格），
  正文零裸 ID，免责进 `<details>`，ID 收进文末「数据溯源」。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Judgement(BaseModel):
    """人类层的一条判断性结论：只有结论文本，ID 单独放 `cited_item_ids`。

    这样正文能写成自然语言，链接又仍可追溯——`cited_item_ids` 由渲染器
    转成 `[标题](url)`，不进正文。
    """

    key: str = ""
    title: str = ""
    claim: str = ""
    cited_item_ids: list[str] = Field(default_factory=list)


class HeadlinesPayload(BaseModel):
    """「本周三句话 + 各节判断性结论」的结构化输出（人类层的第 8 次调用）。"""

    headlines: list[str] = Field(default_factory=list)
    judgements: list[Judgement] = Field(default_factory=list)


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
    # ── S5 人类层字段 ──────────────────────────────────────────────
    headlines: list[str] = Field(default_factory=list)
    """「本周三句话」：判断句，每句 ≤40 字，不含免责措辞、不含裸 ID。"""

    judgements: list[Judgement] = Field(default_factory=list)
    """从 7 节里提炼出的判断性结论（过程与免责留在机器层）。"""

    caveats: list[str] = Field(default_factory=list)
    """口径与免责：比较区间、采集失败、源集合变更、未做显著性检验等。"""

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

    def to_machine_json(self) -> dict[str, object]:
        """机器层：L1-L4 自验证的输入源。

        ★ 这里必须保留全部过程数据（7 节正文、裸 ID、violations、免责），
        人类层 `weekly.md` 才好放心地把它们移出正文。
        """
        return {
            "schema_version": 2,
            "window": {
                "start": self.window_start,
                "end": self.window_end,
                "days": self.window_days,
            },
            "comparison": {
                "start": self.comparison_start,
                "end": self.comparison_end,
                "days": self.comparison_days,
            },
            "headlines": list(self.headlines),
            "judgements": [j.model_dump() for j in self.judgements],
            "caveats": list(self.caveats),
            "segments": [
                {
                    "key": s.key,
                    "title": s.title,
                    "body": s.body,
                    "char_count": s.char_count,
                    "cited_item_ids": list(s.cited_item_ids),
                    "boilerplate_hits": list(s.boilerplate_hits),
                    "violations": list(s.violations),
                    "llm_calls": s.llm_calls,
                    "prompt_tokens": s.prompt_tokens,
                    "completion_tokens": s.completion_tokens,
                    "skipped_reason": s.skipped_reason,
                }
                for s in self.segments
            ],
            "llm": {
                "calls": self.llm_calls,
                "attempts": self.attempts,
                "truncated_segments": list(self.truncated_segments),
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "cost_cny": round(self.cost_cny, 6),
                "model_tier": self.model_tier,
            },
        }

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


__all__ = ["HeadlinesPayload", "Judgement", "TrendReport", "TrendSegment"]
