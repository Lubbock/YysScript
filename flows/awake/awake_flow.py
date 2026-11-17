"""自动觉醒材料。

对应旧 scripts/awake.py 的 Awake 类：
底部菜单进觉醒材料 -> 选副本（火御魂 / 风麒麟 / 水麒麟 / 雷麒麟）
-> 循环「等挑战界面 → 挑战 → 等结算 → 再点挑战」。
"""
from __future__ import annotations

from typing import Optional

from actions.controller import GameController
from config import coordinates as coords
from flows.base import Flow
from states.battle_settlement_alt import BATTLE_SETTLEMENT_ALT
from states.challenge import CHALLENGE


class AwakeFlow(Flow):
    """自动刷觉醒材料。"""

    name = "awake"
    description = "自动觉醒材料"

    #: 一场战斗的预估时长（旧脚本写死 20 秒）
    BATTLE_DURATION = 20.0
    #: 等战斗结算的最长时间
    BATTLE_TIMEOUT = 300.0
    #: 等挑战界面出现的最长时间
    CHALLENGE_TIMEOUT = 60.0

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        times: int = 20,
        dungeon: int = 4,
    ) -> None:
        """
        times   : 刷多少次
        dungeon : 副本序号，1 火御魂 | 2 风麒麟 | 3 水麒麟 | 4 雷麒麟
        """
        super().__init__(controller=controller, machine=machine)
        self.times = times
        self.dungeon = dungeon

    def run(self) -> None:
        self.log.info("开始刷觉醒材料：副本 %s，共 %s 次", self.dungeon, self.times)
        self.click(coords.bottom_menu(coords.MENU_AWAKE_MATERIAL))
        self.sleep(1.5)
        self.click(coords.awake_dungeon(self.dungeon))
        self.sleep(1.5)

        for index in range(self.times):
            self.wait(
                CHALLENGE,
                timeout=self.CHALLENGE_TIMEOUT,
                on_wait=lambda rounds: self.click(coords.AWAKE_CHALLENGE),
            )
            self.log.info("第 %s/%s 次觉醒", index + 1, self.times)
            self.click(coords.AWAKE_CHALLENGE)
            self.sleep(self.BATTLE_DURATION)
            self.expect(BATTLE_SETTLEMENT_ALT, timeout=self.BATTLE_TIMEOUT)
            # 结算界面再点一次挑战位置，回到下一轮
            self.click(coords.AWAKE_CHALLENGE)
            self.sleep(2)
