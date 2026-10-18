"""每日简报的结构化模型（设计方案 §10.1 / §11.1、v1.14 格式规范）。

`DailyBrief` 既是 LLM 结构化输出的契约（structured.py 用它做 JSON Schema 校验），
也是渲染层（render/markdown.py、render/json_out.py）的输入。
`date` 与 `stats` 由代码填充（LLM 不生成），其余字段来自 LLM 或 off 档的数据版降级。

v1.14 格式契约：
- `headline_item_id`：头条对应的真实条目，渲染层据此输出来源/标题/链接/平台/热度；
- `overview_bullets[]`：总览必须分条，每条一个图标 + 小标题 + 一句话；
- `editor_note`：四个固定字段，渲染成 🎯 / 🔍 / 🔄 / ⚠️ 四节。
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from pydantic import BaseModel, Field, model_validator


class OverviewBullet(BaseModel):
    """总览中的一条：一个主题图标 + 小标题 + 一句话。"""

    icon: str = "📌"
    topic: str = ""
    text: str = ""


class EditorNote(BaseModel):
    """主编点评的四个固定小节（v1.14：从一整段改为结构化四节）。"""

    core: str = ""  # 🎯 核心判断
    cross_signal: str = ""  # 🔍 交叉信号
    counterintuitive: str = ""  # 🔄 反直觉
    risk: str = ""  # ⚠️ 风险提醒


class ItemComment(BaseModel):
    """单条点评（v2，M6b）：要点 + 为什么重要 + 立场。

    v2 变更：中文概述的责任并入 `one_liner`（一律中文），不再单独出字段；
    旧版的对谁重要 / 关注信号 / 新颖度 / 影响力四个字段已移除（从未被渲染）。
    """

    item_id: str
    one_liner: str = ""  # 要点，一律中文
    why: str = ""  # 为什么重要（因果链，不说套话）
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
    headline_item_id: str = ""  # 头条对应的真实条目 id（渲染来源块）
    overview_bullets: list[OverviewBullet] = Field(default_factory=list)
    executive_summary: str = ""  # 一句话总览（bullet 之外的收束句）
    sections: list[Section] = Field(default_factory=list)
    editor_note: EditorNote = Field(default_factory=EditorNote)
    contradictions: list[str] = Field(default_factory=list)  # 今日信息中的矛盾之处
    underrated: list[str] = Field(default_factory=list)  # 被低估、热度不高但值得关注
    comments: list[ItemComment] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _coerce_editor_note(cls, data: Any) -> Any:
        """兼容 v1.13 及以前的字符串 `editor_note`（旧报告 / 旧测试）。"""
        if not isinstance(data, dict):
            return data
        note = data.get("editor_note")
        if isinstance(note, str):
            return {**data, "editor_note": EditorNote(core=note)}
        return data

    def item_ids(self) -> list[str]:
        """所有被纳入板块的条目 id（有序）。"""
        seen: list[str] = []
        for section in self.sections:
            for item_id in section.item_ids:
                if item_id not in seen:
                    seen.append(item_id)
        return seen


class ItemComments(BaseModel):
    """单条点评的批量包装（v1 遗留契约，保留以免打断既有引用）。"""

    comments: list[ItemComment] = Field(default_factory=list)


class OneLinerOut(BaseModel):
    """one_liner 单条输出（`brief/item_comment.j2` v2 的结构化契约）。

    v2 只产要点，why/stance 由 `brief/item_enhance.j2` 负责——
    两个任务分开调用，输出更短，避免挤在一次调用里撞 max_tokens。
    """

    item_id: str
    one_liner: str = ""


class OneLinersOut(BaseModel):
    """one_liner 批量包装（v2 输出的顶层键是 `one_liners`）。"""

    one_liners: list[OneLinerOut] = Field(default_factory=list)


class EnhanceOut(BaseModel):
    """why / stance 单条输出（`brief/item_enhance.j2` 的结构化契约）。"""

    item_id: str
    why: str = ""
    stance: str = ""


class EnhancesOut(BaseModel):
    """why / stance 批量包装（顶层键沿用 `comments`）。"""

    comments: list[EnhanceOut] = Field(default_factory=list)


def brief_from_dict(data: dict[str, Any], *, date: date_type | None = None) -> DailyBrief:
    """从 dict 构造 DailyBrief（对 off 档手写/LLM 原始输出做兜底）。"""
    return DailyBrief.model_validate({**data, "date": date})


__all__ = [
    "DailyBrief",
    "EditorNote",
    "EnhanceOut",
    "EnhancesOut",
    "ItemComment",
    "ItemComments",
    "OneLinerOut",
    "OneLinersOut",
    "OverviewBullet",
    "Section",
    "brief_from_dict",
]
