"""坐标换算：基准客户区逻辑坐标 <-> 屏幕绝对坐标。

这是解决「坐标按 1024x768 写死，换分辨率就全崩」的地方：
- 上层（config/coordinates.py、flows）只使用基准客户区坐标；
- 本模块按真实窗口的位置和大小做线性缩放 + 平移；
- 纯计算，不依赖 pyautogui / win32，可以单独单测。
"""
from __future__ import annotations

from typing import Optional, Tuple

from config import settings
from config.coordinates import Point

ScreenPoint = Tuple[int, int]
Region = Tuple[int, int, int, int]


class Viewport:
    """逻辑坐标与屏幕坐标的换算器。"""

    def __init__(
        self,
        origin: ScreenPoint,
        size: ScreenPoint,
        base_size: Optional[ScreenPoint] = None,
        offset: Optional[ScreenPoint] = None,
    ) -> None:
        """
        origin    : 客户区左上角的屏幕坐标
        size      : 客户区实际宽高
        base_size : 逻辑坐标的基准宽高，默认 settings.BASE_CLIENT_SIZE
        offset    : 人工校准偏移，默认 settings.CALIBRATION_OFFSET
        """
        base = base_size or settings.BASE_CLIENT_SIZE
        if base[0] <= 0 or base[1] <= 0:
            raise ValueError("基准分辨率必须为正数: {}".format(base))
        if size[0] <= 0 or size[1] <= 0:
            raise ValueError("窗口尺寸必须为正数: {}".format(size))

        self.origin = (int(origin[0]), int(origin[1]))
        self.size = (int(size[0]), int(size[1]))
        self.base_size = (int(base[0]), int(base[1]))
        self.offset = (int(offset[0]), int(offset[1])) if offset else (0, 0)

    # ------------------------------------------------------------------ 属性
    @property
    def scale_x(self) -> float:
        return self.size[0] / self.base_size[0]

    @property
    def scale_y(self) -> float:
        return self.size[1] / self.base_size[1]

    @property
    def region(self) -> Region:
        """客户区在屏幕上的矩形 (left, top, width, height)，可直接喂给截屏。"""
        return self.origin[0], self.origin[1], self.size[0], self.size[1]

    # ------------------------------------------------------------------ 换算
    def to_screen(self, point: Point, clamp: bool = True) -> ScreenPoint:
        """逻辑坐标 -> 屏幕绝对坐标。"""
        x = self.origin[0] + point.x * self.scale_x + self.offset[0]
        y = self.origin[1] + point.y * self.scale_y + self.offset[1]
        screen = (int(round(x)), int(round(y)))
        return self._clamp(screen) if clamp else screen

    def to_logical(self, screen: ScreenPoint) -> Point:
        """屏幕绝对坐标 -> 逻辑坐标（vision 的识别结果转回逻辑坐标时用）。"""
        x = (screen[0] - self.origin[0] - self.offset[0]) / self.scale_x
        y = (screen[1] - self.origin[1] - self.offset[1]) / self.scale_y
        return Point(int(round(x)), int(round(y)))

    def scale_size(self, width: int, height: int) -> ScreenPoint:
        """把逻辑尺寸换算成屏幕尺寸（拖拽距离、区域大小等）。"""
        return int(round(width * self.scale_x)), int(round(height * self.scale_y))

    def _clamp(self, screen: ScreenPoint) -> ScreenPoint:
        """把坐标限制在客户区内，避免点到窗口外面去。"""
        left, top = self.origin
        right, bottom = left + self.size[0] - 1, top + self.size[1] - 1
        return min(max(screen[0], left), right), min(max(screen[1], top), bottom)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "Viewport(origin={}, size={}, base={})".format(
            self.origin, self.size, self.base_size
        )
