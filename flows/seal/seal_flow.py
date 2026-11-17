"""自动妖气封印（组队刷）。

对应旧 scripts/dogger.py 的 Dogger 类：
进妖气封印 -> 选目标式神（默认小松丸）-> 进组队 -> 点准备 -> 战斗 ->
结算退出 -> 回到组队界面继续下一轮。
"""
from __future__ import annotations

from typing import Optional

from actions.controller import GameController
from config import coordinates as coords
from flows.base import Flow
from states.battle_prepare import BATTLE_PREPARE
from states.battle_settlement_alt import BATTLE_SETTLEMENT_ALT
from states.battle_start import BATTLE_START
from states.base import State
from states.monster_xiaosongmaru import MONSTER_XIAOSONGMARU
from states.team import TEAM


class SealFlow(Flow):
    """自动妖气封印。"""

    name = "seal"
    description = "自动妖气封印（组队刷）"

    #: 等「准备」界面出现的超时
    PREPARE_TIMEOUT = 120.0
    #: 等战斗结算的超时
    BATTLE_TIMEOUT = 300.0
    #: 等回到组队界面的超时
    TEAM_TIMEOUT = 120.0

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        times: int = 30,
        target: State = MONSTER_XIAOSONGMARU,
    ) -> None:
        super().__init__(controller=controller, machine=machine)
        self.times = times
        self.target = target

    def run(self) -> None:
        for index in range(self.times):
            self.log.info("---------- 第 %s/%s 次妖气封印 ----------", index + 1, self.times)
            if not self._enter_team():
                continue
            self._prepare()
            self._finish_battle()
            self._back_to_team()

    # ------------------------------------------------------------------ 步骤
    def _enter_team(self) -> bool:
        """打开妖气封印列表，选目标式神并加入队伍。"""
        self.click(coords.SEAL_ENTRY)
        target = self.locate(self.target)
        if target is None:
            # 旧代码这里会把 None 直接传给 click 导致崩溃
            self.log.warning("未找到目标 %s，跳过本轮", self.target)
            return False
        self.click(target)
        self.click(coords.SEAL_TEAMMATE)
        return True

    def _prepare(self) -> None:
        """等到「准备」界面并点准备（中途可能要先点「开始战斗」）。"""
        self.wait(
            BATTLE_PREPARE,
            timeout=self.PREPARE_TIMEOUT,
            interval=2,
            on_wait=self._kick_start_battle,
        )
        self.click(coords.SEAL_PREPARE, duration=1.0)
        if self.is_active(BATTLE_PREPARE):
            self.click(coords.SEAL_PREPARE, duration=2.0)

    def _kick_start_battle(self, rounds: int) -> None:
        """等准备界面时，如果出现「开始战斗」就先点掉。"""
        if self.is_active(BATTLE_START):
            self.click(coords.SEAL_START_BATTLE)

    def _finish_battle(self) -> None:
        """等战斗结算出现，然后退出结算界面。"""
        self.expect(BATTLE_SETTLEMENT_ALT, timeout=self.BATTLE_TIMEOUT)
        self.click(coords.SEAL_EXIT)

    def _back_to_team(self) -> None:
        """回到组队界面；回不去就一直点入口重试。"""
        self.wait(
            TEAM,
            timeout=self.TEAM_TIMEOUT,
            interval=2,
            on_wait=lambda rounds: self.click(coords.SEAL_ENTRY),
        )
        self.sleep(2)
