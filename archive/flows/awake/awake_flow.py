"""自动觉醒材料（事件驱动版）。

对应旧 scripts/awake.py 的 Awake 类：
底部菜单进觉醒材料 -> 选副本（火御魂 / 风麒麟 / 水麒麟 / 雷麒麟）
-> 循环「等挑战界面 → 挑战 → 等结算 → 再点挑战」。

迁移后 run() 只负责「进副本 + 组装引擎」，循环规则都在本文件的 `AwakeRound` 订阅方里：

    state.entered.CHALLENGE           -> 点挑战坐标，开始给这场战斗计时
    state.entered.BATTLE_SETTLEMENT_ALT -> 结算入账，点挑战坐标回到下一轮

等待节奏交给 core/timing.py：旧实现写死 `sleep(BATTLE_DURATION=20)` 再开始识图，
现在只在**样本还没收敛**时这么做，收敛后按历史 p10 盲等（key = `awake:battle`）。
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
    TOPIC_POLL_COMPLETED,
    TOPIC_ROUND_STARTED,
    PollEvent,
    RoundEvent,
    StateEvent,
    topic_for,
)
from states.battle_settlement_alt import BATTLE_SETTLEMENT_ALT
from states.challenge import CHALLENGE

#: 阶段
PHASE_CHALLENGE = "challenge"
PHASE_BATTLE = "battle"


class AwakeRound:
    """觉醒一轮的订阅方：等挑战界面 -> 点挑战 -> 等结算 -> 点挑战回下一轮。"""

    def __init__(self, engine, challenge_timeout: float, battle_timeout: float,
                 battle_interval: float, initial_blind_wait: float,
                 settle_pause: float, name: str = "awake") -> None:
        self.engine = engine
        self.challenge_timeout = challenge_timeout
        self.battle_timeout = battle_timeout
        self.battle_interval = battle_interval
        self.initial_blind_wait = initial_blind_wait
        self.settle_pause = settle_pause
        self.log = get_logger("flows.{}".format(name))

        self.battle_key = "{}:battle".format(name)
        self.challenge_key = "{}:challenge".format(name)

        self._subs: List[Subscription] = []
        self._probe: Optional[ProbeWhileWaiting] = None
        self._phase = PHASE_CHALLENGE
        self._battle_cycle: Optional[Cycle] = None
        self._challenge_warned = False

    # ------------------------------------------------------------------ 挂载
    def attach(self) -> "AwakeRound":
        engine = self.engine
        engine.watch(CHALLENGE, BATTLE_SETTLEMENT_ALT)
        self._subs = [
            engine.on(TOPIC_ROUND_STARTED, self.on_round_started, priority=-50),
            engine.on(topic_for(PREFIX_STATE_ENTERED, CHALLENGE), self.on_challenge),
            engine.on(topic_for(PREFIX_STATE_ENTERED, BATTLE_SETTLEMENT_ALT),
                      self.on_settlement),
            engine.on(TOPIC_POLL_COMPLETED, self.on_poll),
        ]
        # 旧代码 wait(CHALLENGE, on_wait=lambda: click(AWAKE_CHALLENGE))：
        # 挑战界面有时要先点一下才会真的出现，所以等待期间持续补点同一个坐标
        self._probe = ProbeWhileWaiting(
            engine, self.challenge_key, coords.AWAKE_CHALLENGE,
            unless_state=CHALLENGE, detail="等待挑战界面时补点挑战坐标").attach()
        engine.begin_wait(self.challenge_key, 2.0)
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
        self._phase = PHASE_CHALLENGE
        self._battle_cycle = None
        self._challenge_warned = False
        self.engine.begin_wait(self.challenge_key, 2.0)

    def on_challenge(self, event: StateEvent) -> None:
        """挑战界面出现 -> 点挑战坐标开战。"""
        if self._phase != PHASE_CHALLENGE or self.engine.interrupted:
            return
        self._start_battle("已匹配到挑战界面")

    def on_settlement(self, event: StateEvent) -> None:
        """结算界面出现 -> 这场战斗入账 -> 点挑战坐标回到下一轮。"""
        if self._phase != PHASE_BATTLE or self.engine.interrupted:
            return
        if self._battle_cycle is not None:
            self.engine.timer.commit(self._battle_cycle)
            self._battle_cycle = None
        self.engine.click(coords.AWAKE_CHALLENGE, state_key=event.key,
                          detail="结算后再点挑战位置，回到下一轮")
        self.engine.sleep(self.settle_pause)
        self._phase = PHASE_CHALLENGE
        self.engine.begin_wait(self.challenge_key, 2.0)
        self.engine.finish_round("觉醒一轮完成")

    def on_poll(self, event: PollEvent) -> None:
        """阶段预算检查，复现旧实现的两处超时语义。"""
        if self.engine.interrupted:
            return
        if self._phase == PHASE_CHALLENGE:
            if event.hit and event.state_key == CHALLENGE.key:
                return
            elapsed = self.engine.elapsed_round()
            if elapsed > self.challenge_timeout and not self._challenge_warned:
                # 旧实现等不到挑战界面并不报错，而是照样点一下挑战坐标继续跑，
                # 真出问题会在后面 expect(BATTLE_SETTLEMENT_ALT) 时抛 StateTimeoutError
                self._challenge_warned = True
                self.log.warning("等待挑战界面超过 %.0f 秒，仍按旧行为点挑战坐标继续",
                                 self.challenge_timeout)
                self._start_battle("未匹配到挑战界面，超时后盲点挑战坐标")
            return
        if self._phase == PHASE_BATTLE and self._battle_cycle is not None:
            if self._battle_cycle.elapsed() > self.battle_timeout:
                # 等价旧代码 expect(BATTLE_SETTLEMENT_ALT, timeout=BATTLE_TIMEOUT)
                self.engine.timer.discard(self._battle_cycle, "战斗超时")
                self._battle_cycle = None
                self.engine.fail(
                    StateTimeoutError(BATTLE_SETTLEMENT_ALT.key, self.battle_timeout))

    # ------------------------------------------------------------------ 内部
    def _start_battle(self, reason: str) -> None:
        self.log.info("%s，点击挑战进入战斗", reason)
        self._phase = PHASE_BATTLE
        # 计时从点击前开始，把随后的盲等也算进样本，量到的才是真实的战斗耗时
        self._battle_cycle = self.engine.timer.begin(self.battle_key)
        self.engine.click(coords.AWAKE_CHALLENGE, detail="点击挑战，进入战斗")
        self.engine.begin_wait(self.battle_key, self.battle_interval)
        # 样本还没收敛时，沿用旧实现写死的等待时长；收敛后由计时器的盲等取代
        if self.initial_blind_wait > 0 and \
                not self.engine.timer.estimate(self.battle_key).converged:
            self.engine.sleep(self.initial_blind_wait)


class AwakeFlow(Flow):
    """自动刷觉醒材料。"""

    name = "awake"
    description = "自动觉醒材料"

    #: 一场战斗的预估时长（旧脚本写死 20 秒）；仅在计时样本未收敛时作为盲等时长
    BATTLE_DURATION = 20.0
    #: 等战斗结算的最长时间
    BATTLE_TIMEOUT = 300.0
    #: 等挑战界面出现的最长时间
    CHALLENGE_TIMEOUT = 60.0
    #: 战斗中的探测间隔（样本收敛后由计时器改用更细的间隔）
    BATTLE_INTERVAL = 3.0
    #: 结算后点挑战坐标之后的停顿
    SETTLE_PAUSE = 2.0
    #: 整轮兜底超时的余量
    ROUND_TIMEOUT_SLACK = 30.0

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        times: int = 20,
        dungeon: int = 4,
        **kwargs,
    ) -> None:
        """
        times   : 刷多少次
        dungeon : 副本序号，1 火御魂 | 2 风麒麟 | 3 水麒麟 | 4 雷麒麟
        kwargs  : 透传给 Flow（bus / timer / adaptive）
        """
        super().__init__(controller=controller, machine=machine, **kwargs)
        self.times = times
        self.dungeon = dungeon

    def run(self) -> None:
        self.log.info("开始刷觉醒材料：副本 %s，共 %s 次", self.dungeon, self.times)
        self.click(coords.bottom_menu(coords.MENU_AWAKE_MATERIAL))
        self.sleep(1.5)
        self.click(coords.awake_dungeon(self.dungeon))
        self.sleep(1.5)

        engine = self.create_engine()
        AwakeRound(
            engine,
            challenge_timeout=self.CHALLENGE_TIMEOUT,
            battle_timeout=self.BATTLE_TIMEOUT,
            battle_interval=self.BATTLE_INTERVAL,
            initial_blind_wait=self.BATTLE_DURATION,
            settle_pause=self.SETTLE_PAUSE,
            name=self.name,
        ).attach()
        engine.run_rounds(
            self.times,
            round_timeout=(self.CHALLENGE_TIMEOUT + self.BATTLE_TIMEOUT
                           + self.ROUND_TIMEOUT_SLACK),
        )
