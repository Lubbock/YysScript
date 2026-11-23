"""自动御魂（事件驱动版）。

旧 scripts/soul.py 是纯定时流程（点坐标 → 固定等 80 秒 → 点坐标），
上一版改成模板匹配驱动的命令式循环，这一版再进一步：流程本体不再写
「等挑战 → 点挑战 → 等结算 → 点结算」的硬编码链条，而是

    引擎轮询识图 -> 广播 state.entered.<KEY> -> BattleCycle 订阅方决定动作

好处：
1. 规则可插拔 —— 想在结算后先关掉某个弹窗，再加一个订阅方即可，不用改本文件；
2. 一整轮 / 一场战斗花多久会被记下来（core/timing.py），
   之后引擎先「盲等」到接近真实耗时再开始细粒度识图，
   把御魂这种「大部分时间在空等截图」的流程的无用截图压到最低；
3. 与式神碎片（shard）共用同一个 BattleCycle，两份复制粘贴的循环合成一份。

macOS 下截屏 / 点击通道默认是「iPhone Mirroring」镜像窗口（见 actions/window.py）。
"""
from __future__ import annotations

from typing import Optional, Tuple

from actions.controller import GameController
from flows.base import Flow
from flows.battle_cycle import BattleCycle
from states.shard_battle_end import SHARD_BATTLE_END
from states.soul_challenge import SOUL_CHALLENGE


class SoulFlow(Flow):
    """自动刷御魂。"""

    name = "soul"
    description = "自动御魂：匹配挑战 -> 等结算 -> 点回挑战界面"
    #: 等待挑战按钮出现的超时（含退出结算画面的时间）
    CHALLENGE_TIMEOUT = 120.0
    #: 单场战斗最长等待时间
    BATTLE_TIMEOUT = 300.0
    #: 战斗中的轮询间隔（历史样本不足时用；收敛后由计时器给出更细的间隔）
    BATTLE_INTERVAL = 3.0
    #: 补点之间的缓冲等待
    SETTLE_PAUSE = 2.0
    #: 结算后最多补点几次（御魂掉落界面 -> 挑战界面）
    EXTRA_SETTLE_CLICKS = 4
    #: 每补点一次后等待挑战界面的超时
    BACK_TIMEOUT = 6.0
    #: 整轮兜底超时 = 两个阶段预算 + 这个余量（正常情况由阶段预算先触发）
    ROUND_TIMEOUT_SLACK = 30.0

    #: 战斗结束画面：与碎片挑战共用同一张魂碗模板
    END_STATES: Tuple = (SHARD_BATTLE_END,)

    #: 挑战按钮始终没出现时的报错文案（与旧实现保持一致）
    MISSING_CHALLENGE_MESSAGE = (
        "未匹配到挑战按钮，请确认手机停在御魂挑战界面（镜像窗口可见该按钮）"
    )

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        times: int = 2,
        **kwargs,
    ) -> None:
        """kwargs 透传给 Flow（bus / timer / adaptive）。"""
        super().__init__(controller=controller, machine=machine, **kwargs)
        self.times = times

    # ------------------------------------------------------------------ 主流程
    def run(self) -> None:
        self.log.info("开始刷御魂，共 %s 次", self.times)
        engine = self.create_engine()
        BattleCycle(
            engine,
            challenge=SOUL_CHALLENGE,
            end_states=self.END_STATES,
            battle_interval=self.BATTLE_INTERVAL,
            extra_settle_clicks=self.EXTRA_SETTLE_CLICKS,
            settle_pause=0.0,
            retry_pause=self.SETTLE_PAUSE,
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
