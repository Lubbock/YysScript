"""游戏窗口定位。

职责：找到游戏窗口的**客户区**在屏幕上的位置和大小，供 Viewport 换算坐标、
供 ScreenCapture 限定截屏区域。

后端可替换：
- Win32WindowFinder : Windows 客户端（pywin32）
- FullScreenFinder  : 找不到窗口 / 非 Windows（模拟器、mac 调试）时把整个屏幕当客户区

pyautogui / win32gui 都在方法内部延迟导入，保证本模块在任何平台都能被 import。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from config import settings
from core.errors import WindowNotFoundError
from core.logger import get_logger

log = get_logger(__name__)

Region = Tuple[int, int, int, int]
_dpi_ready = False


@dataclass(frozen=True)
class WindowRect:
    """客户区矩形。"""

    left: int
    top: int
    width: int
    height: int

    @property
    def origin(self) -> Tuple[int, int]:
        return self.left, self.top

    @property
    def size(self) -> Tuple[int, int]:
        return self.width, self.height

    @property
    def region(self) -> Region:
        return self.left, self.top, self.width, self.height


class WindowFinder:
    """窗口查找器接口。"""

    name = "base"

    def find(self) -> Optional[WindowRect]:
        raise NotImplementedError

    def focus(self, rect: WindowRect) -> None:
        """把窗口置前（可选实现）。"""

    def move_to_corner(self, rect: WindowRect, x: int = 0, y: int = 0) -> None:
        """把窗口挪到屏幕指定位置（可选实现）。"""


class Win32WindowFinder(WindowFinder):
    """Windows 客户端：按窗口类名 + 标题查找。"""

    name = "win32"

    def __init__(
        self,
        title: Optional[str] = None,
        classname: Optional[str] = None,
    ) -> None:
        self.title = title or settings.GAME_WINDOW_TITLE
        self.classname = classname or settings.GAME_WINDOW_CLASS

    def find(self) -> Optional[WindowRect]:
        win32gui = _import_win32()
        if win32gui is None:
            return None
        _enable_dpi_awareness()

        hwnd = win32gui.FindWindow(self.classname, self.title)
        if not hwnd:
            # 类名可能随客户端版本变化，退化成只按标题找
            hwnd = win32gui.FindWindow(None, self.title)
        if not hwnd:
            log.warning("未找到窗口 title=%s class=%s", self.title, self.classname)
            return None

        left, top = win32gui.ClientToScreen(hwnd, (0, 0))
        _, _, right, bottom = win32gui.GetClientRect(hwnd)
        rect = WindowRect(left=left, top=top, width=right, height=bottom)
        log.info("定位到游戏窗口 hwnd=%s 客户区=%s", hex(hwnd), rect)
        self._hwnd = hwnd
        return rect

    def focus(self, rect: WindowRect) -> None:
        win32gui = _import_win32()
        hwnd = getattr(self, "_hwnd", None)
        if win32gui is None or not hwnd:
            return
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception as exc:  # 前台锁定等场景，忽略即可
            log.debug("置前窗口失败: %s", exc)

    def move_to_corner(self, rect: WindowRect, x: int = 0, y: int = 0) -> None:
        """把整个窗口（含边框）挪到屏幕 (x, y)，对应旧 scripts/e0001.py。"""
        win32gui, win32con = _import_win32(with_con=True)
        hwnd = getattr(self, "_hwnd", None)
        if win32gui is None or not hwnd:
            return
        frame_w = rect.width + (rect.left - win32gui.GetWindowRect(hwnd)[0])
        frame_h = rect.height + (rect.top - win32gui.GetWindowRect(hwnd)[1])
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_TOP,
            x,
            y,
            frame_w,
            frame_h,
            win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW,
        )


class FullScreenFinder(WindowFinder):
    """把整个屏幕当成客户区（模拟器全屏 / 非 Windows 调试）。"""

    name = "fullscreen"

    def find(self) -> Optional[WindowRect]:
        import pyautogui

        width, height = pyautogui.size()
        return WindowRect(left=0, top=0, width=int(width), height=int(height))


def _import_win32(with_con: bool = False):
    """延迟导入 pywin32；非 Windows 平台返回 None。"""
    try:
        import win32gui
    except ImportError:
        return (None, None) if with_con else None
    if not with_con:
        return win32gui
    try:
        import win32con
    except ImportError:
        return win32gui, None
    return win32gui, win32con


def _enable_dpi_awareness() -> None:
    """声明 DPI 感知，否则高分屏下 win32 与 pyautogui 的坐标会不一致。"""
    global _dpi_ready
    if _dpi_ready:
        return
    _dpi_ready = True
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
        except Exception:
            pass


class GameWindow:
    """窗口句柄的缓存包装：一次定位，多次复用，需要时 refresh()。"""

    def __init__(
        self,
        finder: Optional[WindowFinder] = None,
        allow_fullscreen: Optional[bool] = None,
    ) -> None:
        self._finder = finder or Win32WindowFinder()
        self._allow_fullscreen = (
            settings.FALLBACK_TO_FULLSCREEN if allow_fullscreen is None else allow_fullscreen
        )
        self._rect: Optional[WindowRect] = None

    @property
    def rect(self) -> WindowRect:
        """当前窗口矩形，未定位时自动定位一次。"""
        if self._rect is None:
            self.refresh()
        assert self._rect is not None
        return self._rect

    @property
    def region(self) -> Region:
        return self.rect.region

    def refresh(self) -> WindowRect:
        """重新定位窗口。找不到时按配置回退全屏或抛异常。"""
        rect = self._finder.find()
        if rect is None and self._allow_fullscreen:
            log.warning("未找到游戏窗口，回退为全屏模式（坐标按整屏换算）")
            rect = FullScreenFinder().find()
        if rect is None:
            raise WindowNotFoundError(
                "找不到游戏窗口「{}」，请确认客户端已启动，"
                "或把 settings.FALLBACK_TO_FULLSCREEN 设为 True".format(settings.GAME_WINDOW_TITLE)
            )
        self._rect = rect
        return rect

    def focus(self) -> None:
        self._finder.focus(self.rect)

    def move_to_corner(self, x: int = 0, y: int = 0) -> None:
        self._finder.move_to_corner(self.rect, x, y)


def create_window(allow_fullscreen: Optional[bool] = None) -> GameWindow:
    """工厂：创建 GameWindow。"""
    return GameWindow(allow_fullscreen=allow_fullscreen)
