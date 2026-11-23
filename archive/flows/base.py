"""流程基类：把「状态机 + 操作器 + 事件总线 + 计时器」组合成可复用的动作原语。

flows 下的每个功能都继承 Flow，只写业务编排，不直接碰 pyautogui / cv2：
- 判断界面  -> self.is_active(STATE) / self.machine.detect([...])
- 等界面    -> self.wait(STATE, on_wait=...) / self.expect(STATE)
- 点击      -> self.click(逻辑坐标 | 识别结果 | 屏幕坐标)
- 点击状态  -> self.click_state(MARKER)  先定位再点

两种编排风格，可以混用：
1. **命令式**（老写法，explore / awake / seal 等仍在用）：run() 里按顺序
   wait -> click -> wait；
2. **事件驱动**（soul / shard 已迁移）：`self.create_engine()` 拿到 FlowEngine，
   把规则写成订阅方挂上去，引擎负责轮询识图、广播事件、推进轮次与计时，
   见 flows/engine.py 与 flows/battle_cycle.py。

无论哪种风格，Flow 都自带：
- `self.bus`   : 事件总线（core/bus.py），流程级私有，一个流程一条；
- `self.timer` : 循环计时 + 自适应等待（core/timing.py），样本落 sqlite。
"""
from __future__ import annotations

import time
from typing import Callable, List, Optional, Sequence

from actions.controller import GameController
from config import settings
from core.bus import EventBus
from core.errors import FlowAbortedError
from core.logger import get_logger
from core.stopwatch import WaitPredictor
from core.timing import CycleTimer, WaitPlan
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
        bus: Optional[EventBus] = None,
        timer: Optional[CycleTimer] = None,
        adaptive: Optional[bool] = None,
        clock: Optional[Callable[[], float]] = None,
        sleeper: Optional[Callable[[float], None]] = None,
    ) -> None:
        """
        controller / machine : 不传就自动装配（真机运行走这条）
        bus                  : 事件总线，默认新建一条流程私有总线
        timer                : 循环计时器，默认新建并绑定到 bus（commit 时广播）
        adaptive             : None = 跟随 settings.ADAPTIVE_WAIT
                               （命令行 --no-adaptive-wait / YYS_ADAPTIVE_WAIT=0 会改它）
        clock / sleeper    : 测试缝：注入假时钟与假 sleep，让引擎的轮询 / 盲等
                               在单测里瞬时完成；真机运行不传，走 time.monotonic
        """
        self.controller = controller or GameController()
        self.machine = machine or StateMachine(self.controller.matcher)
        self.predictor = WaitPredictor()
        self.bus = bus or EventBus()
        self.timer = timer or CycleTimer(bus=self.bus, adaptive=adaptive)
        self._clock = clock
        self._sleeper = sleeper
        #: create_engine() 产出的引擎；execute() 靠它判断要不要重复打总账
        self._engine = None
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
        adaptive_key: Optional[str] = None,
    ) -> bool:
        """等待状态出现，超时返回 False。

        adaptive_key：给了计时 key（例如 "seal:battle"）就启用自适应等待 ——
        先按历史耗时盲等（这期间不截屏），再以更细的间隔轮询；
        不给就是固定 interval 轮询，与改造前一致。
        """
        return self.machine.wait_for(state, timeout=timeout, interval=interval,
                                     on_wait=on_wait, **self._adaptive(adaptive_key))

    def expect(
        self,
        state,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        on_wait=None,
        adaptive_key: Optional[str] = None,
    ) -> bool:
        """等待状态出现，超时抛 StateTimeoutError。"""
        return self.machine.expect(state, timeout=timeout, interval=interval,
                                   on_wait=on_wait, **self._adaptive(adaptive_key))

    def wait_gone(
        self,
        state,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        on_wait=None,
        adaptive_key: Optional[str] = None,
    ) -> bool:
        """等待状态消失。"""
        return self.machine.wait_gone(state, timeout=timeout, interval=interval,
                                      on_wait=on_wait, **self._adaptive(adaptive_key))

    def wait_any(
        self,
        candidates: Sequence,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        on_wait=None,
        adaptive_key: Optional[str] = None,
    ) -> Optional[Detection]:
        """等待候选状态中任意一个出现。"""
        return self.machine.wait_any(candidates, timeout=timeout, interval=interval,
                                     on_wait=on_wait, **self._adaptive(adaptive_key))

    def _adaptive(self, key: Optional[str]) -> dict:
        """把 adaptive_key 翻译成状态机的 scheduler / timing_key 参数。"""
        if not key:
            return {}
        return {"scheduler": self.timer, "timing_key": key}

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

    # ------------------------------------------------------------------ 事件与计时
    def on(self, topic: str, handler, priority: int = 0, once: bool = False):
        """订阅本流程总线上的事件（topic 见 flows/signals.py）。"""
        return self.bus.subscribe(topic, handler, priority=priority, once=once)

    def publish(self, topic: str, event=None) -> int:
        """往本流程总线上发事件，返回投递到的订阅方数量。"""
        return self.bus.publish(topic, event)

    def cycle(self, key: str):
        """记录一段耗时：`with self.cycle("soul:battle"): ...`（样本落 sqlite）。"""
        return self.timer.cycle(key)

    def wait_plan(self, key: str, timeout: float,
                  interval: Optional[float] = None) -> WaitPlan:
        """问计时器「这一步该盲等多久、之后隔多久识一次图」。

        命令式流程也能用：
            plan = self.wait_plan("soul:battle", timeout=300.0, interval=3.0)
            self.sleep(plan.blind_wait)      # 这段时间不截屏
            self.wait(STATE, timeout=..., interval=plan.interval)
        """
        return self.timer.plan(key, timeout=timeout, interval=interval)

    def create_engine(self, name: Optional[str] = None, **kwargs):
        """创建事件驱动的主流程引擎（flows/engine.py）。

        默认复用本 flow 的 machine / controller / bus / timer，
        因此订阅方发出的事件与计时样本都落在同一条总线上。
        """
        from flows.engine import FlowEngine  # 延迟导入：命令式流程用不到引擎

        kwargs.setdefault("machine", self.machine)
        kwargs.setdefault("controller", self.controller)
        kwargs.setdefault("bus", self.bus)
        kwargs.setdefault("timer", self.timer)
        if self._clock is not None:
            kwargs.setdefault("clock", self._clock)
        if self._sleeper is not None:
            kwargs.setdefault("sleeper", self._sleeper)
        self._engine = FlowEngine(name or self.name, **kwargs)
        return self._engine

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
        """统一入口：prepare + run + 收尾打总账。"""
        self.log.info("=== 流程 %s 开始 ===", self.name)
        self.prepare()
        self.run()
        # 引擎驱动的流程由引擎自己打总账（含轮次 / 识图成本），这里不重复
        if self._engine is None and self.timer.summary():
            self.log.info("本次耗时样本：\n%s", self.timer.describe_summary())
        self.log.info("=== 流程 %s 结束 ===", self.name)

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def default_timeout() -> float:
        return settings.DEFAULT_WAIT_TIMEOUT
