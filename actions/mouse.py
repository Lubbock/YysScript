"""拟人化鼠标操作。

对应旧 scripts/a_base.py 里的 click / lock_click / personal_pause / next_page。
这一层只认**屏幕绝对坐标**，逻辑坐标换算由 GameController 负责。

拟人化手段：
- 落点随机抖动（不会每次都点同一个像素）
- 动作前后随机停顿（旧 personal_pause 的 0~1 秒）
- 拖动分多步并带缓动曲线，轨迹接近人手

macOS「礼貌点击」模式（controller 注入 pid_provider 后启用）：
镜像 / 游戏窗口只在自己是活跃 App 时才响应点击，而用户还要继续用电脑，
所以每次点击只做三件事，把干扰压到点击瞬间：
1. 记下用户光标位置与当前前台 App；
2. 用 System Events 短暂激活目标窗口 -> 把光标 warp 到目标点并**补发一个
   mouseMoved** -> 在同一个坐标发 down/up（不做光标移动动画）；
3. 立刻把光标 warp 回原位（同样补发 mouseMoved），并把焦点还给用户原来的 App。
轮询识别期间完全不碰鼠标与焦点。

为什么必须补发 mouseMoved（实测踩出来的坑）：
`CGWarpMouseCursorPosition` 只改窗口服务里的指针坐标，**不产生鼠标移动事件**。
目标 App 自己缓存的光标位置（hover 状态、Mac Catalyst 的指针->触摸桥接）不会跟着
更新，系统也要等下一次真实硬件移动才刷新。只 warp / 只按坐标发事件时，合成点击会
被静默丢掉，表现就是「跑一段时间后点不动，用户手动晃一下鼠标又恢复」。

两个实测结论（别再踩）：
- 命令行 Python 进程里 `NSRunningApplication.activateWithOptions_` 与
  `NSWorkspace.frontmostApplication()` 都不可信（前者不生效、后者返回过期值），
  前台的查询与设置一律走 System Events（osascript + unix id）；
- 合成点击（CGEventPost）需要当前进程链有「辅助功能」权限，否则被系统静默丢弃，
  用 accessibility_trusted() 自检（ctypes 直调，本机 pyobjc 缺 ApplicationServices 子包）。
"""
from __future__ import annotations

import logging
import random
import sys
import time
from typing import Callable, Optional, Tuple

import pyautogui

from config import settings
from core.logger import get_logger

log = get_logger(__name__)

ScreenPoint = Tuple[int, int]

pyautogui.FAILSAFE = settings.PYAUTOGUI_FAILSAFE
pyautogui.PAUSE = settings.PYAUTOGUI_PAUSE

# ------------------------------------------------------------------ 礼貌点击节奏
# down/up 之间按住多久（太短部分 App 会当成 hover）
_CLICK_HOLD: float = 0.06
# 光标落到目标点后、发点击前的稳定时间，让 App 先收到 mouseMoved
_MOVE_SETTLE: float = 0.02


def _tween(name: str):
    """取 pyautogui 缓动函数，取不到就返回 None（直线移动）。"""
    return getattr(pyautogui, name, None)


class HumanMouse:
    """带随机抖动与停顿的鼠标封装。"""

    def __init__(
        self,
        jitter: Optional[int] = None,
        pause_range: Optional[Tuple[float, float]] = None,
        humanize: bool = True,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.jitter = settings.HUMAN_JITTER if jitter is None else jitter
        self.pause_range = pause_range or settings.HUMAN_PAUSE_RANGE
        self.humanize = humanize
        self._rng = rng or random.Random()
        #: 返回目标进程 PID（macOS 礼貌点击用）；None 表示走 pyautogui 全局点击
        self.pid_provider: Optional[Callable[[], Optional[int]]] = None

    # ------------------------------------------------------------------ 基础
    def sleep_human(self) -> None:
        """随机停顿，模拟人操作之间的间隔。"""
        if not self.humanize:
            return
        low, high = self.pause_range
        if high > 0:
            time.sleep(self._rng.uniform(low, high))

    def _jitter(self, point: ScreenPoint) -> ScreenPoint:
        if not self.humanize or self.jitter <= 0:
            return int(point[0]), int(point[1])
        return (
            int(point[0]) + self._rng.randint(-self.jitter, self.jitter),
            int(point[1]) + self._rng.randint(-self.jitter, self.jitter),
        )

    # ------------------------------------------------------------------ 礼貌点击
    def _target_pid(self) -> Optional[int]:
        """macOS 且注入了 PID 时返回目标进程 PID，否则 None。"""
        if self.pid_provider is None or sys.platform != "darwin":
            return None
        pid = self.pid_provider()
        if not pid:
            return None
        try:
            import Quartz  # noqa: F401
        except ImportError:
            return None
        return pid

    def polite_click_available(self) -> bool:
        """当前是否走礼貌点击（不长时间占用光标 / 焦点）。"""
        return self._target_pid() is not None

    # ------------------------------------------------------------------ 动作
    def move_to(self, point: ScreenPoint, duration: float = 0.3) -> None:
        x, y = self._jitter(point)
        pyautogui.moveTo(x, y, duration=duration, tween=_tween("easeOutQuad"))

    def click(
        self,
        point: ScreenPoint,
        clicks: int = 1,
        button: str = "left",
        interval: float = 0.1,
        duration: float = 0.0,
        move_duration: float = 0.3,
    ) -> ScreenPoint:
        """移动到目标并点击，返回实际点击的屏幕坐标。

        礼貌点击模式下不播放光标移动动画：激活目标窗口、把光标 warp 到目标点
        （并补发 mouseMoved）后直接点击，随即还原用户光标与焦点。
        """
        target = self._jitter(point)
        pid = self._target_pid()
        if pid is not None:
            # 每次 _frontmost_pid() 都要起一个 osascript（约 0.4 秒），只在 debug 时才查
            trace = log.isEnabledFor(logging.DEBUG)
            log.info("礼貌点击: 目标 pid=%s 坐标=%s", pid, target)
            if trace:
                log.debug("礼貌点击: 点击前前台=%s", _frontmost_pid())
            with _polite_session(pid) as session:
                if trace:
                    log.debug("礼貌点击: 激活后前台=%s activated=%s",
                              _frontmost_pid(), session.activated)
                for index in range(max(1, clicks)):
                    _session_click(target)
                    if index + 1 < clicks:
                        time.sleep(interval)
            if trace:
                log.debug("礼貌点击: 归还后前台=%s", _frontmost_pid())
            self.sleep_human()
            return target
        pyautogui.moveTo(target[0], target[1], duration=move_duration,
                         tween=_tween("easeOutQuad"))
        pyautogui.click(
            x=target[0],
            y=target[1],
            clicks=clicks,
            interval=interval,
            button=button,
            duration=duration,
        )
        self.sleep_human()
        return target

    def double_click(self, point: ScreenPoint, duration: float = 0.0) -> ScreenPoint:
        return self.click(point, clicks=2, duration=duration)

    def drag(
        self,
        start: ScreenPoint,
        end: ScreenPoint,
        duration: float = 1.0,
        steps: Optional[int] = None,
    ) -> None:
        """从 start 拖到 end。分步移动 + 缓动曲线，轨迹更像人手划屏。"""
        steps = steps or settings.HUMAN_DRAG_STEPS
        sx, sy = self._jitter(start)
        ex, ey = self._jitter(end)
        pid = self._target_pid()
        if pid is not None:
            with _polite_session(pid):
                _session_drag((sx, sy), (ex, ey), steps, duration)
            self.sleep_human()
            return
        pyautogui.moveTo(sx, sy, duration=0.3, tween=_tween("easeOutQuad"))
        pyautogui.mouseDown(x=sx, y=sy)
        try:
            step_duration = max(duration / steps, 0.01)
            for i in range(1, steps + 1):
                ratio = i / steps
                pyautogui.moveTo(
                    int(sx + (ex - sx) * ratio),
                    int(sy + (ey - sy) * ratio),
                    duration=step_duration,
                )
        finally:
            pyautogui.mouseUp(x=ex, y=ey)
        self.sleep_human()

    def scroll(self, clicks: int, point: Optional[ScreenPoint] = None, pause: float = 0.5) -> None:
        """在指定位置滚动滚轮。"""
        target_point = None if point is None else self._jitter(point)
        pid = self._target_pid()
        if pid is not None:
            with _polite_session(pid):
                _session_scroll(clicks, target_point)
            time.sleep(pause)
            return
        if point is not None:
            x, y = self._jitter(point)
            pyautogui.moveTo(x, y, duration=0.2)
        pyautogui.scroll(clicks)
        time.sleep(pause)


# --------------------------------------------------------------------------- #
# 权限自检
# --------------------------------------------------------------------------- #
def accessibility_trusted() -> bool:
    """当前进程链是否拥有 macOS 辅助功能权限。

    没有该权限时 CGEventPost 发出的合成点击会被系统**静默丢弃**（不报错、
    手机也没反应），是「脚本跑了但不点击」最常见的原因。
    用 ctypes 直调 ApplicationServices，避免依赖 pyobjc 的对应子包。
    """
    if sys.platform != "darwin":
        return True
    try:
        import ctypes

        lib = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/"
            "Versions/A/ApplicationServices")
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(lib.AXIsProcessTrusted())
    except Exception:
        return True


# --------------------------------------------------------------------------- #
# macOS 礼貌点击：点击瞬间激活目标窗口，点完立刻还原光标与用户焦点
# --------------------------------------------------------------------------- #
class _polite_session:
    """点击期间的上下文：激活目标进程，退出时还原光标与前台 App。"""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.prev_pid: Optional[int] = None
        self.activated = False
        self.old_xy: Optional[Tuple[float, float]] = None
        self._activate_err = ""

    def __enter__(self):
        from AppKit import NSEvent, NSScreen

        loc = NSEvent.mouseLocation()
        height = NSScreen.mainScreen().frame().size.height
        self.old_xy = (loc.x, height - loc.y)
        # 注意：命令行 Python 进程里 NSWorkspace.frontmostApplication() 返回的是
        # 过期值（实测系统已切换前台它仍报旧 App），前台判定必须走 System Events。
        self.prev_pid = _frontmost_pid()
        if self.prev_pid != self.pid:
            self._activate_err = _set_frontmost(self.pid)
            self.activated = _wait_frontmost(self.pid, timeout=1.5)
            if not self.activated:
                raise RuntimeError(
                    "无法激活目标窗口（pid={}），放弃本次点击。{}"
                    "若反复出现：系统设置 -> 隐私与安全性 -> 自动化，"
                    "允许你的终端控制 System Events。".format(
                        self.pid,
                        "osascript: {} ".format(self._activate_err) if self._activate_err else "",
                    )
                )
        # 显示器休眠时点击根本送不到目标窗口，先给一次明确提示（只在状态跳变时记日志）
        _warn_if_display_asleep()
        return self

    def __exit__(self, *exc_info) -> None:
        if self.old_xy is not None:
            # warp 回原位也必须补发 mouseMoved：否则目标 App 仍以为光标停在点击点，
            # 要等用户真的动一次鼠标才刷新（「不动鼠标就点不动」的另一半原因）
            _warp_to(self.old_xy, settle=0.0)
        if self.activated and self.prev_pid is not None:
            # 用户在这期间自己切了别的应用就不打扰，只在我们抢来的焦点还在时归还
            if _frontmost_pid() == self.pid:
                _set_frontmost(self.prev_pid)
        return False


def _frontmost_pid() -> Optional[int]:
    """当前前台进程 PID（走 System Events；NSWorkspace 在命令行进程里不可信）。"""
    import subprocess

    script = (
        'tell application "System Events" to get unix id of '
        "first application process whose frontmost is true"
    )
    try:
        out = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        return int(out) if out else None
    except Exception:
        return None


def _set_frontmost(pid: int) -> str:
    """用 System Events 把指定进程置前，返回 osascript 的报错（空串表示无报错）。"""
    import subprocess

    script = (
        'tell application "System Events" to set frontmost of '
        "(first process whose unix id is {}) to true".format(pid)
    )
    try:
        proc = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=5,
        )
        return proc.stderr.strip()
    except Exception as exc:
        return str(exc)


def _wait_frontmost(pid: int, timeout: float = 1.5) -> bool:
    """轮询等待目标进程成为前台，激活真的生效后才允许点击。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _frontmost_pid() == pid:
            return True
        time.sleep(0.12)
    return False


# --------------------------------------------------------------------------- #
# 指针同步：warp + 补发 mouseMoved（礼貌点击的地基）
# --------------------------------------------------------------------------- #
def _warp_to(point: ScreenPoint, settle: float = _MOVE_SETTLE) -> None:
    """把光标放到 point，并补发一个同坐标的 mouseMoved。

    只用 `CGWarpMouseCursorPosition` 有两个坑：
    1. 它**不产生鼠标移动事件**，目标 App 缓存的光标位置（hover 状态、
       Mac Catalyst 的指针->触摸桥接）仍是旧值，随后按坐标发的 down/up
       会被丢掉，要等用户真的动一次鼠标才恢复；
    2. 它不重置硬件累计位移，下一次真实移动会把光标拽回旧基准 + delta，
       所以 warp 前后各切一次 associate，点完再补发事件。
    """
    import Quartz

    x, y = float(point[0]), float(point[1])
    Quartz.CGAssociateMouseAndMouseCursorPosition(False)
    Quartz.CGWarpMouseCursorPosition((x, y))
    moved = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventMouseMoved, (x, y), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(Quartz.kCGSessionEventTap, moved)
    Quartz.CGAssociateMouseAndMouseCursorPosition(True)
    if settle:
        time.sleep(settle)


def _cursor_position() -> ScreenPoint:
    """当前系统光标位置（屏幕绝对坐标），仅供 debug 核对指针是否真的落到位。"""
    import Quartz

    loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return int(loc.x), int(loc.y)


def _main_display_asleep() -> bool:
    """主显示器是否已休眠。休眠时合成事件落进睡着的窗口服务器，手机不会有任何
    反应，表现同样是「不动鼠标就不生效」，但这一条脚本修不了，只能提示用户。
    """
    try:
        import Quartz

        return bool(Quartz.CGDisplayIsAsleep(Quartz.CGMainDisplayID()))
    except Exception:
        return False


_asleep_logged: Optional[bool] = None


def _warn_if_display_asleep() -> None:
    """只在状态跳变时告警一次，避免每次点击都刷日志。"""
    global _asleep_logged
    asleep = _main_display_asleep()
    if asleep != _asleep_logged:
        _asleep_logged = asleep
        if asleep:
            log.warning("主显示器处于休眠状态，此时的点击不会送达目标窗口；"
                        "动一下鼠标唤醒屏幕，或设置里关闭显示器自动休眠")


def _session_click(point: ScreenPoint) -> None:
    import Quartz

    _warp_to(point)
    if log.isEnabledFor(logging.DEBUG):
        log.debug("礼貌点击: 指针落点 %s，系统光标实际 %s", point, _cursor_position())
    x, y = float(point[0]), float(point[1])
    down = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventLeftMouseDown, (x, y), Quartz.kCGMouseButtonLeft)
    up = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventLeftMouseUp, (x, y), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(Quartz.kCGSessionEventTap, down)
    time.sleep(_CLICK_HOLD)
    Quartz.CGEventPost(Quartz.kCGSessionEventTap, up)


def _session_drag(
    start: ScreenPoint,
    end: ScreenPoint,
    steps: int,
    duration: float,
) -> None:
    import Quartz

    sx, sy = float(start[0]), float(start[1])
    ex, ey = float(end[0]), float(end[1])
    _warp_to(start)
    down = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventLeftMouseDown, (sx, sy), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(Quartz.kCGSessionEventTap, down)
    step_duration = max(duration / steps, 0.01)
    for i in range(1, steps + 1):
        ratio = i / steps
        pos = (sx + (ex - sx) * ratio, sy + (ey - sy) * ratio)
        # 每一步都让指针跟到位，否则 App 侧的拖拽轨迹仍停在起点
        _warp_to(pos, settle=0.0)
        moved = Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventLeftMouseDragged, pos, Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGSessionEventTap, moved)
        time.sleep(step_duration)
    up = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventLeftMouseUp, (ex, ey), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(Quartz.kCGSessionEventTap, up)


def _session_scroll(clicks: int, point: Optional[ScreenPoint] = None) -> None:
    """滚动事件本身不带坐标，系统按当前光标位置决定「滚谁」，所以要先落点。"""
    import Quartz

    if point is not None:
        _warp_to(point)
    event = Quartz.CGEventCreateScrollWheelEvent(
        None, Quartz.kCGScrollEventUnitLine, 1, int(clicks))
    Quartz.CGEventPost(Quartz.kCGSessionEventTap, event)
