"""自动探索主流程（事件驱动版）。

对应旧 scripts/adventure.py 的 Adventure 类。流程：

    进入副本 -> 选难度 -> 翻页扫怪 -> 打怪（顺带换狗粮）
             -> 战斗结算 -> 领 Boss 奖励 -> 退出 -> 重新进入

一个引擎轮次 = 一次完整的探索（进副本 → 扫怪打怪 → 退出），与旧的 `times` 语义一致。

事件驱动的部分是「战斗」这一段（最耗时、也最该自适应等待的一段）：

    state.entered.EXPLORE_BATTLE_END / EXPLORE_ENTRY / HOME -> 战斗结束，退出结算页回地图
    state.entered.STAMINA_SHORTAGE                          -> 体力耗尽，中止流程

扫怪本身不是模板匹配（用的是 vision 的颜色轮廓检测），所以 `_sweep()` 仍然是
订阅方内部的循环：找到怪就点开打，打不动就翻页，翻满就退出本轮。
`MapNavigator` / `DogFoodManager` 保持原样（它们依赖 Flow 的 click/drag/locate 原语），
由订阅方持有 flow 引用来调用。

与旧实现的差异：
1. 旧代码 `for retry in range(34)` 末尾有一个无条件 break，导致扫怪只跑一轮、
   翻页逻辑形同虚设；上一版已恢复成「翻满 max_page 页才结束本次探索」，保持不变。
2. 怪物坐标由 vision 的颜色检测给出（屏幕坐标），直接交给 controller 点击，
   不再假设屏幕分辨率。
3. 体力耗尽抛 StaminaExhaustedError，由 main.py 统一转成退出码 300；
   现在改成订阅 `state.entered.STAMINA_SHORTAGE`，**任何时刻**出现购买体力弹窗都会中止，
   不再只在「点完怪物」那一瞬间检查。
4. `sleep(BATTLE_PRE_WAIT=30)` 只在计时样本未收敛时使用；收敛后由 core/timing.py
   按 `explore:battle` 的历史 p10 盲等，战斗提前结束就能立刻识别到结算页。
"""
from __future__ import annotations

from typing import List, Optional

from actions.controller import GameController
from config import coordinates as coords
from config import settings
from core.bus import Subscription
from core.errors import StaminaExhaustedError
from core.logger import get_logger
from core.timing import Cycle
from flows.base import Flow
from flows.explore.dog_food import DogFoodManager
from flows.explore.map_navigator import MapNavigator
from flows.signals import (
    PREFIX_STATE_ENTERED,
    TOPIC_POLL_COMPLETED,
    TOPIC_ROUND_STARTED,
    PollEvent,
    RoundEvent,
    StateEvent,
    topic_for,
)
from states.explore_battle_end import EXPLORE_BATTLE_END
from states.explore_entry import EXPLORE_ENTRY
from states.explore_exit_confirm import EXPLORE_EXIT_CONFIRM
from states.explore_map import EXPLORE_MAP
from states.home import HOME
from states.marker_boss_reward import MARKER_BOSS_REWARD
from states.stamina_shortage import STAMINA_SHORTAGE
from vision.types import Box

#: 阶段
PHASE_SWEEP = "sweep"      # 在地图上找怪 / 翻页
PHASE_BATTLE = "battle"    # 已点开始战斗，等结算
PHASE_EXIT = "exit"        # 战斗结束，正在退回地图
PHASE_LEAVE = "leave"      # 本次探索扫完，正在退出副本

#: 战斗结束时可能出现的界面（旧 wait_any 的候选）
BATTLE_END_STATES = (EXPLORE_BATTLE_END, EXPLORE_ENTRY, HOME)


class ExploreSweep:
    """一次探索（进副本 -> 扫怪 -> 退出）的订阅方。"""

    def __init__(self, flow: "ExploreFlow", engine, max_attempts: int, max_page: int,
                 lost_limit: int, battle_timeout: float, battle_interval: float,
                 initial_blind_wait: float, post_battle_pause: float,
                 exp_only: bool = False, name: str = "explore") -> None:
        self.flow = flow
        self.engine = engine
        self.max_attempts = max_attempts
        self.max_page = max_page
        self.lost_limit = lost_limit
        self.battle_timeout = battle_timeout
        self.battle_interval = battle_interval
        self.initial_blind_wait = initial_blind_wait
        self.post_battle_pause = post_battle_pause
        self.exp_only = exp_only
        self.log = get_logger("flows.{}".format(name))

        self.battle_key = "{}:battle".format(name)
        self.map_key = "{}:map".format(name)

        self._subs: List[Subscription] = []
        self._phase = PHASE_SWEEP
        self._battle_cycle: Optional[Cycle] = None
        self._page = 0
        self._lost = 0

    # ------------------------------------------------------------------ 挂载
    def attach(self) -> "ExploreSweep":
        engine = self.engine
        engine.watch(EXPLORE_MAP, *BATTLE_END_STATES, EXPLORE_EXIT_CONFIRM,
                     STAMINA_SHORTAGE)
        self._subs = [
            engine.on(TOPIC_ROUND_STARTED, self.on_round_started, priority=-50),
            engine.on(topic_for(PREFIX_STATE_ENTERED, STAMINA_SHORTAGE), self.on_stamina),
            engine.on(TOPIC_POLL_COMPLETED, self.on_poll),
        ]
        for state in BATTLE_END_STATES:
            self._subs.append(
                engine.on(topic_for(PREFIX_STATE_ENTERED, state), self.on_battle_end))
        return self

    def detach(self) -> None:
        for sub in self._subs:
            self.engine.bus.unsubscribe(sub)
        self._subs = []

    # ------------------------------------------------------------------ 事件
    def on_round_started(self, event: RoundEvent) -> None:
        """新一轮探索：选难度进地图、翻到第一页，然后开始扫怪。"""
        self._battle_cycle = None
        self._page = 0
        self._lost = 0
        self._start_round()
        self._sweep()

    def on_stamina(self, event: StateEvent) -> None:
        """购买体力弹窗 = 体力耗尽，继续跑没有意义。"""
        self.engine.fail(StaminaExhaustedError("体力已耗尽，探索流程停止"))

    def on_battle_end(self, event: StateEvent) -> None:
        """战斗结束（结算页 / 副本入口 / 首页都算）-> 退回地图继续扫怪。"""
        if self._phase != PHASE_BATTLE or self.engine.interrupted:
            return
        if self._battle_cycle is not None:
            self.engine.timer.commit(self._battle_cycle)
            self._battle_cycle = None
        self.log.info("战斗结束，当前界面 %s", event.state)
        self.engine.sleep(self.post_battle_pause)
        self._back_to_map()

    def on_poll(self, event: PollEvent) -> None:
        """战斗阶段预算检查（旧 wait_any 超时只告警，然后照样退出结算页）。"""
        if self._phase != PHASE_BATTLE or self.engine.interrupted:
            return
        if self._battle_cycle is None:
            return
        if self._battle_cycle.elapsed() <= self.battle_timeout:
            return
        self.engine.timer.discard(self._battle_cycle, "战斗结束状态未识别到")
        self._battle_cycle = None
        self.log.warning("战斗结束状态未识别到，按超时继续")
        self.engine.sleep(self.post_battle_pause)
        self._back_to_map()

    # ------------------------------------------------------------------ 单轮
    def _start_round(self) -> None:
        self._phase = PHASE_SWEEP
        self.engine.click(coords.EXPLORE_DIFFICULTY, detail="选择难度进入副本")
        self._wait(EXPLORE_MAP, timeout=60, key=self.map_key)
        self.flow.navigator.next_page()

    def _sweep(self) -> None:
        """在当前副本里翻页找怪并逐个击破。

        打完一只怪之后由 `on_battle_end` 事件重新调用本方法，
        所以这里只在「点开怪但没真的开战」时才继续循环。
        """
        self._phase = PHASE_SWEEP
        for _ in range(self.max_attempts):
            if self.engine.interrupted:
                return
            monsters = self.flow.controller.find_monsters(exp_only=self.exp_only)
            self.log.info("地图第 %s 页，定位到 %s 个怪物", self._page, len(monsters))
            if monsters:
                self._lost = 0
                if self._fight(monsters[0]):
                    return          # 战斗已开打，交给事件驱动继续
            else:
                self._lost += 1
                self.log.info("第 %s 次未找到怪物", self._lost)
                if self._lost >= self.lost_limit:
                    self._page += 1
                    self._lost = 0
                    self.log.info("进入下一页寻找怪物")
                    self.flow.navigator.next_page()
            if self._page > self.max_page:
                self.log.info("已翻满 %s 页，结束本次探索", self.max_page)
                break
        self._leave_round()

    def _fight(self, monster: Box) -> bool:
        """打一只怪。返回 True 表示战斗已开打（调用方应把控制权交回引擎）。"""
        self.log.info("点击怪物 %s", monster.center)
        self.engine.click(monster, detail="点击地图上的怪物")

        if self.engine.peek((STAMINA_SHORTAGE,)) is not None:
            self.engine.fail(StaminaExhaustedError("体力已耗尽，探索流程停止"))
            return False

        self.engine.sleep(2)
        if self.engine.peek((EXPLORE_MAP,)) is not None:
            # 点到的是地图空白处，往右挪一步重新找
            self.engine.click(coords.EXPLORE_MOVE_RIGHT, detail="点到空白处，往右挪一步")
            return False

        self.engine.sleep(1)
        if self.flow.dog_food.needs_change():
            self.log.info("========== 开始替换狗粮 ==========")
            self.flow.dog_food.replace_one()

        self.engine.click(coords.EXPLORE_START_BATTLE, detail="开始战斗")
        self.log.info("开始战斗 ...")
        # 计时从点「开始战斗」这一刻起，把随后的盲等也算进样本
        self._battle_cycle = self.engine.timer.begin(self.battle_key)
        self._phase = PHASE_BATTLE
        self.engine.begin_wait(self.battle_key, self.battle_interval)
        # 样本还没收敛时沿用旧实现写死的 30 秒；收敛后由计时器的盲等取代
        if self.initial_blind_wait > 0 and \
                not self.engine.timer.estimate(self.battle_key).converged:
            self.engine.sleep(self.initial_blind_wait)
        return True

    def _back_to_map(self) -> None:
        """从结算界面退回地图；顺便领 Boss 奖励，必要时重新进副本。"""
        self._phase = PHASE_EXIT
        self.engine.begin_wait(self.map_key, 2.0)
        self.engine.click(coords.EXPLORE_EXIT, detail="退出战斗结算页")
        self._wait(EXPLORE_MAP, timeout=60, key=self.map_key,
                   probe=coords.EXPLORE_EXIT)
        self.log.info("退出单场战斗结算页")
        self.engine.sleep(4)

        if self.engine.peek((EXPLORE_ENTRY,)) is not None:
            self._collect_boss_rewards()
        if self.engine.peek((HOME,)) is not None:
            self.flow.enter_dungeon()
        self.engine.reset_current()      # 让主循环重新识别当前界面
        self._sweep()

    def _collect_boss_rewards(self) -> None:
        """领取章节 Boss 掉落的奖励（旧脚本点两次以关掉弹窗）。"""
        rewards = self.flow.locate_all(MARKER_BOSS_REWARD)
        if not rewards:
            self.log.info("没有可领取的 Boss 奖励")
            return
        for reward in rewards:
            self.engine.click(reward, detail="领取 Boss 奖励")
            self.engine.sleep(1)
            self.engine.click(reward, detail="关掉奖励弹窗")
        self.engine.sleep(3)
        self.log.info("Boss 奖励领取完成")
        if self.engine.peek((HOME,)) is not None:
            self.flow.enter_dungeon()

    def _leave_round(self) -> None:
        """退出本次探索副本，回到入口界面，本轮结束。"""
        self._phase = PHASE_LEAVE
        self.engine.begin_wait(None, 2.0)
        if self.engine.peek((EXPLORE_EXIT_CONFIRM,)) is None:
            self.engine.click(coords.EXPLORE_BACK, detail="点地图左上角返回")
        if self._wait(EXPLORE_EXIT_CONFIRM, timeout=30, key=None) is None:
            self.log.warning("未出现退出确认弹窗，仍尝试点击确定")
        self.engine.click(coords.EXPLORE_EXIT_OK, detail="确认退出探索")
        self.engine.sleep(4)

        if self.engine.peek((EXPLORE_ENTRY,)) is None and \
                self.engine.peek((HOME,)) is not None:
            self.flow.enter_dungeon()
        self.engine.reset_current()
        self.engine.finish_round("一次探索完成")

    # ------------------------------------------------------------------ 工具
    def _wait(self, state, timeout: float, key: Optional[str], probe=None):
        """等某个界面出现；probe 不为空时每拍补点它（旧 on_wait 行为）。"""
        def on_wait(_rounds: int) -> None:
            if probe is not None:
                self.engine.click(probe, detail="等待 {} 时补点".format(state))

        return self.engine.wait_for((state,), timeout=timeout, interval=2.0,
                                    key=key, on_wait=on_wait)


class ExploreFlow(Flow):
    """自动探索。"""

    name = "explore"
    description = "自动探索：扫怪 / 换狗粮 / 领 Boss 奖励 / 退出重进"

    #: 一场战斗最长等待时间
    BATTLE_TIMEOUT = 300.0
    #: 点完「开始战斗」后的固定等待（战斗动画 + 加载）；仅在计时样本未收敛时使用
    BATTLE_PRE_WAIT = 30.0
    #: 战斗结算后的固定等待
    BATTLE_POST_WAIT = 7.0
    #: 单轮探索的最大尝试次数（找怪 + 打怪）
    MAX_ATTEMPTS = 34
    #: 战斗中的探测间隔（样本收敛后由计时器改用更细的间隔）
    BATTLE_INTERVAL = 5.0
    #: 整轮兜底超时的余量
    ROUND_TIMEOUT_SLACK = 120.0

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        times: int = 1,
        exp_only: bool = False,
        **kwargs,
    ) -> None:
        """kwargs 透传给 Flow（bus / timer / adaptive）。"""
        super().__init__(controller=controller, machine=machine, **kwargs)
        self.times = times
        self.exp_only = exp_only
        self.max_page = settings.EXPLORE_MAX_PAGE
        self.lost_limit = settings.EXPLORE_LOST_LIMIT
        self.navigator = MapNavigator(self)
        self.dog_food = DogFoodManager(self)

    # ------------------------------------------------------------------ 主流程
    def run(self) -> None:
        self.enter_dungeon()

        engine = self.create_engine()
        ExploreSweep(
            self,
            engine,
            max_attempts=self.MAX_ATTEMPTS,
            max_page=self.max_page,
            lost_limit=self.lost_limit,
            battle_timeout=self.BATTLE_TIMEOUT,
            battle_interval=self.BATTLE_INTERVAL,
            initial_blind_wait=self.BATTLE_PRE_WAIT,
            post_battle_pause=self.BATTLE_POST_WAIT,
            exp_only=self.exp_only,
            name=self.name,
        ).attach()
        # 一轮里可能打很多只怪，兜底超时按「最多 MAX_ATTEMPTS 场战斗」估
        engine.run_rounds(
            self.times,
            round_timeout=(self.MAX_ATTEMPTS
                           * (self.BATTLE_PRE_WAIT + self.BATTLE_TIMEOUT)
                           + self.ROUND_TIMEOUT_SLACK),
        )

    def enter_dungeon(self) -> None:
        """点右侧副本入口，进入探索。"""
        self.click(coords.EXPLORE_ENTRY)
        self.expect(EXPLORE_ENTRY, timeout=60)
        self.log.info("已进入探索副本选择界面")

    def select_chapter(self) -> None:
        """在章节列表里选第九章（旧脚本的 find_map，默认不启用）。"""
        self.navigator.select_chapter()
