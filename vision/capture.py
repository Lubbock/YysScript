"""截屏：按窗口区域截图。

region_provider 由 actions 层注入游戏窗口矩形，截的是屏幕上那块区域。
调用方（runner.session / similarity.capture）在截屏前调 `actions.mouse.ensure_frontmost`
把目标窗口提到最前，否则拍到的是压在上面的窗口。
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Tuple

import cv2
import numpy as np
import pyautogui

from vision.types import Frame

#: 返回 (left, top, width, height)；None 表示截全屏
RegionProvider = Callable[[], Optional[Tuple[int, int, int, int]]]


class ScreenCapture:
    """把截屏封装成 BGR numpy 数组。"""

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
            left, top, width, height = (int(v) for v in area)
            shot = pyautogui.screenshot(region=(left, top, width, height))
            origin = (left, top)
            if shot.size != (width, height):  # Retina：像素尺寸 != 点数
                shot = shot.resize((width, height))
        image = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2BGR)
        h, w = image.shape[:2]
        return Frame(image=image, origin=origin, size=(w, h))

    def grab_gray(self, region: Optional[Tuple[int, int, int, int]] = None) -> Frame:
        """截屏并转灰度。"""
        frame = self.grab(region)
        gray: Any = cv2.cvtColor(frame.image, cv2.COLOR_BGR2GRAY)
        return Frame(image=gray, origin=frame.origin, size=frame.size)
