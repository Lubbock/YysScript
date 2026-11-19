"""截屏。

旧代码每次识别都截**整个屏幕**：慢，而且桌面上的其它窗口 / 弹窗会造成误匹配。
这里支持只截游戏窗口区域（region_provider 由 actions 层注入窗口矩形）；
macOS 上还提供按窗口编号（Quartz）抓窗口内容的通道：窗口被遮挡 / 被拖动
都不影响截图与坐标（window_id_provider 由 actions 层注入）。
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Tuple

import cv2
import numpy as np
import pyautogui

from core.logger import get_logger
from vision.types import Frame

log = get_logger(__name__)

#: 返回 (left, top, width, height) 或 None（None 表示截全屏）
RegionProvider = Callable[[], Optional[Tuple[int, int, int, int]]]
#: 返回 macOS 窗口编号（Quartz window number）或 None
WindowIdProvider = Callable[[], Optional[int]]


class ScreenCapture:
    """把截屏封装成 BGR numpy 数组。"""

    def __init__(
        self,
        region_provider: Optional[RegionProvider] = None,
        window_id_provider: Optional[WindowIdProvider] = None,
    ) -> None:
        self._region_provider = region_provider
        self._window_id_provider = window_id_provider

    def region(self) -> Optional[Tuple[int, int, int, int]]:
        """当前截图区域；None 表示全屏。"""
        if self._region_provider is None:
            return None
        return self._region_provider()

    def grab(self, region: Optional[Tuple[int, int, int, int]] = None) -> Frame:
        """截屏并返回 Frame（BGR）。

        优先按窗口编号（macOS Quartz）抓窗口内容：窗口被遮挡 / 被拖动都不影响；
        拿不到窗口编号时退回按区域截屏。
        """
        wid = self._window_id_provider() if self._window_id_provider else None
        if wid:
            frame = self._grab_window(wid)
            if frame is not None:
                return frame
        area = region if region is not None else self.region()
        if area is None:
            shot = pyautogui.screenshot()
            origin = (0, 0)
        else:
            left, top, width, height = area
            shot = pyautogui.screenshot(region=(int(left), int(top), int(width), int(height)))
            origin = (int(left), int(top))
            # 个别平台（macOS Retina）返回的像素尺寸与 region 点数不一致，
            # 统一缩回 region 尺寸，保证 Frame 坐标与点击坐标同一单位。
            if shot.size != (int(width), int(height)):
                shot = shot.resize((int(width), int(height)))
        image = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2BGR)
        h, w = image.shape[:2]
        return Frame(image=image, origin=origin, size=(w, h))

    def _grab_window(self, wid: int) -> Optional[Frame]:
        """macOS：按窗口编号抓窗口内容（Quartz CGWindowListCreateImage）。

        每次抓取都重新查窗口当前 bounds，因此窗口移动后坐标依然正确；
        返回的图像统一缩放到 bounds 的点尺寸，与点击坐标同一单位。
        """
        try:
            import Quartz
        except ImportError:
            return None
        try:
            bounds = None
            wins = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
            for info in wins:
                if info.get("kCGWindowNumber") == wid:
                    b = info["kCGWindowBounds"]
                    bounds = (int(b["X"]), int(b["Y"]), int(b["Width"]), int(b["Height"]))
                    break
            if bounds is None:
                return None
            x, y, w, h = bounds
            image_ref = Quartz.CGWindowListCreateImage(
                Quartz.CGRectMake(x, y, w, h),
                Quartz.kCGWindowListOptionIncludingWindow,
                wid,
                Quartz.kCGWindowImageBestResolution,
            )
            if image_ref is None:
                return None
            iw = Quartz.CGImageGetWidth(image_ref)
            ih = Quartz.CGImageGetHeight(image_ref)
            data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(image_ref))
            pixels = np.frombuffer(bytes(data), np.uint8)
            stride = Quartz.CGImageGetBytesPerRow(image_ref)
            pixels = pixels.reshape(ih, stride)[:, : iw * 4].reshape(ih, iw, 4)
            image = pixels[:, :, :3].copy()  # BGRA 字节序 -> BGR
            if (iw, ih) != (w, h):
                image = cv2.resize(image, (w, h), interpolation=cv2.INTER_AREA)
            return Frame(image=image, origin=(x, y), size=(w, h))
        except Exception as exc:  # 权限 / 窗口最小化等，退回区域截屏
            log.debug("按窗口编号截屏失败 wid=%s: %s", wid, exc)
            return None

    def grab_gray(self, region: Optional[Tuple[int, int, int, int]] = None) -> Frame:
        """截屏并转灰度。"""
        frame = self.grab(region)
        gray: Any = cv2.cvtColor(frame.image, cv2.COLOR_BGR2GRAY)
        return Frame(image=gray, origin=frame.origin, size=frame.size)
