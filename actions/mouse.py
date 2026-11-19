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
2. 短暂激活目标窗口 -> 在坐标上会话级点击（不做光标移动动画）；
3. 立刻把光标 warp 回原位，并把焦点还给用户原来的 App。
轮询识别期间完全不碰鼠标与焦点。
"""
from __future__ import annotations

import random
import sys
import time
from typing import Callable, Optional, Tuple

import pyautogui

from config import settings

ScreenPoint = Tuple[int, int]

pyautogui.FAILSAFE = settings.PYAUTOGUI_FAILSAFE
pyautogui.PAUSE = settings.PYAUTOGUI_PAUSE


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

        礼貌点击模式下不播放光标移动动画：激活目标窗口后在坐标上直接点击，
        随即还原用户光标与焦点。
        """
        target = self._jitter(point)
        pid = self._target_pid()
        if pid is not None:
            with _polite_session(pid):
                for index in range(max(1, clicks)):
                    _session_click(target)
                    if index + 1 < clicks:
                        time.sleep(interval)
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
        pid = self._target_pid()
        if pid is not None:
            with _polite_session(pid):
                _session_scroll(clicks)
            time.sleep(pause)
            return
        if point is not None:
            x, y = self._jitter(point)
            pyautogui.moveTo(x, y, duration=0.2)
        pyautogui.scroll(clicks)
        time.sleep(pause)


# --------------------------------------------------------------------------- #
# macOS 礼貌点击：点击瞬间激活目标窗口，点完立刻还原光标与用户焦点
# --------------------------------------------------------------------------- #
_ACTIVATE_IGNORING_OTHERS = 1 << 1


class _polite_session:
    """点击期间的上下文：激活目标进程，退出时还原光标与前台 App。"""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.prev_app = None
        self.activated = False
        self.old_xy: Optional[Tuple[float, float]] = None

    def __enter__(self):
        import Quartz
        from AppKit import NSEvent, NSScreen, NSWorkspace

        ws = NSWorkspace.sharedWorkspace()
        self.prev_app = ws.frontmostApplication()
        loc = NSEvent.mouseLocation()
        height = NSScreen.mainScreen().frame().size.height
        self.old_xy = (loc.x, height - loc.y)
        if self.prev_app is None or self.prev_app.processIdentifier() != self.pid:
            app = _app_for_pid(self.pid)
            if app is not None:
                app.activateWithOptions_(_ACTIVATE_IGNORING_OTHERS)
                self.activated = True
                time.sleep(0.15)  # 等激活生效，避免点击落在旧前台窗口上
        return self

    def __exit__(self, *exc_info) -> None:
        import Quartz

        if self.old_xy is not None:
            Quartz.CGWarpMouseCursorPosition(self.old_xy)
            Quartz.CGAssociateMouseAndMouseCursorPosition(True)
        if self.activated and self.prev_app is not None:
            time.sleep(0.2)
            ws = NSWorkspace.sharedWorkspace()
            current = ws.frontmostApplication()
            # 用户在这期间自己切了别的应用就不打扰，只在我们抢来的焦点还在时归还
            if current is not None and current.processIdentifier() == self.pid:
                self.prev_app.activateWithOptions_(_ACTIVATE_IGNORING_OTHERS)
        return False


def _app_for_pid(pid: int):
    from AppKit import NSWorkspace

    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.processIdentifier() == pid:
            return app
    return None


def _session_click(point: ScreenPoint) -> None:
    import Quartz

    x, y = float(point[0]), float(point[1])
    down = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventLeftMouseDown, (x, y), Quartz.kCGMouseButtonLeft)
    up = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventLeftMouseUp, (x, y), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(Quartz.kCGSessionEventTap, down)
    time.sleep(0.06)
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
    down = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventLeftMouseDown, (sx, sy), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(Quartz.kCGSessionEventTap, down)
    step_duration = max(duration / steps, 0.01)
    for i in range(1, steps + 1):
        ratio = i / steps
        moved = Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventLeftMouseDragged,
            (sx + (ex - sx) * ratio, sy + (ey - sy) * ratio),
            Quartz.kCGMouseButtonLeft,
        )
        Quartz.CGEventPost(Quartz.kCGSessionEventTap, moved)
        time.sleep(step_duration)
    up = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventLeftMouseUp, (ex, ey), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(Quartz.kCGSessionEventTap, up)


def _session_scroll(clicks: int) -> None:
    import Quartz

    event = Quartz.CGEventCreateScrollWheelEvent(
        None, Quartz.kCGScrollEventUnitLine, 1, int(clicks))
    Quartz.CGEventPost(Quartz.kCGSessionEventTap, event)
