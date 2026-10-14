"""量化判据模板库的加载与渲染（设计方案 §11.5，v1.3）。

- `criteria_names()` / `criteria_template()`：读 `configs/criteria.yaml`，供向导选择。
- `render_criteria()`：把模板 + 参数渲染成人类可读的 `falsifiable_criteria` 文本
  （如 `github_stars_reach(repo=vllm-project/vllm, threshold=80000)`），
  这样带量化判据的预言即便不设判据模板也能满足"可证伪"红线。
- `coerce_param()`：把 `--param key=value` 或向导输入的字符串按模板声明的类型转成 int/float/str。

M3b 的 verifier 将复用本模块的模板定义做"查表即判"，本阶段只负责加载与渲染。
"""

from __future__ import annotations

from typing import Any

from aipulse.core.config import load_criteria


def criteria_names() -> list[str]:
    """所有可用判据模板名（不含"不设定"）。"""
    return list(load_criteria().get("criteria", {}).keys())


def criteria_template(name: str) -> dict[str, Any]:
    """取某判据模板（{description, params}）。不存在时抛 KeyError。"""
    data = load_criteria().get("criteria", {})
    if name not in data:
        raise KeyError(f"未知判据模板：{name!r}（可用：{sorted(data)}）")
    return dict(data[name])


def criteria_params(name: str) -> list[dict[str, Any]]:
    """模板声明的参数列表。"""
    return list(criteria_template(name).get("params", []))


def render_criteria(name: str, params: dict[str, Any] | None = None) -> str:
    """渲染成 falsifiable_criteria 文本。"""
    values = params or {}
    return f"{name}({', '.join(f'{k}={v!r}' for k, v in values.items())})"


def coerce_param(name: str, raw: str, type_: str) -> Any:
    """按模板声明的类型把字符串参数转成对应类型。"""
    value = (raw or "").strip()
    if type_ == "int":
        return int(value)
    if type_ == "float":
        return float(value)
    return value


def parse_param_assignments(pairs: list[str], template_name: str) -> dict[str, Any]:
    """把 `["repo=vllm-project/vllm", "threshold=80000"]` 转成 dict，并按模板类型规整。"""
    params: dict[str, Any] = {}
    declared = {p["name"]: p for p in criteria_params(template_name)}
    for pair in pairs:
        key, _, value = pair.partition("=")
        key = key.strip()
        if not key:
            continue
        type_ = str(declared.get(key, {}).get("type", "str"))
        params[key] = coerce_param(key, value, type_)
    return params


__all__ = [
    "coerce_param",
    "criteria_names",
    "criteria_params",
    "criteria_template",
    "parse_param_assignments",
    "render_criteria",
]
