"""流程基类：把「状态机 + 操作器」组合成可复用的动作原语。

flows 下的每个功能都继承 Flow，只写业务编排，不直接碰 pyautogui / cv2：
- 判断界面  -> self.is_active(STATE) / self.machine.detect([...])
- 等界面    -> self.wait(STATE, on_wait=...) / self.expect(STATE)
- 点击      -> self.click(逻辑坐标 | 识别结果 | 屏幕坐标)
- 点击状态  -> self.click_state(MARKER)  先定位再点
"""
from __future__ import annotations

import time
from typing import List, Optional, Sequence

from actions.controller import GameController
from config import settings
from core.errors import FlowAbortedError
from core.logger import get_logger
from core.stopwatch import WaitPredictor
from states.machine import Detection, StateMachine
from vision.types import Match


class RetryGuard:
    """重试次数守卫：超过上限抛 FlowAbortedError（替代旧代码的 exit(300)）。"""

    def __init__(self, limit: int, reason: str = "重试次数用尽") -> None:
        self.limit = limit
        self.reason = reason
        self.used = 0

    def tick(self) -> None:
        self.used += 1
        if self.used > self.limit:
            raise FlowAbortedError("{}（上限 {} 次）".format(self.reason, self.limit))


class Flow:
    """所有玩法流程的基类。"""

    #: 命令行里使用的名字
    name = "base"
    #: 一句话说明
    description = ""

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine: Optional[StateMachine] = None,
    ) -> None:
        self.controller = controller or GameController()
        self.machine = machine or StateMachine(self.controller.matcher)
        self.predictor = WaitPredictor()
        self.log = get_logger("flows.{}".format(self.name))

    # ------------------------------------------------------------------ 原语
    def click(self, target, **kwargs):
        """点击目标（逻辑坐标 Point / 识别结果 Match / 屏幕坐标 tuple）。"""
        return self.controller.click(target, **kwargs)

    def drag(self, start, end, duration: float = 1.0) -> None:
        self.controller.drag(start, end, duration=duration)

    def scroll(self, clicks: int, at=None, pause: float = 0.5) -> None:
        self.controller.scroll(clicks, at=at, pause=pause)

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def is_active(self, state, threshold: Optional[float] = None) -> bool:
        return self.machine.is_active(state, threshold=threshold)

    def locate(self, state, threshold: Optional[float] = None) -> Optional[Match]:
        return self.machine.locate(state, threshold=threshold)

    def locate_all(self, state, threshold: Optional[float] = None) -> List[Match]:
        return self.machine.locate_all(state, threshold=threshold)

    def detect(self, candidates: Sequence) -> Optional[Detection]:
        """在候选状态中找出置信度最高的当前状态。"""
        return self.machine.detect(candidates)

    def wait(
        self,
        state,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        on_wait=None,
    ) -> bool:
        """等待状态出现，超时返回 False。"""
        return self.machine.wait_for(state, timeout=timeout, interval=interval, on_wait=on_wait)

    def expect(
        self,
        state,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        on_wait=None,
    ) -> bool:
        """等待状态出现，超时抛 StateTimeoutError。"""
        return self.machine.expect(state, timeout=timeout, interval=interval, on_wait=on_wait)

    def wait_gone(
        self,
        state,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        on_wait=None,
    ) -> bool:
        """等待状态消失。"""
        return self.machine.wait_gone(state, timeout=timeout, interval=interval, on_wait=on_wait)

    def wait_any(
        self,
        candidates: Sequence,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        on_wait=None,
    ) -> Optional[Detection]:
        """等待候选状态中任意一个出现。"""
        return self.machine.wait_any(candidates, timeout=timeout, interval=interval,
                                     on_wait=on_wait)

    def click_state(
        self,
        state,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        required: bool = True,
    ) -> Optional[Match]:
        """先定位状态模板再点它的中心。

        required=True 时定位不到就抛 FlowAbortedError（旧代码会把 None 传进 click 直接崩）。
        """
        match = self.machine.locate(state)
        if match is None:
            if timeout:
                if not self.wait(state, timeout=timeout, interval=interval):
                    match = None
                else:
                    match = self.machine.locate(state)
            if match is None:
                if required:
                    raise FlowAbortedError("未能定位到 {}".format(state))
                self.log.warning("未能定位到 %s，跳过点击", state)
                return None
        self.click(match)
        return match

    # ------------------------------------------------------------------ 生命周期
    def prepare(self) -> None:
        """流程开始前的准备：定位窗口；无法礼貌点击时才置前窗口。"""
        self.controller.refresh_window()
        if self.controller.mouse.polite_click_available():
            from actions.mouse import accessibility_trusted

            if not accessibility_trusted():
                self.log.error(
                    "当前终端没有 macOS 辅助功能权限，点击事件会被系统静默丢弃！"
                    "请到 系统设置 -> 隐私与安全性 -> 辅助功能，勾选你正在用的终端后重跑。"
                )
        else:
            self.controller.focus()

    def run(self) -> None:
        """流程主体，子类必须实现。"""
        raise NotImplementedError("{} 未实现 run()".format(type(self).__name__))

    def execute(self) -> None:
        """统一入口：prepare + run。"""
        self.log.info("=== 流程 %s 开始 ===", self.name)
        self.prepare()
        self.run()
        self.log.info("=== 流程 %s 结束 ===", self.name)

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def default_timeout() -> float:
        return settings.DEFAULT_WAIT_TIMEOUT
