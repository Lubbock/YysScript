"""自动结界突破（事件驱动版）。

对应旧 scripts/fight.py 的 Fight 类：
进结界突破 -> 依次点九宫格 9 个结界 -> 有「进攻」按钮就打 ->
打完或打失败后回到九宫格 -> 9 个都处理完就刷新列表。

一个引擎轮次 = 一整轮九宫格（9 格 + 刷新），与旧的 round_index 语义一致。
格子推进是索引驱动的（第几格点哪个坐标），战斗部分则是事件驱动的：

    round.started                        -> 打开第 1 格，找「进攻」标记
    state.entered.BATTLE_PREPARE_ALT     -> 进入准备界面，开始每拍点「确认」
    poll.completed(命中 BATTLE_PREPARE_ALT) -> 点确认（旧 wait_gone 的 on_wait）
    state.exited.BATTLE_PREPARE_ALT      -> 准备界面消失 = 战斗开始，开始计时
    state.entered.BREAKTHROUGH_FAILED / BATTLE_SETTLEMENT_ALT
                                         -> 战斗入账，点第 1 格关弹窗，推进下一格

MARKER_ATTACK / MARKER_REFRESH 是按钮标记，只在需要的时刻用 `engine.peek()` 单独识别
（与旧代码的 `locate()` 一致），不进 watch 列表 —— 否则每拍都要多匹配两张模板，
而且它们出现在多个界面上，容易造成误判。

修掉的旧 bug（保持已修状态）：
1. 九宫格索引换算用 math.ceil(float(now)/3) + now%3，第 3/6/9 格会算错行；
   现在统一用 coords.breakthrough_cell(index)。
2. 刷新时的 loop_action 写成 `{click(a), click(b)}`（集合字面量），
   两个点击的执行顺序不确定；现在按顺序调用。
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
from states.breakthrough_entry import BREAKTHROUGH_ENTRY
from states.breakthrough_failed import BREAKTHROUGH_FAILED
from states.marker_attack import MARKER_ATTACK
from states.marker_refresh import MARKER_REFRESH

#: 九宫格共 9 个结界
CELL_COUNT = 9

#: 阶段
PHASE_OPEN_CELL = "open-cell"    # 正在打开某一格、找进攻标记
PHASE_WAIT_PREPARE = "wait-prepare"  # 已点进攻，等准备界面出现
PHASE_CONFIRM = "confirm"        # 准备界面挂着，每拍点确认
PHASE_WAIT_RESULT = "wait-result"    # 战斗中，等胜/负结算
PHASE_REFRESH = "refresh"        # 9 格跑完，刷新列表


class BreakthroughSweep:
    """一整轮九宫格的订阅方。"""

    def __init__(self, engine, cell_count: int, attack_timeout: float,
                 battle_timeout: float, refresh_timeout: float,
                 poll_interval: float, initial_blind_wait: float,
                 cell_pause: float, result_pause: float, refresh_pause: float,
                 name: str = "breakthrough") -> None:
        self.engine = engine
        self.cell_count = cell_count
        self.attack_timeout = attack_timeout
        self.battle_timeout = battle_timeout
        self.refresh_timeout = refresh_timeout
        self.poll_interval = poll_interval
        self.initial_blind_wait = initial_blind_wait
        self.cell_pause = cell_pause
        self.result_pause = result_pause
        self.refresh_pause = refresh_pause
        self.name = name
        self.log = get_logger("flows.{}".format(name))

        self.battle_key = "{}:battle".format(name)

        self._subs: List[Subscription] = []
        self._phase = PHASE_OPEN_CELL
        self._cell = 0
        self._battle_cycle: Optional[Cycle] = None
        self._phase_started_at = 0.0

    # ------------------------------------------------------------------ 挂载
    def attach(self) -> "BreakthroughSweep":
        engine = self.engine
        engine.watch(BATTLE_PREPARE_ALT, BREAKTHROUGH_FAILED, BATTLE_SETTLEMENT_ALT)
        self._subs = [
            engine.on(TOPIC_ROUND_STARTED, self.on_round_started, priority=-50),
            engine.on(topic_for(PREFIX_STATE_ENTERED, BATTLE_PREPARE_ALT),
                      self.on_prepare),
            engine.on(topic_for(PREFIX_STATE_EXITED, BATTLE_PREPARE_ALT),
                      self.on_prepare_gone),
            engine.on(topic_for(PREFIX_STATE_ENTERED, BREAKTHROUGH_FAILED),
                      self.on_result),
            engine.on(topic_for(PREFIX_STATE_ENTERED, BATTLE_SETTLEMENT_ALT),
                      self.on_result),
            engine.on(TOPIC_POLL_COMPLETED, self.on_poll),
        ]
        return self

    def detach(self) -> None:
        for sub in self._subs:
            self.engine.bus.unsubscribe(sub)
        self._subs = []

    # ------------------------------------------------------------------ 事件
    def on_round_started(self, event: RoundEvent) -> None:
        self._battle_cycle = None
        self._open_cell(1)

    def on_prepare(self, event: StateEvent) -> None:
        """准备界面出现（旧 expect(BATTLE_PREPARE_ALT) 成功）。"""
        if self._phase != PHASE_WAIT_PREPARE or self.engine.interrupted:
            return
        self._enter_phase(PHASE_CONFIRM, None)
        self.log.info("进攻第 %s 格结界，进入准备界面", self._cell)

    def on_prepare_gone(self, event: Optional[StateEvent] = None) -> None:
        """准备界面消失 = 战斗真的开始了（旧 wait_gone(BATTLE_PREPARE_ALT) 返回）。"""
        if self._phase != PHASE_CONFIRM or self.engine.interrupted:
            return
        self._enter_phase(PHASE_WAIT_RESULT, self.battle_key)
        # 计时从这里开始，量到的正是旧代码 sleep(20) + wait_any 那一段
        self._battle_cycle = self.engine.timer.begin(self.battle_key)
        if self.initial_blind_wait > 0 and \
                not self.engine.timer.estimate(self.battle_key).converged:
            self.engine.sleep(self.initial_blind_wait)

    def on_result(self, event: StateEvent) -> None:
        """战斗结束（胜利结算或失败）-> 入账 -> 关弹窗 -> 下一格。"""
        if self._phase != PHASE_WAIT_RESULT or self.engine.interrupted:
            return
        if self._battle_cycle is not None:
            self.engine.timer.commit(self._battle_cycle)
            self._battle_cycle = None
        self.log.info("第 %s 格战斗结束：%s", self._cell, event.state)
        # 战斗结束后点一下第一格，关掉结算 / 失败弹窗
        self.engine.click(coords.breakthrough_cell(1), state_key=event.key,
                          detail="关掉结算弹窗")
        self.engine.sleep(self.result_pause)
        self._advance()

    def on_poll(self, event: PollEvent) -> None:
        """各阶段预算检查 + 准备界面上的确认补点。"""
        if self.engine.interrupted:
            return
        waited = self.engine.elapsed_round() - self._phase_started_at

        if self._phase == PHASE_WAIT_PREPARE:
            if waited > self.attack_timeout:
                # 等价旧代码 expect(BATTLE_PREPARE_ALT, timeout=ATTACK_TIMEOUT)
                self.engine.fail(
                    StateTimeoutError(BATTLE_PREPARE_ALT.key, self.attack_timeout))
            return

        if self._phase == PHASE_CONFIRM:
            # 旧代码 wait_gone(BATTLE_PREPARE_ALT, on_wait=lambda: click(CONFIRM))
            if event.hit and event.state_key == BATTLE_PREPARE_ALT.key:
                self.engine.click(coords.BREAKTHROUGH_CONFIRM, detail="点确认开战")
            if waited > self.battle_timeout:
                self.log.warning("准备界面超过 %.0f 秒未消失，按战斗已开始继续",
                                 self.battle_timeout)
                self.on_prepare_gone()
            return

        if self._phase == PHASE_WAIT_RESULT:
            if self._battle_cycle is not None and \
                    self._battle_cycle.elapsed() > self.battle_timeout:
                # 旧代码 wait_any 超时只告警，然后 sleep(2) 进下一格
                self.engine.timer.discard(self._battle_cycle, "战斗结果超时")
                self._battle_cycle = None
                self.log.warning("第 %s 格战斗结果未识别到", self._cell)
                self.engine.sleep(self.cell_pause)
                self._advance()

    # ------------------------------------------------------------------ 内部
    def _enter_phase(self, phase: str, timing_key: Optional[str]) -> None:
        self._phase = phase
        self._phase_started_at = self.engine.elapsed_round()
        self.engine.begin_wait(timing_key, self.poll_interval)

    def _open_cell(self, cell: int) -> None:
        """打开第 cell 格：有「进攻」标记就点它开战，没有就跳过。"""
        self._cell = cell
        self._enter_phase(PHASE_OPEN_CELL, None)
        self.engine.click(coords.breakthrough_cell(cell),
                          detail="打开第 {} 格结界".format(cell))
        self.engine.sleep(self.cell_pause)

        # MARKER_ATTACK 只在打开格子后单独识别一次（等价旧的 locate），不进 watch
        attack = self.engine.peek((MARKER_ATTACK,))
        if attack is None or attack.match is None:
            self.log.info("第 %s 格没有可进攻的结界，跳过", cell)
            self._advance()
            return
        self.log.info("进攻第 %s 格结界", cell)
        self.engine.click(attack.match, state_key=attack.state.key, detail="点进攻")
        self._enter_phase(PHASE_WAIT_PREPARE, None)

    def _advance(self) -> None:
        """推进到下一格；9 格都处理完就刷新列表并结束本轮。"""
        self._phase = PHASE_OPEN_CELL
        if self._cell >= self.cell_count:
            self._refresh_list()
            return
        self._open_cell(self._cell + 1)

    def _refresh_list(self) -> None:
        """9 格处理完后刷新结界列表（旧 _refresh_list）。"""
        self._enter_phase(PHASE_REFRESH, None)
        started = self.engine.elapsed_round()
        attempts = 0
        # 旧代码 wait_gone(MARKER_REFRESH, timeout=120, on_wait=_click_refresh)：
        # 刷新按钮还在就点「刷新 + 确认」，直到它消失或超时
        while self.engine.peek((MARKER_REFRESH,)) is not None:
            if self.engine.elapsed_round() - started > self.refresh_timeout:
                self.log.warning("刷新结界列表超时（%.0f 秒）", self.refresh_timeout)
                break
            attempts += 1
            self.log.info("刷新结界列表（第 %s 次尝试）", attempts)
            self.engine.click(coords.BREAKTHROUGH_REFRESH, detail="点刷新")
            self.engine.click(coords.BREAKTHROUGH_REFRESH_CONFIRM, detail="确认刷新")
            self.engine.sleep(self.poll_interval)
        self.engine.sleep(self.refresh_pause)
        self.engine.finish_round("九宫格一轮完成（含刷新）")


class BreakthroughFlow(Flow):
    """自动结界突破。"""

    name = "breakthrough"
    description = "自动结界突破（九宫格循环）"

    #: 点完一个结界后等「进攻」按钮出现的时间
    ATTACK_TIMEOUT = 20.0
    #: 战斗最长时间
    BATTLE_TIMEOUT = 300.0
    #: 等刷新按钮消失（即刷新完成）的时间
    REFRESH_TIMEOUT = 120.0
    #: 各阶段探测间隔（样本收敛后战斗阶段由计时器改用更细的间隔）
    POLL_INTERVAL = 2.0
    #: 战斗前的固定等待（旧脚本写死 20 秒）；仅在计时样本未收敛时使用
    BATTLE_PRE_WAIT = 20.0
    #: 点开一格之后的停顿
    CELL_PAUSE = 3.0
    #: 战斗结果处理完之后的停顿（旧脚本 sleep(4) + sleep(2)）
    RESULT_PAUSE = 6.0
    #: 刷新完成后的停顿
    REFRESH_PAUSE = 3.0
    #: 整轮兜底超时的余量
    ROUND_TIMEOUT_SLACK = 60.0

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        rounds: Optional[int] = None,
        **kwargs,
    ) -> None:
        """rounds=None 表示无限循环（与旧脚本一致），否则跑指定轮数。"""
        super().__init__(controller=controller, machine=machine, **kwargs)
        self.rounds = rounds

    def run(self) -> None:
        self.click(coords.BREAKTHROUGH_ENTRY)
        self.expect(BREAKTHROUGH_ENTRY, timeout=60)

        engine = self.create_engine()
        BreakthroughSweep(
            engine,
            cell_count=CELL_COUNT,
            attack_timeout=self.ATTACK_TIMEOUT,
            battle_timeout=self.BATTLE_TIMEOUT,
            refresh_timeout=self.REFRESH_TIMEOUT,
            poll_interval=self.POLL_INTERVAL,
            initial_blind_wait=self.BATTLE_PRE_WAIT,
            cell_pause=self.CELL_PAUSE,
            result_pause=self.RESULT_PAUSE,
            refresh_pause=self.REFRESH_PAUSE,
            name=self.name,
        ).attach()
        # 一轮要打满 9 格，兜底超时按「每格最多一次战斗」估
        engine.run_rounds(
            self.rounds,
            round_timeout=(CELL_COUNT * (self.ATTACK_TIMEOUT + self.BATTLE_TIMEOUT
                                         + self.BATTLE_PRE_WAIT)
                           + self.REFRESH_TIMEOUT + self.ROUND_TIMEOUT_SLACK),
        )
