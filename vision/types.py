"""图像识别的公共数据结构。

坐标语义约定（全项目统一）：
- Frame.origin / Box / Match 里的坐标都是**屏幕绝对坐标**；
- config.coordinates.Point 是**基准客户区逻辑坐标**；
- 两者互转由 actions.viewport.Viewport 负责。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Tuple


@dataclass(frozen=True)
class Frame:
    """一次截屏结果。

    image  : BGR 顺序的 numpy 数组
    origin : 截图左上角在屏幕上的绝对坐标
    size   : 截图宽高
    """

    image: Any
    origin: Tuple[int, int] = (0, 0)
    size: Tuple[int, int] = (0, 0)

    def to_screen(self, x: int, y: int) -> Tuple[int, int]:
        """把截图内的局部坐标换算成屏幕绝对坐标。"""
        return self.origin[0] + x, self.origin[1] + y


@dataclass(frozen=True)
class Box:
    """屏幕绝对坐标下的矩形区域。"""

    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> Tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2

    @property
    def bottom_right(self) -> Tuple[int, int]:
        """旧 MapCv.location_screen 返回的就是这个点，保留以便复现旧行为。"""
        return self.x + self.w, self.y + self.h

    @property
    def area(self) -> int:
        return self.w * self.h


@dataclass(frozen=True)
class Match:
    """一次模板匹配命中。"""

    box: Box
    score: float
    template: str

    @property
    def center(self) -> Tuple[int, int]:
        return self.box.center

    @property
    def bottom_right(self) -> Tuple[int, int]:
        return self.box.bottom_right
