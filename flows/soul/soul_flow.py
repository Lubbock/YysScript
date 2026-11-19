"""自动御魂。

旧 scripts/soul.py 是纯定时流程（点坐标 → 固定等 80 秒 → 点坐标），
这里改成与碎片（shard）同构的模板匹配驱动循环：

    匹配菱形「挑战」按钮 -> 点击开战
    -> 等战斗结束画面（与碎片共用魂碗模板）-> 点击
    -> 第一次点击会显示御魂掉落界面，再点一次才回到挑战界面：
       结束后若没检测到挑战按钮，就在结算位置补点几次

macOS 下截屏 / 点击通道默认是「iPhone Mirroring」镜像窗口（见 actions/window.py）。
"""
from __future__ import annotations

from typing import Optional, Tuple

from actions.controller import GameController
from core.errors import FlowAbortedError
from flows.base import Flow
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
    #: 战斗中的轮询间隔
    BATTLE_INTERVAL = 3.0
    #: 结算后补点之间的缓冲等待
    SETTLE_PAUSE = 2.0
    #: 结算后最多补点几次（御魂掉落界面 -> 挑战界面）
    EXTRA_SETTLE_CLICKS = 4
    #: 每补点一次后等待挑战界面的超时
    BACK_TIMEOUT = 6.0

    #: 战斗结束画面：与碎片挑战共用同一张魂碗模板
    END_STATES: Tuple = (SHARD_BATTLE_END,)

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        times: int = 2,
    ) -> None:
        super().__init__(controller=controller, machine=machine)
        self.times = times

    # ------------------------------------------------------------------ 主流程
    def run(self) -> None:
        self.log.info("开始刷御魂，共 %s 次", self.times)
        for index in range(self.times):
            self.log.info("---------- 第 %s/%s 次御魂 ----------", index + 1, self.times)
            self._click_challenge()
            self._wait_battle_end()

    # ------------------------------------------------------------------ 单轮
    def _click_challenge(self) -> None:
        """等菱形挑战按钮出现并点击；等待期间顺手点掉残留的结算画面。"""
        if not self.wait(
            SOUL_CHALLENGE,
            timeout=self.CHALLENGE_TIMEOUT,
            on_wait=lambda rounds: self._dismiss_settlement(),
        ):
            raise FlowAbortedError(
                "未匹配到挑战按钮，请确认手机停在御魂挑战界面（镜像窗口可见该按钮）"
            )
        self.click_state(SOUL_CHALLENGE)
        self.log.info("已点击挑战，进入战斗")

    def _dismiss_settlement(self) -> None:
        """等待挑战按钮时若看到结算画面，点一下退出。"""
        detection = self.detect(self.END_STATES)
        if detection is not None and detection.match is not None:
            self.log.info("检测到结算画面 %s，先点击退出", detection.state)
            self.click(detection.match)

    def _wait_battle_end(self) -> None:
        """等结算画面出现，点击并回到挑战界面。"""
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
        self._back_to_challenge(detection.match)

    def _back_to_challenge(self, settle_match) -> None:
        """点结算：第一次显示御魂掉落界面，没检测到挑战界面就补点几次。"""
        self.click(settle_match)
        for extra in range(self.EXTRA_SETTLE_CLICKS):
            if self.wait(SOUL_CHALLENGE, timeout=self.BACK_TIMEOUT, interval=2.0):
                return
            self.log.info("未检测到挑战界面，补点第 %s 次", extra + 1)
            self.click(settle_match)
            self.sleep(self.SETTLE_PAUSE)
        if self.wait(SOUL_CHALLENGE, timeout=self.BACK_TIMEOUT, interval=2.0):
            return
        self.log.warning("补点后仍未回到挑战界面，下一轮等待挑战按钮时兜底")
