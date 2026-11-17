"""拟人化鼠标操作。

对应旧 scripts/a_base.py 里的 click / lock_click / personal_pause / next_page。
这一层只认**屏幕绝对坐标**，逻辑坐标换算由 GameController 负责。

拟人化手段：
- 落点随机抖动（不会每次都点同一个像素）
- 动作前后随机停顿（旧 personal_pause 的 0~1 秒）
- 拖动分多步并带缓动曲线，轨迹接近人手
"""
from __future__ import annotations

import random
import time
from typing import Optional, Tuple

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
        """移动到目标并点击，返回实际点击的屏幕坐标。"""
        target = self._jitter(point)
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
        """从 start 拖到 end。分步移动 + 缓动，轨迹更像人手划屏。"""
        steps = steps or settings.HUMAN_DRAG_STEPS
        sx, sy = self._jitter(start)
        ex, ey = self._jitter(end)
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
        if point is not None:
            x, y = self._jitter(point)
            pyautogui.moveTo(x, y, duration=0.2)
        pyautogui.scroll(clicks)
        time.sleep(pause)
