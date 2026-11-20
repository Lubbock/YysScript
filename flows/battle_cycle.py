"""「挑战 -> 战斗 -> 结算 -> 回到挑战」这条通用链的事件订阅方。

御魂（soul）与式神碎片（shard）的循环结构完全一样，只有状态、间隔、
结算后要不要补点几次的差别。以前是两份几乎复制粘贴的 run()，
现在都变成「组装一个 BattleCycle 挂到引擎上」：

    engine = FlowEngine("soul", self.machine, self.controller, bus=self.bus)
    BattleCycle(engine, challenge=SOUL_CHALLENGE, end_states=(SHARD_BATTLE_END,),
                extra_settle_clicks=4, retry_pause=2.0).attach()
    engine.run_rounds(self.times, round_timeout=...)

本模块**只订阅事件、只调用 engine 的公开方法**，不直接碰 machine / controller，
因此：
- 引擎不认识任何玩法，玩法也不需要知道引擎怎么轮询；
- 加一条规则（例如结算后先关掉某个弹窗）= 再加一个订阅方，不用改这里也不用改 flow；
- 单测可以用假 machine + 假 controller 直接驱动，不需要 cv2 / 截图。

阶段（phase）与计时 key：
    challenge : 等挑战按钮出现            -> "<flow>:challenge"
    battle    : 已点挑战，等结算画面      -> "<flow>:battle"
    settle    : 已点结算，等回到挑战界面  -> 计入 "<flow>:challenge"
引擎另外自动记 "<flow>:round"（整轮）与 "<flow>:probe"（一次识图成本）。
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from config import settings
from core.bus import Subscription
from core.errors import FlowAbortedError
from core.logger import get_logger
from core.timing import Cycle
from flows.engine import FlowEngine
from flows.signals import (
    PREFIX_STATE_ENTERED,
    TOPIC_POLL_COMPLETED,
    TOPIC_ROUND_STARTED,
    TOPIC_STATE_TIMEOUT,
    PollEvent,
    RoundEvent,
    StateEvent,
    TimeoutEvent,
    topic_for,
)

#: 阶段
PHASE_CHALLENGE = "challenge"
PHASE_BATTLE = "battle"
PHASE_SETTLE = "settle"


class BattleCycle:
    """挑战循环的订阅方集合。

    参数：
        engine            : 要挂载的 FlowEngine
        challenge         : 挑战按钮对应的 State（例如 SOUL_CHALLENGE）
        end_states        : 表示战斗结束的 State 序列（例如 (SHARD_BATTLE_END,)）
        battle_interval   : 战斗中的探测间隔（未收敛时用），对应旧 BATTLE_INTERVAL
        challenge_interval: 等挑战按钮时的探测间隔，默认 settings.DEFAULT_WAIT_INTERVAL
        extra_settle_clicks: 点完结算后，若没回到挑战界面最多补点几次（御魂的掉落界面需要）
        settle_pause      : 点完结算后的缓冲等待（碎片用 3 秒，御魂用 0）
        retry_pause       : 每次补点之间的缓冲等待（御魂用 2 秒）
        back_timeout      : 每次「等挑战界面回来」的超时
        back_interval     : 等挑战界面回来的轮询间隔
        challenge_timeout : 一轮里等挑战按钮的预算，超了就按旧行为中止流程；None 表示不检查
        battle_timeout    : 一场战斗的预算，超了就按旧行为告警并进入下一轮；None 表示不检查
        missing_challenge_message: 挑战按钮始终没出现时的报错文案（保持与旧实现一致）
    """

    def __init__(
        self,
        engine: FlowEngine,
        challenge: Any,
        end_states: Sequence,
        battle_interval: float = 3.0,
        challenge_interval: Optional[float] = None,
        extra_settle_clicks: int = 0,
        settle_pause: float = 0.0,
        retry_pause: float = 2.0,
        back_timeout: float = 6.0,
        back_interval: float = 2.0,
        challenge_timeout: Optional[float] = None,
        battle_timeout: Optional[float] = None,
        missing_challenge_message: Optional[str] = None,
        name: Optional[str] = None,
    ) -> None:
        self.engine = engine
        self.challenge = challenge
        self.end_states: Tuple[Any, ...] = tuple(end_states)
        self.name = name or engine.name
        self.log = get_logger("flows.{}".format(self.name))

        self.battle_interval = float(battle_interval)
        # None 归一成默认探测间隔：begin_wait(key, None) 的语义是「沿用当前值」，
        # 而当前值可能已被战斗阶段改成 battle_interval，会让挑战阶段越跑越慢
        self.challenge_interval = (settings.DEFAULT_WAIT_INTERVAL
                                   if challenge_interval is None
                                   else float(challenge_interval))
        self.extra_settle_clicks = int(extra_settle_clicks)
        self.settle_pause = float(settle_pause)
        self.retry_pause = float(retry_pause)
        self.back_timeout = float(back_timeout)
        self.back_interval = float(back_interval)
        self.challenge_timeout = challenge_timeout
        self.battle_timeout = battle_timeout
        self.missing_challenge_message = missing_challenge_message or (
            "未匹配到挑战按钮，请确认手机停在{}界面（镜像窗口可见该按钮）".format(
                getattr(challenge, "label", "挑战")))

        #: 计时 key
        self.battle_key = "{}:battle".format(self.name)
        self.challenge_key = "{}:challenge".format(self.name)
        #: 挑战状态的 key，用于在 poll.completed 里判断「这一拍是不是命中了挑战按钮」
        self._challenge_state_key = getattr(challenge, "key", str(challenge))

        self._subs: List[Subscription] = []
        self._phase = PHASE_CHALLENGE
        self._challenge_seen = False
        self._battle_cycle: Optional[Cycle] = None

    # ------------------------------------------------------------------ 挂载
    def attach(self) -> "BattleCycle":
        """登记要识别的状态并订阅事件；返回自身以便链式调用。"""
        engine = self.engine
        engine.watch(self.challenge, *self.end_states)
        self._subs = [
            engine.on(TOPIC_ROUND_STARTED, self.on_round_started, priority=-50),
            engine.on(topic_for(PREFIX_STATE_ENTERED, self.challenge), self.on_challenge),
            engine.on(TOPIC_POLL_COMPLETED, self.on_poll),
            engine.on(TOPIC_STATE_TIMEOUT, self.on_timeout),
        ]
        for end in self.end_states:
            self._subs.append(
                engine.on(topic_for(PREFIX_STATE_ENTERED, end), self.on_settlement))
        # 一轮开始时引擎会广播 round.started，这里先把节奏设成「等挑战」
        engine.begin_wait(self.challenge_key, self.challenge_interval)
        return self

    def detach(self) -> None:
        """退订全部事件。"""
        for sub in self._subs:
            self.engine.bus.unsubscribe(sub)
        self._subs = []

    # ------------------------------------------------------------------ 事件
    def on_round_started(self, event: RoundEvent) -> None:
        """新一轮：回到「等挑战」阶段，重置本轮的状态与计时。"""
        self._phase = PHASE_CHALLENGE
        self._challenge_seen = False
        self._battle_cycle = None
        self.engine.begin_wait(self.challenge_key, self.challenge_interval)

    def on_challenge(self, event: StateEvent) -> None:
        """看到挑战按钮 -> 点击开战，并切到「等结算」节奏。"""
        if self._phase != PHASE_CHALLENGE:
            self.log.debug("当前处于 %s 阶段，忽略挑战按钮命中", self._phase)
            return
        if self.engine.interrupted:
            self.log.debug("引擎已被要求停止 / 中止，忽略挑战按钮命中")
            return
        if event.match is None:
            return
        self._phase = PHASE_BATTLE
        self._challenge_seen = True
        self.engine.click(event.match, state_key=event.key, detail="点击挑战，进入战斗")
        self.log.info("已点击挑战，进入战斗")
        self._battle_cycle = self.engine.timer.begin(self.battle_key)
        self.engine.begin_wait(self.battle_key, self.battle_interval)

    def on_settlement(self, event: StateEvent) -> None:
        """看到结算画面 -> 点掉它 -> 回到挑战界面。

        两种情况：
        1. phase == battle：正常打完一场，记 battle 耗时并结束本轮；
        2. 其它阶段：上一轮残留的结算画面（旧代码的 _dismiss_settlement），
           点掉之后不结束本轮，继续等挑战按钮。
        """
        if event.match is None:
            return
        in_battle = self._phase == PHASE_BATTLE
        if in_battle:
            self._phase = PHASE_SETTLE
            self.log.info("战斗结束，结算画面 %s", event.state)
            # battle 计时必须在「检测到结算」这一刻就结束：这个 key 的盲等只覆盖
            # 点挑战 -> 出现结算 这一段。要是把点结算 / 补点 / 等回挑战界面的时间
            # 也算进样本，盲等就会逐轮自我放大（下一轮等得更久 -> 样本更大 -> ...），
            # 正好是 core/timing.py 要防的不收敛。回挑战界面的耗时另记 challenge key。
            self._commit_battle()
        else:
            self.log.info("检测到残留结算画面 %s，先点击退出", event.state)
        settle_match = event.match
        self.engine.click(settle_match, state_key=event.key, detail="点击结算")
        if self.settle_pause > 0:
            self.engine.sleep(self.settle_pause)

        back = self._back_to_challenge(settle_match)
        if in_battle:
            self.engine.finish_round("结算完成，已回到挑战界面" if back else "结算完成")
        else:
            # 残留结算已处理：让引擎重新识别一次当前画面，好触发挑战按钮的 entered
            self.engine.reset_current()

    def on_poll(self, event: PollEvent) -> None:
        """每次识图后检查阶段预算，复现旧实现的两种超时行为。"""
        if self._phase == PHASE_CHALLENGE:
            # 命中优先于超时判定：poll.completed 比 state.entered 先发一拍，
            # 如果这一拍正好识别到了挑战按钮，就不能按「挑战按钮没出现」中止 ——
            # 否则会先点挑战开战、再抛异常退出，把战斗丢在那儿没人收尾。
            # 旧的 machine.wait_for 也是每轮先判命中、再判超时。
            if event.hit and event.state_key == self._challenge_state_key:
                return
            if self.challenge_timeout is not None and \
                    self.engine.elapsed_round() > self.challenge_timeout:
                self.engine.fail(FlowAbortedError(self.missing_challenge_message))
            return
        if self._phase == PHASE_BATTLE and self.battle_timeout is not None:
            if self._battle_cycle is not None and \
                    self._battle_cycle.elapsed() > self.battle_timeout:
                self.log.warning("未识别到战斗结算，按超时继续下一轮")
                self._discard_battle("战斗超时（上限 {:.0f} 秒）".format(self.battle_timeout))
                self.engine.finish_round("战斗超时")

    def on_timeout(self, event: TimeoutEvent) -> None:
        """引擎层面的整轮超时兜底（正常情况由 on_poll 先触发）。"""
        if not self._challenge_seen and self._phase == PHASE_CHALLENGE:
            self.engine.fail(FlowAbortedError(self.missing_challenge_message))
            return
        if self._battle_cycle is not None:
            self.log.warning("未识别到战斗结算，按超时继续下一轮")
            self._discard_battle("整轮超时")
        self._phase = PHASE_CHALLENGE

    # ------------------------------------------------------------------ 内部
    def _back_to_challenge(self, settle_match: Any) -> bool:
        """点完结算后等挑战界面回来；御魂的掉落界面需要补点几次（旧行为保留）。

        这里的等待是订阅方内部的阻塞等待，publish=False：
        命中 / 超时都不广播，避免反过来驱动主循环造成重入。
        """
        challenge_cycle = self.engine.timer.begin(self.challenge_key)
        found = False
        for extra in range(self.extra_settle_clicks):
            if self._wait_challenge():
                found = True
                break
            self.log.info("未检测到挑战界面，补点第 %s 次", extra + 1)
            self.engine.click(settle_match, detail="补点结算画面")
            self.engine.sleep(self.retry_pause)
        if not found:
            found = self._wait_challenge()
        if found:
            self.engine.timer.commit(challenge_cycle)
        else:
            self.engine.timer.discard(challenge_cycle, "仍未回到挑战界面")
            self.log.warning("%s仍未回到挑战界面，下一轮等待挑战按钮时兜底",
                             "补点后" if self.extra_settle_clicks else "")
        return found

    def _wait_challenge(self) -> bool:
        detection = self.engine.wait_for(
            (self.challenge,),
            timeout=self.back_timeout,
            interval=self.back_interval,
            key=self.challenge_key,
        )
        return detection is not None

    def _commit_battle(self) -> None:
        if self._battle_cycle is None:
            return
        self.engine.timer.commit(self._battle_cycle)
        self._battle_cycle = None

    def _discard_battle(self, reason: str) -> None:
        if self._battle_cycle is None:
            return
        self.engine.timer.discard(self._battle_cycle, reason)
        self._battle_cycle = None
