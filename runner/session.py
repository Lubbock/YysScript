"""会话：窗口 + 截屏 + 视口 + 拟人化鼠标。

坐标语义（三套）：
    标注坐标   截图原始像素，原点 = 截图左上角，来自 similarity 数据集
    逻辑坐标   基准客户区 1024x768，config/coordinates.Point
    屏幕坐标   显示器绝对像素，HumanMouse 只认这个

标注坐标 → 屏幕坐标要过**两次** Viewport：
    1. 用「采集时」的窗口矩形把标注像素还原成屏幕坐标，再 to_logical 得到逻辑坐标；
    2. 用「当前」的窗口矩形 to_screen 得到现在的屏幕坐标。
这样采集之后窗口被拖动或缩放，点击位置依然落在同一个界面元素上。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Tuple

if TYPE_CHECKING:
    from actions.mouse import HumanMouse
from actions.viewport import Viewport
from actions.window import GameWindow, WindowRect, create_window
from config.coordinates import Point
from core.logger import get_logger
from runner.errors import ClickError, RunnerError
from runner.group import AnnotationRef, ShotRef
from vision.types import Frame

log = get_logger(__name__)

ScreenPoint = Tuple[int, int]


@dataclass(frozen=True)
class ClickResult:
    """一次点击的结果。"""

    logical: Point
    screen: Optional[ScreenPoint]
    clicked: bool
    annotation: Optional[AnnotationRef] = None

    @property
    def describe(self) -> str:
        where = "逻辑({},{})".format(self.logical.x, self.logical.y)
        if self.screen:
            where += " 屏幕({},{})".format(self.screen[0], self.screen[1])
        state = "已点击" if self.clicked else "被跳过（窗口激活失败）"
        return "{} {}".format(where, state)


class Session:
    """一次运行期会话。"""

    def __init__(
        self,
        window: Optional[GameWindow] = None,
        mouse: Optional[HumanMouse] = None,
        capture: Optional[Any] = None,
        debug: bool = False,
    ) -> None:
        self.window = window or create_window()
        self.mouse = mouse or _new_mouse()
        self.mouse.pid_provider = self._pid
        self.debug = debug
        self._capture = capture
        self._rect: Optional[WindowRect] = None

    @property
    def capture(self) -> Any:
        """截屏器，首次用到时才建（避免导入期就依赖 cv2）。"""
        if self._capture is None:
            from vision.capture import ScreenCapture

            self._capture = ScreenCapture(region_provider=self._region)
        return self._capture

    def _region(self) -> Optional[Tuple[int, int, int, int]]:
        try:
            return self.window.region
        except Exception as exc:
            log.warning("获取窗口区域失败，改用全屏截图: %s", exc)
            return None


    def _pid(self) -> Optional[int]:
        try:
            return self.window.pid
        except Exception:
            return None

    def rect(self, refresh: bool = False) -> WindowRect:
        """当前窗口客户区。"""
        if refresh or self._rect is None:
            self._rect = self.window.refresh()
        return self._rect

    def viewport(self, refresh: bool = False) -> Viewport:
        """当前窗口的坐标换算器。"""
        rect = self.rect(refresh=refresh)
        return Viewport(origin=rect.origin, size=rect.size)

    def focus(self) -> None:
        """把窗口置前。"""
        self.window.focus()

    def grab(self) -> Tuple[bytes, Frame]:
        """截屏，返回 (PNG 字节, Frame)。"""
        frame = self.capture.grab()
        png = encode_png(frame.image)
        return png, frame

    def capture_viewport(self, shot: ShotRef) -> Viewport:
        """采集那张图时的窗口换算器。"""
        left, top, width, height = shot.region
        if width <= 0 or height <= 0:
            raise RunnerError(
                "截图 {} 的窗口区域非法 {}，无法换算坐标".format(shot.id, shot.region))
        return Viewport(origin=(left, top), size=(width, height))

    def resolve(self, shot: ShotRef, x: int, y: int,
                refresh: bool = True) -> Tuple[Point, ScreenPoint]:
        """标注像素 → 逻辑坐标 → 当前屏幕坐标。"""
        left, top = shot.origin
        past = self.capture_viewport(shot)
        logical = past.to_logical((left + int(x), top + int(y)))
        current = self.viewport(refresh=refresh)
        return logical, current.to_screen(logical)

    def click_annotation(self, shot: ShotRef, annotation: AnnotationRef,
                         clicks: int = 1) -> ClickResult:
        """点击一个标注。"""
        logical, screen = self.resolve(shot, annotation.x, annotation.y)
        landed = self.mouse.click(screen, clicks=clicks)
        if landed is None:
            log.warning("点击被跳过（窗口激活失败），标注 %s", annotation.describe())
        return ClickResult(logical=logical, screen=landed or screen,
                           clicked=landed is not None, annotation=annotation)

    def click_logical(self, point: Point, clicks: int = 1) -> ClickResult:
        """点击一个逻辑坐标。"""
        screen = self.viewport(refresh=True).to_screen(point)
        landed = self.mouse.click(screen, clicks=clicks)
        return ClickResult(logical=point, screen=landed or screen,
                           clicked=landed is not None)

    def click_screen(self, point: ScreenPoint, clicks: int = 1) -> ClickResult:
        """点击一个屏幕绝对坐标。"""
        landed = self.mouse.click(tuple(int(v) for v in point), clicks=clicks)
        logical = self.viewport().to_logical(tuple(int(v) for v in point))
        return ClickResult(logical=logical, screen=landed or tuple(point),
                           clicked=landed is not None)

    def describe_window(self) -> str:
        """一行窗口信息。"""
        rect = self.rect()
        view = self.viewport()
        return ("窗口 {}x{} @({},{}) 缩放 x={:.3f} y={:.3f}{}".format(
            rect.width, rect.height, rect.left, rect.top,
            view.scale_x, view.scale_y,
            " wid={}".format(rect.wid) if rect.wid else ""))


def encode_png(image: Any) -> bytes:
    """BGR 数组编码成 PNG 字节。"""
    import cv2

    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise ClickError("截图 PNG 编码失败")
    return buffer.tobytes()


def _new_mouse() -> Any:
    """惰性构造拟人化鼠标。"""
    from actions.mouse import HumanMouse

    return HumanMouse()
