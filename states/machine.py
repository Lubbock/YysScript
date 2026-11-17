"""状态机：用模板匹配判断当前界面，并提供等待 / 轮询原语。

对应旧 scripts/a_base.py 的 lock_wait / lock_wait_lost，以及 utils/MapCv 的判断函数。
改进点：
1. 等待超时抛 StateTimeoutError（旧代码有的分支 exit(300)，有的只打日志继续跑，行为不一致）；
2. 支持一次检测多个候选状态，返回**置信度最高**的那个，流程可以据此分支；
3. 每轮等待可以带 on_wait 回调（旧 loop_action），用于「边等边点」。

本模块不直接依赖 cv2 / pyautogui，matcher 由外部注入，方便单测。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Iterable, List, Optional, Sequence

from config import settings
from core.errors import StateTimeoutError
from core.logger import get_logger
from states.base import State, as_coerce

if TYPE_CHECKING:  # 仅类型标注：避免 states 层在运行时依赖 cv2 / pyautogui
    from vision.types import Match

log = get_logger(__name__)

#: 等待期间的回调，参数是已经轮询的次数
WaitHook = Callable[[int], None]


@dataclass(frozen=True)
class Detection:
    """一次状态命中结果。"""

    state: State
    match: Optional[Match] = None

    @property
    def score(self) -> float:
        return self.match.score if self.match else 0.0

    @property
    def key(self) -> str:
        return self.state.key


class StateMachine:
    """界面状态识别 + 等待。"""

    def __init__(self, matcher) -> None:
        self._matcher = matcher

    # ------------------------------------------------------------------ 识别
    def is_active(self, state, threshold: Optional[float] = None) -> bool:
        """state 对应的界面当前是否显示。"""
        state = as_coerce(state)
        return self.locate(state, threshold=threshold) is not None

    def locate(self, state, threshold: Optional[float] = None) -> Optional[Match]:
        """定位状态的主模板，返回最佳命中。"""
        state = as_coerce(state)
        best: Optional[Match] = None
        for template in state.templates:
            match = self._matcher.match(
                template,
                threshold=threshold if threshold is not None else state.threshold,
            )
            if match is not None and (best is None or match.score > best.score):
                best = match
        return best

    def locate_all(self, state, threshold: Optional[float] = None,
                   limit: Optional[int] = None) -> List[Match]:
        """定位状态模板的全部命中（例如地图上多个「满」标记）。"""
        state = as_coerce(state)
        results: List[Match] = []
        for template in state.templates:
            results.extend(
                self._matcher.match_all(
                    template,
                    threshold=threshold if threshold is not None else state.threshold,
                    limit=limit,
                )
            )
        return sorted(results, key=lambda m: m.score, reverse=True)

    def detect(self, candidates: Sequence) -> Optional[Detection]:
        """在候选状态里找出当前命中的那个（置信度最高者）。"""
        best: Optional[Detection] = None
        for candidate in candidates:
            match = self.locate(candidate)
            if match is None:
                continue
            if best is None or match.score > best.score:
                best = Detection(state=as_coerce(candidate), match=match)
        return best

    def detect_first(self, candidates: Sequence) -> Optional[Detection]:
        """按给定顺序返回第一个命中的状态（顺序即优先级，比 detect 快）。"""
        for candidate in candidates:
            match = self.locate(candidate)
            if match is not None:
                return Detection(state=as_coerce(candidate), match=match)
        return None

    # ------------------------------------------------------------------ 等待
    def wait_for(
        self,
        state,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        on_wait: Optional[WaitHook] = None,
        raise_on_timeout: bool = False,
    ) -> bool:
        """轮询直到 state 出现。

        返回 True 表示等到了；超时返回 False，raise_on_timeout=True 时改抛异常。
        """
        state = as_coerce(state)
        timeout = settings.DEFAULT_WAIT_TIMEOUT if timeout is None else timeout
        interval = settings.DEFAULT_WAIT_INTERVAL if interval is None else interval

        waited = 0.0
        rounds = 0
        while True:
            # 每轮只识别一次：旧写法在命中后会再截一次屏，白做一次模板匹配
            if self.is_active(state):
                log.info("已进入状态 %s（等待 %.1f 秒）", state, waited)
                return True
            rounds += 1
            if on_wait is not None:
                on_wait(rounds)
            if waited >= timeout:
                break
            time.sleep(interval)
            waited += interval

        log.error("等待状态 %s 超时（%.1f 秒）", state, timeout)
        if raise_on_timeout:
            raise StateTimeoutError(state.key, timeout)
        return False

    def wait_gone(
        self,
        state,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        on_wait: Optional[WaitHook] = None,
        raise_on_timeout: bool = False,
    ) -> bool:
        """轮询直到 state 消失（例如战斗中的「准备」按钮不再出现）。"""
        state = as_coerce(state)
        timeout = settings.DEFAULT_WAIT_TIMEOUT if timeout is None else timeout
        interval = settings.DEFAULT_WAIT_INTERVAL if interval is None else interval

        waited = 0.0
        rounds = 0
        while True:
            # 每轮只识别一次，同上
            if not self.is_active(state):
                log.info("状态 %s 已消失（等待 %.1f 秒）", state, waited)
                return True
            rounds += 1
            if on_wait is not None:
                on_wait(rounds)
            if waited >= timeout:
                break
            time.sleep(interval)
            waited += interval

        log.error("状态 %s 未消失，超时 %.1f 秒", state, timeout)
        if raise_on_timeout:
            raise StateTimeoutError(state.key, timeout)
        return False

    def wait_any(
        self,
        candidates: Iterable,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        on_wait: Optional[WaitHook] = None,
    ) -> Optional[Detection]:
        """等待候选状态中任意一个出现，返回命中结果；超时返回 None。"""
        candidates = [as_coerce(c) for c in candidates]
        timeout = settings.DEFAULT_WAIT_TIMEOUT if timeout is None else timeout
        interval = settings.DEFAULT_WAIT_INTERVAL if interval is None else interval

        waited = 0.0
        rounds = 0
        while True:
            detection = self.detect_first(candidates)
            if detection is not None:
                log.info("命中状态 %s（等待 %.1f 秒）", detection.state, waited)
                return detection
            rounds += 1
            if on_wait is not None:
                on_wait(rounds)
            if waited >= timeout:
                log.error("等待任意状态 %s 超时（%.1f 秒）",
                          [c.key for c in candidates], timeout)
                return None
            time.sleep(interval)
            waited += interval

    def expect(
        self,
        state,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        on_wait: Optional[WaitHook] = None,
    ) -> bool:
        """wait_for 的严格版：等不到直接抛 StateTimeoutError。"""
        return self.wait_for(state, timeout=timeout, interval=interval,
                             on_wait=on_wait, raise_on_timeout=True)
