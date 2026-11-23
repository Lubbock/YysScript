"""点击执行：标注坐标 → 视口换算 → 拟人化鼠标。"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from config import settings
from core.logger import get_logger
from runner.errors import ClickError
from runner.group import AnnotationRef, ShotRef
from runner.session import ClickResult, Session

log = get_logger(__name__)


@dataclass(frozen=True)
class ClickOutcome:
    """一次点击的结果。"""

    ok: bool
    attempts: int
    result: Optional[ClickResult] = None
    reason: str = ""

    def describe(self) -> str:
        if self.result is None:
            return "未点击（{}）".format(self.reason or "无标注")
        return "{}，尝试 {} 次".format(self.result.describe, self.attempts)


class Actor:
    """把「点某个标注」这件事包起来：停顿、重试、日志。"""

    def __init__(
        self,
        session: Session,
        settle: Optional[float] = None,
        attempts: Optional[int] = None,
        retry_pause: Optional[float] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.session = session
        self.settle = settings.RUNNER_SETTLE_PAUSE if settle is None else float(settle)
        self.attempts = (settings.ACTIVATE_MAX_ATTEMPTS if attempts is None
                         else max(1, int(attempts)))
        self.retry_pause = (settings.ACTIVATE_RETRY_PAUSE if retry_pause is None
                            else float(retry_pause))
        self._sleep = sleep
        self.clicks = 0

    def pause(self, seconds: Optional[float] = None) -> None:
        """命中后、点击前的停顿。"""
        delay = self.settle if seconds is None else float(seconds)
        if delay > 0:
            self._sleep(delay)

    def click_annotation(self, shot: ShotRef, annotation: AnnotationRef,
                         settle: Optional[float] = None,
                         clicks: int = 1) -> ClickOutcome:
        """点击标注，激活失败时重试。"""
        self.pause(settle)
        result: Optional[ClickResult] = None
        for attempt in range(1, self.attempts + 1):
            try:
                result = self.session.click_annotation(shot, annotation, clicks=clicks)
            except Exception as exc:
                raise ClickError("点击 {} 失败 {}: {}".format(
                    annotation.describe(), type(exc).__name__, exc))
            if result.clicked:
                self.clicks += 1
                log.info("点击 %s -> %s", annotation.describe(), result.describe)
                return ClickOutcome(ok=True, attempts=attempt, result=result)
            log.warning("第 %d/%d 次点击未送达（窗口激活失败）：%s",
                        attempt, self.attempts, annotation.describe())
            if attempt < self.attempts and self.retry_pause > 0:
                self._sleep(self.retry_pause)
        return ClickOutcome(ok=False, attempts=self.attempts, result=result,
                            reason="窗口激活连续失败 {} 次".format(self.attempts))

    def click_label(self, shot: ShotRef, label: Optional[str] = None,
                    settle: Optional[float] = None, clicks: int = 1) -> ClickOutcome:
        """按标注名点击；不给名字就点该图唯一的标注。"""
        if label:
            annotation = shot.find(label)
            if annotation is None:
                raise ClickError("截图 {} 里没有名为「{}」的标注，可选：{}".format(
                    shot.id, label, ", ".join(shot.labels()) or "无"))
        else:
            annotation = shot.only()
        return self.click_annotation(shot, annotation, settle=settle, clicks=clicks)
