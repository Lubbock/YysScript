"""自动妖气封印（组队刷，事件驱动版）。

对应旧 scripts/dogger.py 的 Dogger 类：
进妖气封印 -> 选目标式神（默认小松丸）-> 进组队 -> 点准备 -> 战斗 ->
结算退出 -> 回到组队界面继续下一轮。

迁移后 run() 只组装引擎，规则都在 `SealRound` 订阅方里，按界面跳变推进：

    round.started                     -> 点妖气封印入口，立刻找目标式神（找不到就跳过本轮）
    state.entered.BATTLE_START        -> 点「开始战斗」（旧 _kick_start_battle）
    state.entered.BATTLE_PREPARE      -> 点准备（必要时补点一次），开始给战斗计时
    state.entered.BATTLE_SETTLEMENT_ALT -> 战斗入账，点退出结算
    state.entered.TEAM                -> 回到组队界面，本轮结束

三处等待（准备 / 战斗 / 回组队）都交给 core/timing.py，
跑满几轮之后会按历史 p10 盲等，不再一直空转截图。
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
from states.battle_prepare import BATTLE_PREPARE
from states.battle_settlement_alt import BATTLE_SETTLEMENT_ALT
from states.battle_start import BATTLE_START
from states.base import State
from states.monster_xiaosongmaru import MONSTER_XIAOSONGMARU
from states.team import TEAM

#: 阶段
PHASE_LIST = "list"          # 已点入口，正在找目标式神
PHASE_PREPARE = "prepare"    # 已进队伍，等「准备」界面
PHASE_BATTLE = "battle"      # 已点准备，等结算
PHASE_TEAM = "team"          # 已退出结算，等回到组队界面


class SealRound:
    """妖气封印一轮的订阅方。"""

    def __init__(self, engine, target: State, prepare_timeout: float,
                 battle_timeout: float, team_timeout: float,
                 poll_interval: float, team_pause: float,
                 name: str = "seal") -> None:
        self.engine = engine
        self.target = target
        self.prepare_timeout = prepare_timeout
        self.battle_timeout = battle_timeout
        self.team_timeout = team_timeout
        self.poll_interval = poll_interval
        self.team_pause = team_pause
        self.name = name
        self.log = get_logger("flows.{}".format(name))

        self.prepare_key = "{}:prepare".format(name)
        self.battle_key = "{}:battle".format(name)
        self.team_key = "{}:team".format(name)

        self._subs: List[Subscription] = []
        self._probe: Optional[ProbeWhileWaiting] = None
        self._phase = PHASE_LIST
        self._battle_cycle: Optional[Cycle] = None
        self._phase_started_at = 0.0
        self._warned: Optional[str] = None

    # ------------------------------------------------------------------ 挂载
    def attach(self) -> "SealRound":
        engine = self.engine
        engine.watch(BATTLE_PREPARE, BATTLE_START, BATTLE_SETTLEMENT_ALT, TEAM)
        self._subs = [
            engine.on(TOPIC_ROUND_STARTED, self.on_round_started, priority=-50),
            engine.on(topic_for(PREFIX_STATE_ENTERED, BATTLE_PREPARE), self.on_prepare),
            engine.on(topic_for(PREFIX_STATE_ENTERED, BATTLE_START), self.on_battle_start),
            engine.on(topic_for(PREFIX_STATE_ENTERED, BATTLE_SETTLEMENT_ALT),
                      self.on_settlement),
            engine.on(topic_for(PREFIX_STATE_ENTERED, TEAM), self.on_team),
            engine.on(TOPIC_POLL_COMPLETED, self.on_poll),
        ]
        # 旧代码 wait(TEAM, on_wait=lambda: click(SEAL_ENTRY))：回不去组队界面就一直点入口
        self._probe = ProbeWhileWaiting(
            engine, self.team_key, coords.SEAL_ENTRY, unless_state=TEAM,
            detail="等待组队界面时补点妖气封印入口").attach()
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
        """新一轮：点入口并立刻找目标式神（旧 _enter_team）。"""
        self._battle_cycle = None
        self._warned = None
        self._enter_team()

    def on_battle_start(self, event: StateEvent) -> None:
        """等准备界面时如果出现「开始战斗」，先点掉（旧 _kick_start_battle）。"""
        if self._phase != PHASE_PREPARE or self.engine.interrupted:
            return
        self.engine.click(coords.SEAL_START_BATTLE, state_key=event.key,
                          detail="先点掉开始战斗")

    def on_prepare(self, event: StateEvent) -> None:
        """准备界面出现 -> 点准备（没生效就补点一次）-> 开始给战斗计时。"""
        if self._phase != PHASE_PREPARE or self.engine.interrupted:
            return
        self._click_prepare()

    def on_settlement(self, event: StateEvent) -> None:
        """结算出现 -> 战斗入账 -> 点退出结算 -> 等回组队界面。"""
        if self._phase != PHASE_BATTLE or self.engine.interrupted:
            return
        if self._battle_cycle is not None:
            self.engine.timer.commit(self._battle_cycle)
            self._battle_cycle = None
        self.engine.click(coords.SEAL_EXIT, state_key=event.key, detail="退出结算界面")
        self._enter_phase(PHASE_TEAM, self.team_key)

    def on_team(self, event: StateEvent) -> None:
        """回到组队界面 -> 本轮结束。"""
        if self._phase != PHASE_TEAM or self.engine.interrupted:
            return
        self.engine.sleep(self.team_pause)
        self.engine.finish_round("妖气封印一轮完成")

    def on_poll(self, event: PollEvent) -> None:
        """各阶段预算检查，复现旧实现的超时语义。"""
        if self.engine.interrupted:
            return
        waited = self.engine.elapsed_round() - self._phase_started_at
        if self._phase == PHASE_PREPARE:
            # 旧代码 wait() 超时只返回 False，随后照样点准备，
            # 真出问题在后面 expect(BATTLE_SETTLEMENT_ALT) 抛 StateTimeoutError
            if waited > self.prepare_timeout and self._warned != PHASE_PREPARE:
                self._warned = PHASE_PREPARE
                self.log.warning("等待准备界面超过 %.0f 秒，仍按旧行为点准备继续",
                                 self.prepare_timeout)
                self._click_prepare()
            return
        if self._phase == PHASE_BATTLE:
            if self._battle_cycle is not None and \
                    self._battle_cycle.elapsed() > self.battle_timeout:
                # 等价旧代码 expect(BATTLE_SETTLEMENT_ALT, timeout=BATTLE_TIMEOUT)
                self.engine.timer.discard(self._battle_cycle, "战斗超时")
                self._battle_cycle = None
                self.engine.fail(
                    StateTimeoutError(BATTLE_SETTLEMENT_ALT.key, self.battle_timeout))
            return
        if self._phase == PHASE_TEAM:
            # 旧代码 wait(TEAM) 超时后只 sleep(2) 就进下一轮
            if waited > self.team_timeout and self._warned != PHASE_TEAM:
                self._warned = PHASE_TEAM
                self.log.warning("等待组队界面超过 %.0f 秒，直接进入下一轮", self.team_timeout)
                self.engine.finish_round("等待组队界面超时")

    # ------------------------------------------------------------------ 内部
    def _enter_team(self) -> None:
        """点妖气封印入口，选目标式神并加入队伍。找不到目标就跳过本轮。"""
        self.engine.click(coords.SEAL_ENTRY, detail="打开妖气封印列表")
        # 旧实现是点完入口立刻 locate 一次（不轮询），这里用 peek 保持一致：
        # peek 不广播事件，不会干扰主循环的状态跟踪
        found = self.engine.peek((self.target,))
        if found is None or found.match is None:
            # 旧代码这里会把 None 直接传给 click 导致崩溃，现在明确跳过本轮
            self.log.warning("未找到目标 %s，跳过本轮", self.target)
            self._phase = PHASE_LIST
            self.engine.finish_round("未找到目标式神")
            return
        self.engine.click(found.match, state_key=found.state.key, detail="选择目标式神")
        self.engine.click(coords.SEAL_TEAMMATE, detail="加入队伍")
        self._enter_phase(PHASE_PREPARE, self.prepare_key)

    def _click_prepare(self) -> None:
        """点准备；旧实现点完会再确认一次，没生效就用更长的按压补点一次。"""
        self.engine.click(coords.SEAL_PREPARE, detail="点击准备", duration=1.0)
        if self.engine.peek((BATTLE_PREPARE,)) is not None:
            self.engine.click(coords.SEAL_PREPARE, detail="准备界面仍在，补点一次",
                              duration=2.0)
        self._phase = PHASE_BATTLE
        # 计时从点准备这一刻开始，把战斗动画与加载都算进样本
        self._battle_cycle = self.engine.timer.begin(self.battle_key)
        self.engine.begin_wait(self.battle_key, self.poll_interval)
        self._phase_started_at = self.engine.elapsed_round()
        self._warned = None
        self.log.info("已点击准备，开始战斗")

    def _enter_phase(self, phase: str, timing_key: str) -> None:
        self._phase = phase
        self._phase_started_at = self.engine.elapsed_round()
        self._warned = None
        self.engine.begin_wait(timing_key, self.poll_interval)


class SealFlow(Flow):
    """自动妖气封印。"""

    name = "seal"
    description = "自动妖气封印（组队刷）"

    #: 等「准备」界面出现的超时
    PREPARE_TIMEOUT = 120.0
    #: 等战斗结算的超时
    BATTLE_TIMEOUT = 300.0
    #: 等回到组队界面的超时
    TEAM_TIMEOUT = 120.0
    #: 各阶段的探测间隔（样本收敛后由计时器改用更细的间隔）
    POLL_INTERVAL = 2.0
    #: 回到组队界面后的停顿
    TEAM_PAUSE = 2.0
    #: 整轮兜底超时的余量
    ROUND_TIMEOUT_SLACK = 30.0

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        times: int = 30,
        target: State = MONSTER_XIAOSONGMARU,
        **kwargs,
    ) -> None:
        """kwargs 透传给 Flow（bus / timer / adaptive）。"""
        super().__init__(controller=controller, machine=machine, **kwargs)
        self.times = times
        self.target = target

    def run(self) -> None:
        engine = self.create_engine()
        SealRound(
            engine,
            target=self.target,
            prepare_timeout=self.PREPARE_TIMEOUT,
            battle_timeout=self.BATTLE_TIMEOUT,
            team_timeout=self.TEAM_TIMEOUT,
            poll_interval=self.POLL_INTERVAL,
            team_pause=self.TEAM_PAUSE,
            name=self.name,
        ).attach()
        engine.run_rounds(
            self.times,
            round_timeout=(self.PREPARE_TIMEOUT + self.BATTLE_TIMEOUT
                           + self.TEAM_TIMEOUT + self.ROUND_TIMEOUT_SLACK),
        )
