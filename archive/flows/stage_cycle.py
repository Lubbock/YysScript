"""「阶段链」订阅方：点起始界面 -> 自适应等待 -> 点结算界面。

限时活动（`event-aband3t` / `event-aj8fer`）都是同一个形状：

    等阶段 A 出现 -> 点它 -> 等很久（战斗 / 读条）-> 等阶段 B 出现 -> 点它 -> 下一轮

旧实现的差别只在参数：等哪个模板、中间死等多久、超时多少、点完再停几秒。
以前 aj8fer 用 `core/stopwatch.py` 的均值预测过中间那段等待，aband3t 干脆写死
`sleep(120)`；现在两个都交给 `core/timing.py`：中间那段的真实耗时会被记住，
下一轮先盲等到接近历史 p10 再开始识图。

与 `flows/battle_cycle.py` 的区别：BattleCycle 面向「挑战 -> 战斗 -> 结算 -> 回挑战」
并且结算后还要补点 / 等回挑战界面；StageCycle 更简单，只有两个阶段、点完即止。
"""
from __future__ import annotations

from typing import Any, List, Optional

from core.bus import Subscription
from core.errors import FlowAbortedError
from core.logger import get_logger
from core.timing import Cycle
from flows.engine import FlowEngine
from flows.signals import (
    PREFIX_STATE_ENTERED,
    TOPIC_POLL_COMPLETED,
    TOPIC_ROUND_STARTED,
    PollEvent,
    RoundEvent,
    StateEvent,
    topic_for,
)

#: 阶段
PHASE_WAIT_START = "wait-start"
PHASE_WAIT_END = "wait-end"


class StageCycle:
    """两阶段活动循环的订阅方。

    参数：
        engine             : 目标引擎
        start_state        : 起始界面（点它开始这一轮）
        end_state          : 结算界面（点它结束这一轮）
        timing_key         : 中间那段等待的计时 key；沿用旧 key 可以复用历史样本
        start_timeout      : 等起始界面的超时，超时按 `FlowAbortedError` 中止
                             （等价旧的 `click_state(..., timeout=...)`）
        start_interval     : 等起始界面的探测间隔
        end_timeout        : 等结算界面的超时
        end_interval       : 等结算界面的探测间隔
        initial_blind_wait : 计时样本还没收敛时，先死等这么久再开始识图
                             （等价旧 aband3t 的 `sleep(STAGE_WAIT)`）；
                             收敛后由计时器给出的盲等取代它
        end_pause          : 点完结算界面后的停顿
        end_required       : True  -> 等不到结算界面就中止流程（旧 aband3t 行为）
                             False -> 只告警，继续下一轮（旧 aj8fer 行为）
        progress_message   : 等待结算期间每拍打一条进度日志的模板（含一个 %s 占位）
    """

    def __init__(
        self,
        engine: FlowEngine,
        start_state: Any,
        end_state: Any,
        timing_key: str,
        start_timeout: float = 40.0,
        start_interval: float = 2.0,
        end_timeout: float = 900.0,
        end_interval: float = 3.0,
        initial_blind_wait: float = 0.0,
        end_pause: float = 1.0,
        end_required: bool = True,
        progress_message: Optional[str] = None,
        name: Optional[str] = None,
    ) -> None:
        self.engine = engine
        self.start_state = start_state
        self.end_state = end_state
        self.timing_key = timing_key
        self.start_timeout = float(start_timeout)
        self.start_interval = float(start_interval)
        self.end_timeout = float(end_timeout)
        self.end_interval = float(end_interval)
        self.initial_blind_wait = float(initial_blind_wait)
        self.end_pause = float(end_pause)
        self.end_required = bool(end_required)
        self.progress_message = progress_message
        self.name = name or engine.name
        self.log = get_logger("flows.{}".format(self.name))

        #: 起始界面等不到时的报错文案，与旧的 base.Flow.click_state 保持一致
        self.missing_start_message = "未能定位到 {}".format(start_state)
        self.missing_end_message = "未能定位到 {}".format(end_state)

        self._subs: List[Subscription] = []
        self._phase = PHASE_WAIT_START
        self._stage_cycle: Optional[Cycle] = None
        self._end_started_at = 0.0
        self._polls = 0

    # ------------------------------------------------------------------ 挂载
    def attach(self) -> "StageCycle":
        engine = self.engine
        engine.watch(self.start_state, self.end_state)
        self._subs = [
            engine.on(TOPIC_ROUND_STARTED, self.on_round_started, priority=-50),
            engine.on(topic_for(PREFIX_STATE_ENTERED, self.start_state), self.on_start),
            engine.on(topic_for(PREFIX_STATE_ENTERED, self.end_state), self.on_end),
            engine.on(TOPIC_POLL_COMPLETED, self.on_poll),
        ]
        engine.begin_wait(None, self.start_interval)
        return self

    def detach(self) -> None:
        for sub in self._subs:
            self.engine.bus.unsubscribe(sub)
        self._subs = []

    # ------------------------------------------------------------------ 事件
    def on_round_started(self, event: RoundEvent) -> None:
        self._phase = PHASE_WAIT_START
        self._stage_cycle = None
        self._polls = 0
        self.engine.begin_wait(None, self.start_interval)

    def on_start(self, event: StateEvent) -> None:
        """看到起始界面 -> 点它 -> 开始给中间那段等待计时。"""
        if self._phase != PHASE_WAIT_START or self.engine.interrupted:
            return
        # 计时从点击这一刻开始，把随后的盲等也算进样本，这样量到的才是真实的阶段耗时
        self._stage_cycle = self.engine.timer.begin(self.timing_key)
        if self.engine.click(event.match, state_key=event.key,
                             detail="点击起始阶段") is None:
            self.engine.timer.discard(self._stage_cycle, "点击未送达")
            self._stage_cycle = None
            self.engine.reset_current()          # 下一拍重新触发 entered，自动重试
            return
        self._phase = PHASE_WAIT_END
        self._end_started_at = self.engine.elapsed_round()
        self._polls = 0
        self.engine.begin_wait(self.timing_key, self.end_interval)
        # 样本还没收敛时，先按旧的经验值死等一段，避免开局就高频识图误命中
        if self.initial_blind_wait > 0 and \
                not self.engine.timer.estimate(self.timing_key).converged:
            self.log.info("%s 尚无可用样本，先按经验值等待 %.0f 秒",
                          self.timing_key, self.initial_blind_wait)
            self.engine.sleep(min(self.initial_blind_wait, self.end_timeout))

    def on_end(self, event: StateEvent) -> None:
        """看到结算界面 -> 记账 -> 点它 -> 本轮结束。"""
        if self._phase != PHASE_WAIT_END or self.engine.interrupted:
            return
        self._commit_stage()
        self.engine.click(event.match, state_key=event.key, detail="点击结算阶段")
        if self.end_pause > 0:
            self.engine.sleep(self.end_pause)
        self.engine.finish_round("阶段链完成")

    def on_poll(self, event: PollEvent) -> None:
        """阶段预算检查 + 等待结算时的进度日志。"""
        if self.engine.interrupted:
            return
        if self._phase == PHASE_WAIT_START:
            # 命中优先于超时判定（与旧 machine.wait_for 的顺序一致）
            if event.hit and event.state_key == getattr(self.start_state, "key", ""):
                return
            if self.engine.elapsed_round() > self.start_timeout:
                self.engine.fail(FlowAbortedError(self.missing_start_message))
            return

        if self._phase != PHASE_WAIT_END:
            return
        if not event.hit and self.progress_message:
            self._polls += 1
            self.log.info(self.progress_message, self._polls)
        waited = self.engine.elapsed_round() - self._end_started_at
        if waited > self.end_timeout:
            self._on_end_timeout(waited)

    # ------------------------------------------------------------------ 内部
    def _on_end_timeout(self, waited: float) -> None:
        """等不到结算界面：按 end_required 决定中止还是继续下一轮。"""
        if self._stage_cycle is not None:
            # 超时的这一场不是完整样本，入库会把最小值带偏
            self.engine.timer.discard(self._stage_cycle, "等待结算超时")
            self._stage_cycle = None
        if self.end_required:
            # 旧 aband3t 行为：click_state(required=True) 等不到就中止流程
            self.engine.fail(FlowAbortedError(self.missing_end_message))
            return
        # 旧 aj8fer 行为：只告警，继续下一轮
        self.log.warning("等待 %s 超时（%.1f 秒），按超时继续下一轮", self.end_state, waited)
        self._phase = PHASE_WAIT_START
        self.engine.finish_round("等待结算超时")

    def _commit_stage(self) -> None:
        if self._stage_cycle is None:
            return
        self.engine.timer.commit(self._stage_cycle)
        self._stage_cycle = None

    # ------------------------------------------------------------------ 工具
    def round_timeout(self, slack: float = 30.0) -> float:
        """整轮的兜底超时：两个阶段的预算 + 余量。"""
        return self.start_timeout + self.end_timeout + self.initial_blind_wait + slack
