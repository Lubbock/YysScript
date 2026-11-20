"""自动式神碎片（碎片挑战循环，事件驱动版，双模式）。

两种模式（`--shard-mode` 切换，默认 simple）：

**simple（原有模式）**：全程用模板匹配驱动的挑战循环 ——

    匹配菱形「挑战」按钮 -> 点击开战
    -> 等战斗结束画面出现 -> 点击结算退出
    -> 回到碎片界面再匹配「挑战」 -> ...

**chapter（章节入口模式）**：有些入口打完一场后**不会**回到挑战按钮界面，
而是被踢回探索章节界面，需要手动导航一圈才能重新挑战：

    结算点完 -> 章节界面（Boss 头像，如「第十八章」）-> 点击头像
             -> 等「式神碎片」入口面板 -> 点击
             -> 等碎片列表行（头像 + 等级）-> 点击
             -> 回到挑战界面，由既有的 SHARD_CHALLENGE（第一个配置的模板）接手开战

导航链由本文件的 `ShardChapterNav` 订阅方实现：它只订阅三个
`state.entered.<KEY>` 事件、只调 `engine.click()`，点完列表行之后什么都不用做 ——
挑战按钮出现时 `BattleCycle` 自然会收到它自己的 entered 事件，流程就接上了。

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
from core.errors import ConfigError
from flows.base import Flow
from flows.battle_cycle import BattleCycle
from flows.signals import (
    PREFIX_STATE_ENTERED,
    TOPIC_ROUND_STARTED,
    RoundEvent,
    StateEvent,
    topic_for,
)
from states.shard_battle_end import SHARD_BATTLE_END
from states.shard_chapter_boss import SHARD_CHAPTER_BOSS
from states.shard_challenge import SHARD_CHALLENGE
from states.shard_fragment_entry import SHARD_FRAGMENT_ENTRY
from states.shard_fragment_row import SHARD_FRAGMENT_ROW

#: 模式：结算后直接回挑战界面
MODE_SIMPLE = "simple"
#: 模式：结算后回章节界面，需要 头像 -> 面板 -> 列表行 导航一圈
MODE_CHAPTER = "chapter"
MODES = (MODE_SIMPLE, MODE_CHAPTER)

#: 导航阶段
PHASE_BOSS = "boss"      # 等章节界面上的 Boss 头像
PHASE_ENTRY = "entry"    # 等「式神碎片」入口面板
PHASE_ROW = "row"        # 等碎片列表行
PHASE_DONE = "done"      # 导航完成，等 BattleCycle 接手挑战按钮


class ShardChapterNav:
    """章节入口模式的导航订阅方：头像 -> 入口面板 -> 列表行。

    每一步都是「识别到就点、点完推进阶段」；点击未送达（窗口激活失败）时
    重置引擎当前状态，下一拍会重新广播 entered 自动重试。
    阶段门控保证不会在错误的界面上乱点（例如列表行界面上也能匹配到
    Boss 头像模板，但那时阶段已经是 row/done，entered(SHARD_CHAPTER_BOSS) 会被忽略）。
    """

    def __init__(self, engine) -> None:
        self.engine = engine
        self._subs: List[Subscription] = []
        self._phase = PHASE_BOSS

    # ------------------------------------------------------------------ 挂载
    def attach(self) -> "ShardChapterNav":
        engine = self.engine
        # 登记顺序有讲究：列表行模板里含有和章节头像相同的头像，列表界面上两者
        # 都会命中，detect_first 按 watch 顺序取先命中的，所以 ROW 必须排在 BOSS 前
        engine.watch(SHARD_FRAGMENT_ROW, SHARD_FRAGMENT_ENTRY, SHARD_CHAPTER_BOSS)
        self._subs = [
            engine.on(TOPIC_ROUND_STARTED, self.on_round_started, priority=-50),
            engine.on(topic_for(PREFIX_STATE_ENTERED, SHARD_CHAPTER_BOSS), self.on_boss),
            engine.on(topic_for(PREFIX_STATE_ENTERED, SHARD_FRAGMENT_ENTRY), self.on_entry),
            engine.on(topic_for(PREFIX_STATE_ENTERED, SHARD_FRAGMENT_ROW), self.on_row),
        ]
        return self

    def detach(self) -> None:
        for sub in self._subs:
            self.engine.bus.unsubscribe(sub)
        self._subs = []

    # ------------------------------------------------------------------ 事件
    def on_round_started(self, event: RoundEvent) -> None:
        self._phase = PHASE_BOSS

    def on_boss(self, event: StateEvent) -> None:
        """章节界面：点 Boss 头像，打开「式神碎片」入口面板。"""
        self._click(event, PHASE_BOSS, PHASE_ENTRY, "点击章节 Boss 头像")

    def on_entry(self, event: StateEvent) -> None:
        """入口面板：点它，进入碎片列表。"""
        self._click(event, PHASE_ENTRY, PHASE_ROW, "点击式神碎片入口面板")

    def on_row(self, event: StateEvent) -> None:
        """碎片列表行：点它，进入挑战界面（之后由 BattleCycle 接手）。"""
        self._click(event, PHASE_ROW, PHASE_DONE, "点击碎片列表行")

    # ------------------------------------------------------------------ 内部
    def _click(self, event: StateEvent, expected: str, next_phase: str,
               detail: str) -> None:
        if self._phase != expected or self.engine.interrupted:
            return
        if event.match is None:
            return
        if self.engine.click(event.match, state_key=event.key, detail=detail) is None:
            # 点击没送达：重置当前状态，下一拍重新触发 entered 再点一次
            self.engine.reset_current()
            return
        self._phase = next_phase


class ShardFlow(Flow):
    """自动刷式神碎片。"""

    name = "shard"
    description = "自动式神碎片：匹配挑战 -> 等结算 -> 点结算 -> 再挑战"

    #: 等待挑战按钮出现的超时（含退出结算画面的时间）
    CHALLENGE_TIMEOUT = 120.0
    #: 单场战斗最长等待时间
    BATTLE_TIMEOUT = 300.0
    #: 战斗中的轮询间隔（历史样本不足时用；收敛后由计时器给出更细的间隔）
    BATTLE_INTERVAL = 3.0
    #: 点完结算后的缓冲等待
    SETTLE_PAUSE = 3.0
    #: 结算后等挑战界面回来的超时（仅 simple 模式用）
    BACK_TIMEOUT = 6.0
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
        mode: str = MODE_SIMPLE,
        **kwargs: Any,
    ) -> None:
        """
        times : 刷多少次
        mode  : MODE_SIMPLE（结算后直接回挑战界面）或
                MODE_CHAPTER（结算后回章节界面，需导航 头像->面板->列表行）
        kwargs: 透传给 Flow（bus / timer / adaptive）
        """
        if mode not in MODES:
            raise ConfigError("未知的碎片模式: {}（可用: {}）".format(
                mode, " / ".join(MODES)))
        super().__init__(controller=controller, machine=machine, **kwargs)
        self.times = times
        self.mode = mode

    # ------------------------------------------------------------------ 主流程
    def run(self) -> None:
        self.log.info("开始刷式神碎片，共 %s 次，模式=%s", self.times, self.mode)
        engine = self.create_engine()
        if self.mode == MODE_CHAPTER:
            ShardChapterNav(engine).attach()
        BattleCycle(
            engine,
            challenge=SHARD_CHALLENGE,
            end_states=self.END_STATES,
            battle_interval=self.BATTLE_INTERVAL,
            extra_settle_clicks=0,
            settle_pause=self.SETTLE_PAUSE,
            back_timeout=self.BACK_TIMEOUT,
            # 章节模式下点完结算去的是章节界面，挑战按钮要导航一圈才出现，
            # 不能在这里傻等它回来
            wait_back=self.mode == MODE_SIMPLE,
            challenge_timeout=self.CHALLENGE_TIMEOUT,
            battle_timeout=self.BATTLE_TIMEOUT,
            missing_challenge_message=self.MISSING_CHALLENGE_MESSAGE,
        ).attach()
        engine.run_rounds(
            self.times,
            round_timeout=(self.CHALLENGE_TIMEOUT + self.BATTLE_TIMEOUT
                           + self.ROUND_TIMEOUT_SLACK),
        )
