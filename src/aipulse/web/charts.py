"""校准曲线（内联 SVG，零前端构建链）。

设计决策 #10：HTML 极简黑白 + 数据表格，不引图表库。
"声称置信度 vs 实际命中率"这条对角线是记分板最有说服力的部分（§10.2.3），
所以这里只算坐标、不画花哨装饰——点离对角线越近，系统越"知道自己不知道什么"。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from aipulse.analysis.stats import CalibrationBucket

WIDTH = 560
HEIGHT = 380
PAD_LEFT = 58
PAD_RIGHT = 26
PAD_TOP = 26
PAD_BOTTOM = 46

_TICKS = (0.0, 0.25, 0.5, 0.75, 1.0)


def build_calibration_chart(
    buckets: Sequence[CalibrationBucket], *, width: int = WIDTH, height: int = HEIGHT
) -> dict[str, Any]:
    """把校准分桶换算成 SVG 坐标（纯函数，可单测）。

    坐标原点在左下角：x = 平均置信度，y = 实际命中率。
    """
    x0, y0 = PAD_LEFT, height - PAD_BOTTOM  # 数据空间 (0, 0)
    x1, y1 = width - PAD_RIGHT, PAD_TOP  # 数据空间 (1, 1)

    def px(value: float) -> float:
        return x0 + (x1 - x0) * value

    def py(value: float) -> float:
        return y0 + (y1 - y0) * value

    points: list[dict[str, Any]] = []
    for bucket in buckets:
        if not bucket.n or bucket.mean_confidence is None or bucket.hit_rate is None:
            continue
        points.append(
            {
                "label": bucket.label,
                "n": bucket.n,
                "mean_confidence": round(bucket.mean_confidence, 3),
                "hit_rate": round(bucket.hit_rate, 3),
                "cx": round(px(bucket.mean_confidence), 1),
                "cy": round(py(bucket.hit_rate), 1),
            }
        )
    points.sort(key=lambda p: p["mean_confidence"])

    axis = [
        {"value": value, "x": round(px(value), 1), "y": round(py(value), 1), "label": f"{value:g}"}
        for value in _TICKS
    ]
    return {
        "width": width,
        "height": height,
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "ticks": axis,
        "points": points,
        "polyline": " ".join(f"{p['cx']},{p['cy']}" for p in points),
        "has_points": len(points) > 0,
        "diagonal": {"x1": x0, "y1": y0, "x2": x1, "y2": y1},
    }


__all__ = ["build_calibration_chart"]
