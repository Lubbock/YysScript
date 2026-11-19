"""自动式神碎片（碎片挑战循环）。

流程结构与御魂（SoulFlow）的循环一致，但全程用模板匹配驱动：

    匹配菱形「挑战」按钮 -> 点击开战
    -> 等战斗结束画面出现 -> 点击结算退出
    -> 回到碎片界面再匹配「挑战」 -> ...

- 开始点击匹配 `states/shard_challenge.py`（菱形挑战按钮模板）；
- 结束判定只匹配 `states/shard_battle_end.py`（碎片结算魂碗画面）——通用结算模板
  在战斗画面里容易误命中，不纳入候选；
- macOS 下截屏 / 点击通道默认是「iPhone Mirroring」镜像窗口（见 actions/window.py），
  即 iOS 手机连到 Mac 的屏幕镜像，窗口内的点击会直接透传到手机。
"""
from __future__ import annotations

from typing import Optional, Tuple

from actions.controller import GameController
from core.errors import FlowAbortedError
from flows.base import Flow
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
    #: 战斗中的轮询间隔
    BATTLE_INTERVAL = 3.0
    #: 点完结算后的缓冲等待
    SETTLE_PAUSE = 3.0

    #: 表示战斗结束的界面。只用碎片自己的结算模板：通用结算模板（妖气封印 /
    #: 探索等）在碎片战斗画面里会误命中，导致战斗中乱点。
    END_STATES: Tuple = (SHARD_BATTLE_END,)

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        times: int = 10,
    ) -> None:
        super().__init__(controller=controller, machine=machine)
        self.times = times

    # ------------------------------------------------------------------ 主流程
    def run(self) -> None:
        self.log.info("开始刷式神碎片，共 %s 次", self.times)
        for index in range(self.times):
            self.log.info("---------- 第 %s/%s 次碎片挑战 ----------", index + 1, self.times)
            self._click_challenge()
            self._wait_battle_end()

    # ------------------------------------------------------------------ 单轮
    def _click_challenge(self) -> None:
        """等菱形挑战按钮出现并点击；等待期间顺手点掉残留的结算画面。"""
        if not self.wait(
            SHARD_CHALLENGE,
            timeout=self.CHALLENGE_TIMEOUT,
            on_wait=lambda rounds: self._dismiss_settlement(),
        ):
            raise FlowAbortedError(
                "未匹配到挑战按钮，请确认手机停在式神碎片界面（镜像窗口可见该按钮）"
            )
        self.click_state(SHARD_CHALLENGE)
        self.log.info("已点击挑战，进入战斗")

    def _dismiss_settlement(self) -> None:
        """等待挑战按钮时若看到结算画面，点一下退出。"""
        detection = self.detect(self.END_STATES)
        if detection is not None and detection.match is not None:
            self.log.info("检测到结算画面 %s，先点击退出", detection.state)
            self.click(detection.match)

    def _wait_battle_end(self) -> None:
        """等结算画面出现并点击退出，回到碎片界面。"""
        detection = self.wait_any(
            self.END_STATES,
            timeout=self.BATTLE_TIMEOUT,
            interval=self.BATTLE_INTERVAL,
            on_wait=lambda rounds: self.log.info("战斗中 ...（第 %s 次轮询）", rounds),
        )
        if detection is None:
            self.log.warning("未识别到战斗结算，按超时继续下一轮")
            return
        self.log.info("战斗结束，结算画面 %s", detection.state)
        self.click(detection.match)
        self.sleep(self.SETTLE_PAUSE)
