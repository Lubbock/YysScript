"""操作层门面：GameController。

流程代码（flows）只跟这个类打交道：
    controller.click(EXPLORE_ENTRY)          # 逻辑坐标（config/coordinates.py）
    controller.click(match)                  # 识别结果（vision 输出的屏幕坐标）
    controller.drag(EXPLORE_PAGE_FROM, ...)  # 拖动翻页
    controller.locate("第九章.png")           # 直接按模板名定位

窗口定位 + 坐标换算 + 拟人化点击都在这里组合完成，
所以「换分辨率 / 窗口不在原点」只需要改 actions 层，flows 完全不用动。
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple, Union

from actions.mouse import HumanMouse
from actions.viewport import Viewport
from actions.window import GameWindow, WindowRect, create_window
from config.coordinates import Point
from core.logger import get_logger
from vision.capture import ScreenCapture
from vision.color_detector import MonsterDetector
from vision.template_matcher import TemplateMatcher
from vision.types import Box, Frame, Match

log = get_logger(__name__)

ScreenPoint = Tuple[int, int]
#: 可点击目标：逻辑坐标 / 识别结果 / 屏幕坐标
ClickTarget = Union[Point, Match, Box, ScreenPoint, Sequence[int]]


class GameController:
    """游戏窗口上的操作与识别入口。"""

    def __init__(
        self,
        window: Optional[GameWindow] = None,
        mouse: Optional[HumanMouse] = None,
        viewport: Optional[Viewport] = None,
        debug: bool = False,
    ) -> None:
        self.window = window or create_window()
        self.mouse = mouse or HumanMouse()
        # macOS 事件直投：点击只送进游戏/镜像进程，不抢用户光标与焦点
        self.mouse.pid_provider = self._window_pid
        self._viewport = viewport
        # 截屏区域绑定到游戏窗口：只截窗口，既快又能避免桌面其它窗口造成误匹配
        self.capture = ScreenCapture(
            region_provider=self._region,
            window_id_provider=self._window_id,
        )
        self.matcher = TemplateMatcher(capture=self.capture)
        self.detector = MonsterDetector(capture=self.capture, debug=debug)

    # ------------------------------------------------------------------ 窗口
    def _region(self) -> Optional[Tuple[int, int, int, int]]:
        try:
            return self.window.region
        except Exception as exc:  # 窗口丢失时退回全屏截图
            log.warning("获取窗口区域失败，改用全屏截图: %s", exc)
            return None


    def _window_id(self) -> Optional[int]:
        """macOS 镜像窗口编号；其它平台 / 未定位时为 None。"""
        try:
            return self.window.wid
        except Exception as exc:
            log.debug("获取窗口编号失败: %s", exc)
            return None
    def _window_pid(self) -> Optional[int]:
        """目标进程 PID（事件直投）；不可用时 None。"""
        try:
            return self.window.pid
        except Exception as exc:
            log.debug("获取窗口 PID 失败: %s", exc)
            return None

    @property
    def viewport(self) -> Viewport:
        """当前坐标换算器；窗口移动 / 改变大小后调用 refresh_window() 刷新。"""
        if self._viewport is None:
            rect: WindowRect = self.window.rect
            self._viewport = Viewport(origin=rect.origin, size=rect.size)
        return self._viewport

    def refresh_window(self) -> WindowRect:
        """重新定位游戏窗口并重建换算器。"""
        rect = self.window.refresh()
        self._viewport = Viewport(origin=rect.origin, size=rect.size)
        log.info("窗口已刷新: %s，缩放比例 x=%.3f y=%.3f",
                 rect, self._viewport.scale_x, self._viewport.scale_y)
        return rect

    def focus(self) -> None:
        """把游戏窗口置前。"""
        self.window.focus()

    # ------------------------------------------------------------------ 坐标
    def to_screen(self, point: Point) -> ScreenPoint:
        """逻辑坐标 -> 屏幕坐标。"""
        return self.viewport.to_screen(point)

    def to_logical(self, screen: ScreenPoint) -> Point:
        """屏幕坐标 -> 逻辑坐标。"""
        return self.viewport.to_logical(screen)

    def resolve(self, target: ClickTarget) -> ScreenPoint:
        """把各种形式的点击目标统一解析成屏幕绝对坐标。

        - Point                 : 逻辑坐标，按窗口换算
        - Match / Box           : 识别结果，取中心点（已是屏幕坐标）
        - (x, y) / [x, y]       : 屏幕绝对坐标，原样使用
        """
        if isinstance(target, (Match, Box)):
            return target.center
        if isinstance(target, Point):
            return self.to_screen(target)
        if isinstance(target, (tuple, list)) and len(target) == 2:
            return int(target[0]), int(target[1])
        raise TypeError("无法识别的点击目标: {!r}".format(target))

    # ------------------------------------------------------------------ 操作
    def click(
        self,
        target: ClickTarget,
        clicks: int = 1,
        button: str = "left",
        duration: float = 0.0,
        interval: float = 0.1,
    ) -> Optional[ScreenPoint]:
        """点击目标（自动处理逻辑坐标 / 识别结果 / 屏幕坐标）。

        返回实际点击的屏幕坐标；**窗口激活失败导致点击被跳过时返回 None**，
        调用方应据此判断动作是否真的送达。
        """
        screen = self.resolve(target)
        log.debug("click %s -> 屏幕 %s", target, screen)
        return self.mouse.click(screen, clicks=clicks, button=button,
                                duration=duration, interval=interval)

    def double_click(self, target: ClickTarget,
                     duration: float = 0.0) -> Optional[ScreenPoint]:
        return self.click(target, clicks=2, duration=duration)

    def drag(
        self,
        start: ClickTarget,
        end: ClickTarget,
        duration: float = 1.0,
        steps: Optional[int] = None,
    ) -> None:
        """从 start 拖到 end（两者都可以是逻辑坐标或屏幕坐标）。"""
        self.mouse.drag(self.resolve(start), self.resolve(end), duration=duration, steps=steps)

    def scroll(self, clicks: int, at: Optional[ClickTarget] = None, pause: float = 0.5) -> None:
        """滚动滚轮，at 为空时在当前位置滚动。"""
        self.mouse.scroll(clicks, None if at is None else self.resolve(at), pause=pause)

    def sleep(self, seconds: float) -> None:
        import time

        time.sleep(seconds)

    # ------------------------------------------------------------------ 识别
    def screenshot(self) -> Frame:
        """截取游戏窗口画面。"""
        return self.capture.grab()

    def locate(
        self,
        filename: str,
        threshold: Optional[float] = None,
    ) -> Optional[Match]:
        """按模板文件名定位，返回最佳命中。"""
        return self.matcher.match(filename, threshold=threshold)

    def locate_all(
        self,
        filename: str,
        threshold: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> List[Match]:
        """按模板文件名定位全部命中。"""
        return self.matcher.match_all(filename, threshold=threshold, limit=limit)

    def find_monsters(self, exp_only: bool = False) -> List[Box]:
        """用颜色检测找地图上的怪物（比模板匹配快，用于探索扫怪）。"""
        return self.detector.find_monsters(exp_only=exp_only)
