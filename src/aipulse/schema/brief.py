"""每日简报的结构化模型（设计方案 §10.1）。

`DailyBrief` 既是 LLM 结构化输出的契约（structured.py 用它做 JSON Schema 校验），
也是渲染层（render/markdown.py、render/json_out.py）的输入。
`date` 与 `stats` 由代码填充（LLM 不生成），其余字段来自 LLM 或 off 档的数据版降级。
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from pydantic import BaseModel, Field


class ItemComment(BaseModel):
    """单条点评：为什么重要 / 对谁重要 / 下一步关注什么。"""

    item_id: str
    one_liner: str = ""  # 一句话说清是什么
    why_it_matters: str = ""  # 为什么重要（因果链，不说套话）
    who_cares: str = ""  # 对谁重要（具体人群/角色）
    what_to_watch: str = ""  # 下一步关注什么（可观测信号）
    novelty: int = Field(default=0, ge=0, le=10)  # 0-10 新颖度
    impact: int = Field(default=0, ge=0, le=10)  # 0-10 影响力
    stance: str = ""  # 系统的立场/判断（可以有态度）


class Section(BaseModel):
    """简报板块：开源项目 / 论文与研究 / 社区舆论 / 产业与新闻。"""

    name: str
    item_ids: list[str] = Field(default_factory=list)
    summary: str = ""  # 板块小结（LLM 生成，off 档为空）


class DailyBrief(BaseModel):
    """每日简报全文。"""

    date: date_type | None = None
    headline: str = ""  # 今日一句话头条
    executive_summary: str = ""  # 3-5 句总览
    sections: list[Section] = Field(default_factory=list)
    editor_note: str = ""  # ★ 主编点评：整体判断、交叉信号、反直觉观察
    contradictions: list[str] = Field(default_factory=list)  # 今日信息中的矛盾之处
    underrated: list[str] = Field(default_factory=list)  # 被低估、热度不高但值得关注
    comments: list[ItemComment] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)

    def item_ids(self) -> list[str]:
        """所有被纳入板块的条目 id（有序）。"""
        seen: list[str] = []
        for section in self.sections:
            for item_id in section.item_ids:
                if item_id not in seen:
                    seen.append(item_id)
        return seen


class ItemComments(BaseModel):
    """单条点评的批量包装（full 档 item_comment.j2 的结构化输出契约）。"""

    comments: list[ItemComment] = Field(default_factory=list)


def brief_from_dict(data: dict[str, Any], *, date: date_type | None = None) -> DailyBrief:
    """从 dict 构造 DailyBrief（对 off 档手写/LLM 原始输出做兜底）。"""
    return DailyBrief.model_validate({**data, "date": date})


__all__ = ["DailyBrief", "ItemComment", "ItemComments", "Section", "brief_from_dict"]
