"""自动式神碎片（碎片挑战循环，事件驱动版）。

流程结构与御魂（SoulFlow）完全一致，因此两者共用 flows/battle_cycle.py：

    匹配菱形「挑战」按钮 -> 点击开战
    -> 等战斗结束画面出现 -> 点击结算退出
    -> 回到碎片界面再匹配「挑战」 -> ...

- 开始点击匹配 `states/shard_challenge.py`（菱形挑战按钮模板）；
- 结束判定只匹配 `states/shard_battle_end.py`（碎片结算魂碗画面）——通用结算模板
  在战斗画面里容易误命中，不纳入候选；
- 与御魂的差别只有两处：结算后不需要补点（`EXTRA_SETTLE_CLICKS = 0`），
  但点完结算要缓冲 3 秒（`SETTLE_PAUSE`）；
- macOS 下截屏 / 点击通道默认是「iPhone Mirroring」镜像窗口（见 actions/window.py），
  即 iOS 手机连到 Mac 的屏幕镜像，窗口内的点击会直接透传到手机。
"""
from __future__ import annotations

from typing import Optional, Tuple

from actions.controller import GameController
from flows.base import Flow
from flows.battle_cycle import BattleCycle
from states.shard_battle_end import SHARD_BATTLE_END
from states.shard_challenge import SHARD_CHALLENGE


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
    #: 结算后等挑战界面回来的超时
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
        **kwargs,
    ) -> None:
        """kwargs 透传给 Flow（bus / timer / adaptive）。"""
        super().__init__(controller=controller, machine=machine, **kwargs)
        self.times = times

    # ------------------------------------------------------------------ 主流程
    def run(self) -> None:
        self.log.info("开始刷式神碎片，共 %s 次", self.times)
        engine = self.create_engine()
        BattleCycle(
            engine,
            challenge=SHARD_CHALLENGE,
            end_states=self.END_STATES,
            battle_interval=self.BATTLE_INTERVAL,
            extra_settle_clicks=0,
            settle_pause=self.SETTLE_PAUSE,
            back_timeout=self.BACK_TIMEOUT,
            challenge_timeout=self.CHALLENGE_TIMEOUT,
            battle_timeout=self.BATTLE_TIMEOUT,
            missing_challenge_message=self.MISSING_CHALLENGE_MESSAGE,
        ).attach()
        engine.run_rounds(
            self.times,
            round_timeout=(self.CHALLENGE_TIMEOUT + self.BATTLE_TIMEOUT
                           + self.ROUND_TIMEOUT_SLACK),
        )
