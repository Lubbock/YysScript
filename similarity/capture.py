"""截屏采集：复用 actions 窗口定位与 vision 截屏。"""
from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from core.errors import YysError

SOURCES = ("window", "fullscreen")
_REQUIRED = ("cv2", "numpy", "pyautogui")


class CaptureError(YysError):
    """截屏失败。"""


@dataclass(frozen=True)
class Shot:
    """一次截屏结果。"""

    png: bytes
    width: int
    height: int
    source: str
    origin: Tuple[int, int] = (0, 0)
    region: Optional[Tuple[int, int, int, int]] = None
    window_id: Optional[int] = None
    process: Optional[str] = None

    def meta(self) -> Dict[str, Any]:
        """可 JSON 化的元信息。"""
        return {
            "source": self.source,
            "width": self.width,
            "height": self.height,
            "origin": list(self.origin),
            "region": list(self.region) if self.region else None,
            "window_id": self.window_id,
            "process": self.process,
        }


def capability() -> Dict[str, Any]:
    """探测截屏依赖是否可用。"""
    errors = []
    for name in _REQUIRED:
        try:
            importlib.import_module(name)
        except Exception as exc:
            errors.append("{}: {}: {}".format(name, type(exc).__name__, exc))
    return {"ok": not errors, "errors": errors, "platform": sys.platform}


def default_process() -> str:
    """macOS 默认目标进程名。"""
    from config import settings

    return settings.MAC_WINDOW_PROCESS


def _finder(source: str, process: Optional[str]):
    from actions.window import FullScreenFinder, MacWindowFinder, Win32WindowFinder

    if source != "window":
        return FullScreenFinder(), None
    if sys.platform == "darwin":
        name = process or default_process()
        return MacWindowFinder(name), name
    if sys.platform == "win32":
        return Win32WindowFinder(), None
    return FullScreenFinder(), None


def grab(source: str = "window", process: Optional[str] = None) -> Shot:
    """截屏并编码成 PNG。"""
    if source not in SOURCES:
        raise CaptureError("未知截图来源: {!r}（可选 {}）".format(source, " / ".join(SOURCES)))
    probe = capability()
    if not probe["ok"]:
        raise CaptureError("截屏依赖不可用：{}".format("; ".join(probe["errors"])))

    import cv2

    from vision.capture import ScreenCapture

    finder, name = _finder(source, process)
    rect = finder.find()
    if rect is None:
        hint = "整屏截图" if source == "window" else "检查目标窗口"
        raise CaptureError(
            "定位目标窗口失败（进程 {!r}）。请确认窗口已打开且未最小化，"
            "或改用{}。".format(name or process, hint)
        )

    capture = ScreenCapture(region_provider=lambda: rect.region)
    frame = capture.grab()
    ok, buffer = cv2.imencode(".png", frame.image)
    if not ok:
        raise CaptureError("PNG 编码失败")
    height, width = frame.image.shape[:2]
    return Shot(
        png=buffer.tobytes(),
        width=int(width),
        height=int(height),
        source=source,
        origin=frame.origin,
        region=rect.region,
        window_id=rect.wid,
        process=name,
    )
