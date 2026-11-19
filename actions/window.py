"""游戏窗口定位。

职责：找到游戏窗口的**客户区**在屏幕上的位置和大小，供 Viewport 换算坐标、
供 ScreenCapture 限定截屏区域。

后端可替换：
- Win32WindowFinder : Windows 客户端（pywin32）
- MacWindowFinder   : macOS 按进程名定位窗口（默认「iPhone Mirroring」iOS 镜像窗口）
- FullScreenFinder  : 找不到窗口 / 其它平台（模拟器、调试）时把整个屏幕当客户区

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
    #: macOS 窗口编号（Quartz window number）；有它就能按窗口抓内容，不受遮挡 / 移动影响
    wid: Optional[int] = None

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


class MacWindowFinder(WindowFinder):
    """macOS：按进程名定位窗口，把窗口矩形当客户区。

    默认找系统自带「iPhone Mirroring」（iPhone 镜像）窗口：窗口内容就是连到
    Mac 的 iOS 设备屏幕，窗口内的鼠标点击会直接透传到手机，因此「截屏 ->
    匹配 -> 点击」整套管线可以原样复用到 iOS 客户端。
    窗口矩形通过 System Events（AppleScript）获取，无额外三方依赖。
    """

    name = "mac"

    def __init__(self, process: Optional[str] = None) -> None:
        self.process = process or settings.MAC_WINDOW_PROCESS
        #: 目标进程 PID（事件直投用），find() 时刷新
        self.pid: Optional[int] = None

    def find(self) -> Optional[WindowRect]:
        self.pid = _mac_pid(self.process)
        rect = _mac_quartz_rect(self.process) or _mac_window_rect(self.process)
        if rect is None:
            log.warning("未找到进程 %s 的窗口（镜像未打开？）", self.process)
        else:
            log.info("定位到 mac 窗口 process=%s rect=%s", self.process, rect)
        return rect

    def focus(self, rect: WindowRect) -> None:
        _mac_activate(self.process)




def _mac_quartz_rect(process: str) -> Optional[WindowRect]:
    """用 Quartz 窗口列表取窗口矩形 + 窗口编号（window number）。

    拿到 wid 后截屏层可以按窗口编号直接抓窗口内容：窗口被其它窗口遮挡、
    或被拖动换位都不影响截图与坐标。进程名用 pgrep 取 PID 再匹配 owner，
    避免系统语言不同导致窗口 owner 名称本地化（如「iPhone镜像」）匹配失败。
    """
    import subprocess

    try:
        import Quartz
    except ImportError:
        return None
    try:
        out = subprocess.run(
            ["pgrep", "-x", process], capture_output=True, text=True, timeout=5,
        ).stdout
        pids = {int(p) for p in out.split() if p.strip()}
        if not pids:
            return None
        wins = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
        for w in wins:
            if w.get("kCGWindowOwnerPID") in pids and w.get("kCGWindowLayer", 1) == 0:
                b = w["kCGWindowBounds"]
                x, y, width, height = (int(b[k]) for k in ("X", "Y", "Width", "Height"))
                if w.get("kCGIsMinimized"):
                    log.warning("镜像窗口已最小化，请先还原窗口（最小化时无法抓取窗口内容）")
                    return None
                if width > 0 and height > 0:
                    return WindowRect(left=x, top=y, width=width, height=height,
                                      wid=int(w["kCGWindowNumber"]))
    except Exception as exc:
        log.debug("quartz 取窗口失败: %s", exc)
    return None


def _mac_pid(process: str) -> Optional[int]:
    """按进程名取 PID（pgrep -x 精确匹配）。"""
    import subprocess

    try:
        out = subprocess.run(
            ["pgrep", "-x", process], capture_output=True, text=True, timeout=5,
        ).stdout
        pids = [int(p) for p in out.split() if p.strip()]
    except Exception:
        return None
    return pids[0] if pids else None


def _mac_window_rect(process: str) -> Optional[WindowRect]:
    """通过 System Events 取进程第一个窗口的位置与大小。"""
    import subprocess

    script = (
        'tell application "System Events" to tell process "{}" '
        "to get {{position, size}} of window 1".format(process)
    )
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        x, y, w, h = (int(part) for part in out.replace(" ", "").split(",")[:4])
    except Exception as exc:  # 进程不存在 / 无窗口 / 无辅助功能权限
        log.debug("获取 mac 窗口失败: %s", exc)
        return None
    if w <= 0 or h <= 0:
        return None
    return WindowRect(left=x, top=y, width=w, height=h)


def _mac_activate(process: str) -> None:
    """把目标进程置前（点击要落在镜像窗口上）。"""
    import subprocess

    script = (
        'tell application "System Events" to set frontmost of process "{}" to true'.format(process)
    )
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception as exc:
        log.debug("置前 mac 窗口失败: %s", exc)


def default_finder() -> WindowFinder:
    """工厂：按当前平台挑选默认窗口查找器。"""
    import sys

    if sys.platform == "win32":
        return Win32WindowFinder()
    if sys.platform == "darwin":
        return MacWindowFinder()
    return FullScreenFinder()


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
        self._finder = finder or default_finder()
        self._allow_fullscreen = (
            settings.FALLBACK_TO_FULLSCREEN if allow_fullscreen is None else allow_fullscreen
        )
        self._rect: Optional[WindowRect] = None

    @property
    def wid(self) -> Optional[int]:
        """macOS 窗口编号（非 mac / 未定位时为 None）。"""
        return self.rect.wid

    @property
    def pid(self) -> Optional[int]:
        """目标进程 PID（macOS 事件直投用；其它平台为 None）。"""
        return getattr(self._finder, "pid", None)

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
