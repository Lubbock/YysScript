"""截屏结果的数据结构。

坐标语义约定（全项目统一）：
- Frame.origin 与标注像素是两套不同基准，见 AGENTS.md 第 4 节；
- config.coordinates.Point 是**基准客户区逻辑坐标**；
- 互转由 actions.viewport.Viewport（逻辑↔屏幕）与 runner.session.Session（标注像素↔逻辑）负责。
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

