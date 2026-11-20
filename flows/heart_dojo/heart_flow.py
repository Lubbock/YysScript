"""自动御心道场（觉醒道场，事件驱动版）。

对应旧 scripts/heart.py 的 Heart 类：
进道场 -> 选副本 -> 确认 -> 准备 -> 等战斗结束 -> 回到选择界面循环。

迁移后 run() 只负责「进道场 + 组装引擎」，规则都在 `HeartRound` 订阅方里：

    round.started                       -> 等道场选择界面（等待期间补点「选择」）
    state.entered.HEART_DOJO            -> 点确认、点准备，进入战斗阶段
    poll.completed(命中 BATTLE_PREPARE_ALT) -> 点「开始」（旧 wait_gone 的 on_wait）
    state.exited.BATTLE_PREPARE_ALT     -> 准备界面消失 = 战斗真的开始了
    state.entered.BATTLE_SETTLEMENT_ALT -> 战斗入账，点「选择」回到下一轮

旧实现里写死的 `sleep(SETTLE_WAIT=120)` 只在计时样本未收敛时使用；
收敛后由 core/timing.py 按 `heart:battle` 的历史 p10 盲等，
战斗提前结束时会立刻识别到结算，不用干等满 120 秒。
"""
from __future__ import annotations

from typing import List, Optional

from actions.controller import GameController
from config import coordinates as coords
from core.bus import Subscription
from core.errors import StateTimeoutError
from core.logger import get_logger
from core.timing import Cycle
from flows.base import Flow
from flows.rules import ProbeWhileWaiting
from flows.signals import (
    PREFIX_STATE_ENTERED,
    PREFIX_STATE_EXITED,
    TOPIC_POLL_COMPLETED,
    TOPIC_ROUND_STARTED,
    PollEvent,
    RoundEvent,
    StateEvent,
    topic_for,
)
from states.battle_prepare_alt import BATTLE_PREPARE_ALT
from states.battle_settlement_alt import BATTLE_SETTLEMENT_ALT
from states.heart_dojo import HEART_DOJO

#: 阶段
PHASE_DOJO = "dojo"        # 等道场选择界面
PHASE_PREPARE = "prepare"  # 已点准备，等准备界面消失（战斗开始）
PHASE_BATTLE = "battle"    # 战斗中，等结算


class HeartRound:
    """御心道场一轮的订阅方。"""

    def __init__(self, engine, dojo_timeout: float, prepare_timeout: float,
                 battle_timeout: float, dojo_interval: float, prepare_interval: float,
                 battle_interval: float, initial_blind_wait: float,
                 pre_battle_pause: float, name: str = "heart") -> None:
        self.engine = engine
        self.dojo_timeout = dojo_timeout
        self.prepare_timeout = prepare_timeout
        self.battle_timeout = battle_timeout
        self.dojo_interval = dojo_interval
        self.prepare_interval = prepare_interval
        self.battle_interval = battle_interval
        self.initial_blind_wait = initial_blind_wait
        self.pre_battle_pause = pre_battle_pause
        self.log = get_logger("flows.{}".format(name))

        self.dojo_key = "{}:dojo".format(name)
        self.battle_key = "{}:battle".format(name)

        self._subs: List[Subscription] = []
        self._probe: Optional[ProbeWhileWaiting] = None
        self._phase = PHASE_DOJO
        self._battle_cycle: Optional[Cycle] = None
        self._phase_started_at = 0.0
        self._battle_started_at = 0.0
        self._warned: Optional[str] = None

    # ------------------------------------------------------------------ 挂载
    def attach(self) -> "HeartRound":
        engine = self.engine
        engine.watch(HEART_DOJO, BATTLE_PREPARE_ALT, BATTLE_SETTLEMENT_ALT)
        self._subs = [
            engine.on(TOPIC_ROUND_STARTED, self.on_round_started, priority=-50),
            engine.on(topic_for(PREFIX_STATE_ENTERED, HEART_DOJO), self.on_dojo),
            engine.on(topic_for(PREFIX_STATE_EXITED, BATTLE_PREPARE_ALT),
                      self.on_prepare_gone),
            engine.on(topic_for(PREFIX_STATE_ENTERED, BATTLE_SETTLEMENT_ALT),
                      self.on_settlement),
            engine.on(TOPIC_POLL_COMPLETED, self.on_poll),
        ]
        # 旧代码 wait(HEART_DOJO, on_wait=lambda: click(HEART_SELECT))
        self._probe = ProbeWhileWaiting(
            engine, self.dojo_key, coords.HEART_SELECT, unless_state=HEART_DOJO,
            detail="等待道场界面时补点选择").attach()
        engine.begin_wait(self.dojo_key, self.dojo_interval)
        return self

    def detach(self) -> None:
        for sub in self._subs:
            self.engine.bus.unsubscribe(sub)
        self._subs = []
        if self._probe is not None:
            self._probe.detach()
            self._probe = None

    # ------------------------------------------------------------------ 事件
    def on_round_started(self, event: RoundEvent) -> None:
        self._phase = PHASE_DOJO
        self._battle_cycle = None
        self._warned = None
        self._phase_started_at = self.engine.elapsed_round()
        self.engine.begin_wait(self.dojo_key, self.dojo_interval)

    def on_dojo(self, event: StateEvent) -> None:
        """道场选择界面出现 -> 确认 -> 准备 -> 开始给战斗计时。"""
        if self._phase != PHASE_DOJO or self.engine.interrupted:
            return
        self._enter_prepare()

    def on_prepare_gone(self, event: StateEvent) -> None:
        """准备界面消失 = 战斗真的开始了（旧 wait_gone(BATTLE_PREPARE_ALT)）。"""
        if self._phase != PHASE_PREPARE or self.engine.interrupted:
            return
        self._enter_battle()

    def on_settlement(self, event: StateEvent) -> None:
        """结算出现 -> 战斗入账 -> 点「选择」回到下一轮。"""
        if self._phase == PHASE_DOJO or self.engine.interrupted:
            return
        if self._battle_cycle is not None:
            self.engine.timer.commit(self._battle_cycle)
            self._battle_cycle = None
        self.log.info("战斗结束，结算画面 %s", event.state)
        self.engine.click(coords.HEART_SELECT, state_key=event.key,
                          detail="点选择，回到下一轮")
        self._phase = PHASE_DOJO
        self.engine.finish_round("御心道场一轮完成")

    def on_poll(self, event: PollEvent) -> None:
        """补点「开始」+ 各阶段预算检查。"""
        if self.engine.interrupted:
            return
        if self._phase == PHASE_DOJO:
            # 旧代码 wait() 超时只返回 False，随后照样点确认 / 准备
            if self._over_budget(self.dojo_timeout, PHASE_DOJO):
                self.log.warning("等待道场界面超过 %.0f 秒，仍按旧行为点确认继续",
                                 self.dojo_timeout)
                self._enter_prepare()
            return

        if self._phase == PHASE_PREPARE:
            # 旧代码 wait_gone(BATTLE_PREPARE_ALT, on_wait=lambda: click(HEART_START))：
            # 准备界面还挂着就每拍点一次「开始」
            if event.hit and event.state_key == BATTLE_PREPARE_ALT.key:
                self.engine.click(coords.HEART_START, state_key=event.state_key,
                                  detail="点开始战斗")
            if self._over_budget(self.prepare_timeout, PHASE_PREPARE):
                self.log.warning("准备界面超过 %.0f 秒未消失，按战斗已开始继续",
                                 self.prepare_timeout)
                self._enter_battle()
            return

        if self._phase == PHASE_BATTLE:
            waited = self.engine.elapsed_round() - self._battle_started_at
            if waited > self.battle_timeout:
                # 等价旧代码 expect(BATTLE_SETTLEMENT_ALT, timeout=BATTLE_TIMEOUT)
                if self._battle_cycle is not None:
                    self.engine.timer.discard(self._battle_cycle, "战斗超时")
                    self._battle_cycle = None
                self.engine.fail(
                    StateTimeoutError(BATTLE_SETTLEMENT_ALT.key, self.battle_timeout))

    # ------------------------------------------------------------------ 内部
    def _over_budget(self, timeout: float, phase: str) -> bool:
        """本阶段是否已超预算；同一阶段只触发一次。"""
        if self._warned == phase:
            return False
        if self.engine.elapsed_round() - self._phase_started_at <= timeout:
            return False
        self._warned = phase
        return True

    def _enter_prepare(self) -> None:
        self.engine.click(coords.HEART_CONFIRM, detail="确认副本")
        self.engine.click(coords.HEART_PREPARE, detail="点击准备")
        self.engine.sleep(self.pre_battle_pause)
        self.log.info("开始打怪")
        self._phase = PHASE_PREPARE
        self._phase_started_at = self.engine.elapsed_round()
        self._warned = None
        # 战斗耗时从点准备这一刻开始算（含准备界面停留时间），量到的才是完整的一段
        self._battle_cycle = self.engine.timer.begin(self.battle_key)
        # 准备阶段不盲等：要盯着 BATTLE_PREPARE_ALT 是否消失，还得点「开始」
        self.engine.begin_wait(None, self.prepare_interval)

    def _enter_battle(self) -> None:
        self._phase = PHASE_BATTLE
        self._phase_started_at = self.engine.elapsed_round()
        self._warned = None
        self.engine.begin_wait(self.battle_key, self.battle_interval)
        # 300 秒的战斗预算从「准备界面消失 + 经验值死等」之后才开始算（与旧实现一致）
        if self.initial_blind_wait > 0 and \
                not self.engine.timer.estimate(self.battle_key).converged:
            self.log.info("%s 尚无可用样本，先按经验值等待 %.0f 秒",
                          self.battle_key, self.initial_blind_wait)
            self.engine.sleep(self.initial_blind_wait)
        self._battle_started_at = self.engine.elapsed_round()


class HeartDojoFlow(Flow):
    """自动刷御心道场。"""

    name = "heart"
    description = "自动御心道场"

    #: 战斗结算的固定等待（旧脚本写死 120 秒）；仅在计时样本未收敛时使用
    SETTLE_WAIT = 120.0
    #: 等战斗结算界面的超时
    BATTLE_TIMEOUT = 300.0
    #: 等准备按钮消失的超时
    PREPARE_TIMEOUT = 120.0
    #: 等道场选择界面的超时
    DOJO_TIMEOUT = 60.0
    #: 各阶段探测间隔（样本收敛后战斗阶段由计时器改用更细的间隔）
    DOJO_INTERVAL = 5.0
    PREPARE_INTERVAL = 2.0
    BATTLE_INTERVAL = 5.0
    #: 点完确认 / 准备后的停顿（旧脚本的 sleep(2) + sleep(5)）
    PRE_BATTLE_PAUSE = 7.0
    #: 整轮兜底超时的余量
    ROUND_TIMEOUT_SLACK = 30.0

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        times: int = 10,
        **kwargs,
    ) -> None:
        """kwargs 透传给 Flow（bus / timer / adaptive）。"""
        super().__init__(controller=controller, machine=machine, **kwargs)
        self.times = times

    def run(self) -> None:
        self.click(coords.HEART_ENTRY)
        self.sleep(2)
        self.click(coords.HEART_SELECT)
        self.sleep(1)

        engine = self.create_engine()
        cycle = HeartRound(
            engine,
            dojo_timeout=self.DOJO_TIMEOUT,
            prepare_timeout=self.PREPARE_TIMEOUT,
            battle_timeout=self.BATTLE_TIMEOUT,
            dojo_interval=self.DOJO_INTERVAL,
            prepare_interval=self.PREPARE_INTERVAL,
            battle_interval=self.BATTLE_INTERVAL,
            initial_blind_wait=self.SETTLE_WAIT,
            pre_battle_pause=self.PRE_BATTLE_PAUSE,
            name=self.name,
        ).attach()
        engine.run_rounds(
            self.times,
            round_timeout=(self.DOJO_TIMEOUT + self.PREPARE_TIMEOUT + self.SETTLE_WAIT
                           + self.BATTLE_TIMEOUT + self.ROUND_TIMEOUT_SLACK),
        )
