"""自动式神碎片（碎片挑战循环，事件驱动版）。

全程用模板匹配驱动的挑战循环：

    匹配菱形「挑战」按钮 -> 点击开战
    -> 等战斗结束画面出现 -> 点击结算退出
    -> 重新挑战 -> ...

**重新挑战的入口有两种，而且跑着跑着会变**（同一轮里可能出现任意一种，
不是开局能选定的），所以两条路同时监听、按屏幕上实际出现的界面走：

1. 直接回到挑战按钮界面 -> `BattleCycle` 收到 `state.entered.SHARD_CHALLENGE`，直接开战；
2. 被踢回探索章节界面（如「第十八章」+ 三个头像）-> `ShardEntryNav` 导航一圈：
   点章节界面上的 Boss 头像 -> 等「式神碎片」入口面板并点击 ->
   等碎片列表行（头像 + 等级）并点击 -> 回到挑战按钮界面，交给 `BattleCycle`。

实现要点：
- 导航订阅方是**状态响应式**的（看到哪个导航界面就点哪个），不做线性阶段门控 ——
  一轮可能从任意界面开始（挑战 / 章节 / 面板 / 列表），线性门控会把开局界面挡死；
- `engine.watch()` 的登记顺序里 `SHARD_CHALLENGE` 排第一：挑战界面上列表行模板
  也会误命中（实测 0.79），必须让更确定的挑战按钮优先；列表行排在章节头像前面：
  列表界面上两个模板都命中（行内含同一个头像），更具体的列表行应该赢；
- 结算后不等挑战界面回来（`wait_back=False`）：下一轮开局时屏幕上是什么就走什么，
  两种入口天然都被覆盖。

- 开始点击匹配 `states/shard_challenge.py`（菱形挑战按钮模板）；
- 结束判定只匹配 `states/shard_battle_end.py`（碎片结算魂碗画面）——通用结算模板
  在战斗画面里容易误命中，不纳入候选；
- macOS 下截屏 / 点击通道默认是「iPhone Mirroring」镜像窗口（见 actions/window.py），
  即 iOS 手机连到 Mac 的屏幕镜像，窗口内的点击会直接透传到手机。
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from actions.controller import GameController
from core.bus import Subscription
from core.logger import get_logger
from flows.base import Flow
from flows.battle_cycle import BattleCycle
from flows.signals import (
    PREFIX_STATE_ENTERED,
    TOPIC_POLL_COMPLETED,
    PollEvent,
    StateEvent,
    topic_for,
)
from states.shard_battle_end import SHARD_BATTLE_END
from states.shard_chapter_boss import SHARD_CHAPTER_BOSS
from states.shard_challenge import SHARD_CHALLENGE
from states.shard_fragment_entry import SHARD_FRAGMENT_ENTRY
from states.shard_fragment_row import SHARD_FRAGMENT_ROW

#: 同一个导航界面停留超过这么久还没离开，就再点一次（游戏偶发吞点击）
NAV_STUCK_RETRY = 8.0


class ShardEntryNav:
    """章节入口导航订阅方：头像 -> 入口面板 -> 列表行，看到哪个点哪个。

    不做阶段门控：一轮可能从任意界面开始，且两种入口会随机交替出现，
    线性门控（必须先 A 再 B 再 C）会把「开局就在列表界面」这种情况挡死。
    靠两点保证不乱点：
    1. `state.entered` 只在界面**跳变**时触发，停留在同一界面不会重复点；
    2. watch 顺序让更确定的模板优先（挑战按钮 > 列表行 > 面板 > 头像）。
    """

    def __init__(self, engine) -> None:
        self.engine = engine
        self.log = get_logger("flows.{}".format(engine.name))
        self._subs: List[Subscription] = []
        #: 最近一次导航点击：(状态 key, 本轮内时刻, 命中框)，用于卡住重试
        self._last_click_key = ""
        self._last_click_at = -1.0
        self._last_click_match = None

    # ------------------------------------------------------------------ 挂载
    def attach(self) -> "ShardEntryNav":
        engine = self.engine
        # 顺序即 detect_first 的优先级：
        # - 挑战按钮第一：挑战界面上列表行模板会误命中（实测 0.79），不能让它挡住挑战
        # - 列表行在头像前：列表界面上两者都命中（行内含同一个头像），取更具体的行
        engine.watch(SHARD_CHALLENGE, SHARD_FRAGMENT_ROW, SHARD_FRAGMENT_ENTRY,
                     SHARD_CHAPTER_BOSS, SHARD_BATTLE_END)
        self._subs = [
            engine.on(topic_for(PREFIX_STATE_ENTERED, SHARD_CHAPTER_BOSS), self.on_boss),
            engine.on(topic_for(PREFIX_STATE_ENTERED, SHARD_FRAGMENT_ENTRY), self.on_entry),
            engine.on(topic_for(PREFIX_STATE_ENTERED, SHARD_FRAGMENT_ROW), self.on_row),
            engine.on(TOPIC_POLL_COMPLETED, self.on_poll),
        ]
        return self

    def detach(self) -> None:
        for sub in self._subs:
            self.engine.bus.unsubscribe(sub)
        self._subs = []

    # ------------------------------------------------------------------ 事件
    def on_boss(self, event: StateEvent) -> None:
        """章节界面：点 Boss 头像，打开「式神碎片」入口面板。"""
        self._click(event, "点击章节 Boss 头像")

    def on_entry(self, event: StateEvent) -> None:
        """入口面板：点它，进入碎片列表。"""
        self._click(event, "点击式神碎片入口面板")

    def on_row(self, event: StateEvent) -> None:
        """碎片列表行：点它，进入挑战界面（之后由 BattleCycle 接手）。"""
        self._click(event, "点击碎片列表行")

    def on_poll(self, event: PollEvent) -> None:
        """卡在同一个导航界面太久（游戏吞了点击）就再点一次。"""
        if self.engine.interrupted or not self._last_click_key:
            return
        if event.state_key != self._last_click_key:
            return
        waited = self.engine.elapsed_round() - self._last_click_at
        if waited < NAV_STUCK_RETRY:
            return
        target = self._retry_target()
        if target is None:
            return
        self.log.warning("停留在 %s 超过 %.0f 秒，补点一次", self._last_click_key, waited)
        self._last_click_at = self.engine.elapsed_round()
        self.engine.click(target, state_key=self._last_click_key,
                          detail="补点 {}".format(self._last_click_key))

    def _retry_target(self):
        """补点的目标坐标。

        `PollEvent` 不带 match —— 它描述的是「这一拍识图的结论」，不含命中框；
        而且 poll.completed 在引擎更新 `current` **之前**广播，所以这里读到的是上一拍
        的命中。优先用它（窗口可能被挪动过，新鲜坐标比存下来的旧坐标更准），
        状态对不上就退回上次点击时记下的 match。
        """
        current = self.engine.current
        if current is not None and current.state.key == self._last_click_key:
            return current.match
        return self._last_click_match

    # ------------------------------------------------------------------ 内部
    def _click(self, event: StateEvent, detail: str) -> None:
        if self.engine.interrupted or event.match is None:
            return
        if self.engine.click(event.match, state_key=event.key, detail=detail) is None:
            # 点击没送达（窗口激活失败）：重置当前状态，下一拍重新触发 entered 再点
            self.engine.reset_current()
            return
        self._last_click_key = event.key
        self._last_click_at = self.engine.elapsed_round()
        self._last_click_match = event.match


class ShardFlow(Flow):
    """自动刷式神碎片。"""

    name = "shard"
    description = "自动式神碎片：匹配挑战 -> 等结算 -> 点结算 -> 再挑战"

    #: 等待挑战按钮出现的超时（含退出结算画面 / 章节导航的时间）
    CHALLENGE_TIMEOUT = 120.0
    #: 单场战斗最长等待时间
    BATTLE_TIMEOUT = 300.0
    #: 战斗中的轮询间隔（历史样本不足时用；收敛后由计时器给出更细的间隔）
    BATTLE_INTERVAL = 3.0
    #: 点完结算后的缓冲等待
    SETTLE_PAUSE = 3.0
    #: 整轮兜底超时 = 两个阶段预算 + 这个余量（正常情况由阶段预算先触发）
    ROUND_TIMEOUT_SLACK = 30.0

    #: 表示战斗结束的界面。只用碎片自己的结算模板：通用结算模板（妖气封印 /
    #: 探索等）在碎片战斗画面里会误命中，导致战斗中乱点。
    END_STATES: Tuple = (SHARD_BATTLE_END,)

    #: 挑战按钮始终没出现时的报错文案（与旧实现保持一致）
    MISSING_CHALLENGE_MESSAGE = (
        "未匹配到挑战按钮，请确认手机停在式神碎片界面（镜像窗口可见该按钮）"
    )

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        times: int = 10,
        **kwargs: Any,
    ) -> None:
        """kwargs 透传给 Flow（bus / timer / adaptive / clock / sleeper）。"""
        super().__init__(controller=controller, machine=machine, **kwargs)
        self.times = times

    # ------------------------------------------------------------------ 主流程
    def run(self) -> None:
        self.log.info("开始刷式神碎片，共 %s 次", self.times)
        engine = self.create_engine()
        # 两种重新挑战的入口同时监听：直接回挑战界面 / 回章节界面需导航一圈
        ShardEntryNav(engine).attach()
        BattleCycle(
            engine,
            challenge=SHARD_CHALLENGE,
            end_states=self.END_STATES,
            battle_interval=self.BATTLE_INTERVAL,
            extra_settle_clicks=0,
            settle_pause=self.SETTLE_PAUSE,
            # 结算后下一屏可能是挑战界面也可能是章节界面，不在这里等，
            # 交给下一轮开局时「屏幕上是什么就走什么」
            wait_back=False,
            challenge_timeout=self.CHALLENGE_TIMEOUT,
            battle_timeout=self.BATTLE_TIMEOUT,
            missing_challenge_message=self.MISSING_CHALLENGE_MESSAGE,
        ).attach()
        engine.run_rounds(
            self.times,
            round_timeout=(self.CHALLENGE_TIMEOUT + self.BATTLE_TIMEOUT
                           + self.ROUND_TIMEOUT_SLACK),
        )
