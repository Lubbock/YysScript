"""模板匹配的尺度策略（纯计算，不依赖 cv2，可独立单测）。

为什么要单独拎出来：`TemplateMatcher` 会按 `settings.TEMPLATE_SCALES` 把模板缩放后
逐个尝试匹配，本意是容忍镜像窗口被拖拽缩放（macOS 的 iPhone Mirroring 窗口尺寸连续
可变）。但**缩放后模板太小就没有判别力** —— 实测踩到：41×51 的「碎片章节头像」缩到
x0.5 只剩 20×26 像素，在任意画面上都能撞上 0.96 分，脚本照着这个假命中去点击，
在探索章节界面上反复点同一个空白处，永远进不了式神碎片。

所以尺度候选要同时满足两条：

1. 尺度本身在允许的范围内（默认 1.0 ~ 0.8，容忍窗口缩到八成，再多就没意义了）；
2. 缩放后的模板**每条边**都不小于 `MIN_SCALED_TEMPLATE_SIDE`，否则丢弃该尺度。

第 2 条是关键：小模板的判别力取决于绝对像素数，不是比例。41 个模板里最窄边中位数
92 像素，x0.3 会把其中 27 个压到 32 像素以下 —— 等于整个模板库都变成噪声磁铁。
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

from config import settings


def scale_allowed(width: int, height: int, scale: float,
                  min_side: Optional[int] = None) -> bool:
    """按 scale 缩放 width×height 的模板是否仍然可信。

    参数：
        width / height : 模板原始像素尺寸
        scale          : 候选尺度
        min_side       : 缩放后每条边的像素下限，None 表示读 settings
    """
    floor = settings.MIN_SCALED_TEMPLATE_SIDE if min_side is None else min_side
    if scale <= 0:
        return False
    scaled_w = int(round(width * scale))
    scaled_h = int(round(height * scale))
    return scaled_w >= floor and scaled_h >= floor


def usable_scales(width: int, height: int,
                  scales: Optional[Sequence[float]] = None,
                  min_side: Optional[int] = None) -> Tuple[float, ...]:
    """筛出对某个模板真正可用的尺度，保持原有顺序。

    全被筛掉时返回 (1.0,)：宁可只做原尺度匹配（匹配不到就是匹配不到，会走
    「未识别」分支），也不要退化成随机点击。
    """
    candidates = tuple(settings.TEMPLATE_SCALES if scales is None else scales) or (1.0,)
    kept = tuple(scale for scale in candidates
                 if scale_allowed(width, height, scale, min_side=min_side))
    return kept or (1.0,)
