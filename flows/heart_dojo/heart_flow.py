"""自动御心道场（觉醒道场）。

对应旧 scripts/heart.py 的 Heart 类：
进道场 -> 选副本 -> 确认 -> 准备 -> 等战斗结束 -> 回到选择界面循环。
"""
from __future__ import annotations

from typing import Optional

from actions.controller import GameController
from config import coordinates as coords
from flows.base import Flow
from states.battle_prepare_alt import BATTLE_PREPARE_ALT
from states.battle_settlement_alt import BATTLE_SETTLEMENT_ALT
from states.heart_dojo import HEART_DOJO


class HeartDojoFlow(Flow):
    """自动刷御心道场。"""

    name = "heart"
    description = "自动御心道场"

    #: 战斗结算的固定等待（旧脚本写死 120 秒）
    SETTLE_WAIT = 120.0
    #: 等战斗结算界面的超时
    BATTLE_TIMEOUT = 300.0
    #: 等准备按钮消失的超时
    PREPARE_TIMEOUT = 120.0

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        times: int = 10,
    ) -> None:
        super().__init__(controller=controller, machine=machine)
        self.times = times

    def run(self) -> None:
        self.click(coords.HEART_ENTRY)
        self.sleep(2)
        self.click(coords.HEART_SELECT)
        self.sleep(1)

        for index in range(self.times):
            self.log.info("---------- 第 %s/%s 次御心道场 ----------", index + 1, self.times)
            self.wait(
                HEART_DOJO,
                timeout=60,
                interval=5,
                on_wait=lambda rounds: self.click(coords.HEART_SELECT),
            )
            self.click(coords.HEART_CONFIRM)
            self.click(coords.HEART_PREPARE)
            self.sleep(2)

            self.log.info("开始打怪")
            self.sleep(5)
            self.wait_gone(
                BATTLE_PREPARE_ALT,
                timeout=self.PREPARE_TIMEOUT,
                interval=2,
                on_wait=lambda rounds: self.click(coords.HEART_START),
            )

            self.sleep(self.SETTLE_WAIT)
            self.expect(BATTLE_SETTLEMENT_ALT, timeout=self.BATTLE_TIMEOUT, interval=5)
            self.click(coords.HEART_SELECT)
