"""截屏。

旧代码每次识别都截**整个屏幕**：慢，而且桌面上的其它窗口 / 弹窗会造成误匹配。
这里支持只截游戏窗口区域（region_provider 由 actions 层注入窗口矩形）。
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Tuple

import cv2
import numpy as np
import pyautogui

from vision.types import Frame

#: 返回 (left, top, width, height) 或 None（None 表示截全屏）
RegionProvider = Callable[[], Optional[Tuple[int, int, int, int]]]


class ScreenCapture:
    """把 pyautogui 截屏封装成 BGR numpy 数组。"""

    def __init__(self, region_provider: Optional[RegionProvider] = None) -> None:
        self._region_provider = region_provider

    def region(self) -> Optional[Tuple[int, int, int, int]]:
        """当前截图区域；None 表示全屏。"""
        if self._region_provider is None:
            return None
        return self._region_provider()

    def grab(self, region: Optional[Tuple[int, int, int, int]] = None) -> Frame:
        """截屏并返回 Frame（BGR）。"""
        area = region if region is not None else self.region()
        if area is None:
            shot = pyautogui.screenshot()
            origin = (0, 0)
        else:
            left, top, width, height = area
            shot = pyautogui.screenshot(region=(int(left), int(top), int(width), int(height)))
            origin = (int(left), int(top))
        image = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2BGR)
        h, w = image.shape[:2]
        return Frame(image=image, origin=origin, size=(w, h))

    def grab_gray(self, region: Optional[Tuple[int, int, int, int]] = None) -> Frame:
        """截屏并转灰度。"""
        frame = self.grab(region)
        gray: Any = cv2.cvtColor(frame.image, cv2.COLOR_BGR2GRAY)
        return Frame(image=gray, origin=frame.origin, size=frame.size)
