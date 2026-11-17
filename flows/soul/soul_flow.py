"""自动御魂。

对应旧 scripts/soul.py 的 Soul 类：
底部菜单进御魂 -> 选层数 -> 循环「挑战 → 等战斗结束 → 退出」。
"""
from __future__ import annotations

from typing import Optional

from actions.controller import GameController
from config import coordinates as coords
from flows.base import Flow


class SoulFlow(Flow):
    """自动刷御魂。"""

    name = "soul"
    description = "自动御魂"

    #: 一场御魂战斗的预估时长（旧脚本写死 80 秒）
    BATTLE_DURATION = 80.0
    #: 结算后退回列表的等待
    EXIT_PAUSE = 5.0

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        times: int = 2,
    ) -> None:
        super().__init__(controller=controller, machine=machine)
        self.times = times

    def run(self) -> None:
        self.log.info("开始刷御魂，共 %s 次", self.times)
        self.click(coords.bottom_menu(coords.MENU_SOUL))
        self.sleep(1.5)
        self.click(coords.SOUL_ENTRY)
        self.sleep(1.5)

        for index in range(self.times):
            self.log.info("第 %s/%s 次御魂", index + 1, self.times)
            self.click(coords.SOUL_CHALLENGE)
            self.sleep(self.BATTLE_DURATION)
            self.click(coords.SOUL_EXIT)
            self.sleep(self.EXIT_PAUSE)
