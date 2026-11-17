"""自动结界突破。

对应旧 scripts/fight.py 的 Fight 类：
进结界突破 -> 依次点九宫格 9 个结界 -> 有「进攻」按钮就打 ->
打完或打失败后回到九宫格 -> 9 个都处理完就刷新列表。

修掉的旧 bug：
1. 九宫格索引换算用 math.ceil(float(now)/3) + now%3，第 3/6/9 格会算错行；
   现在统一用 coords.breakthrough_cell(index)。
2. 刷新时的 loop_action 写成 `{click(a), click(b)}`（集合字面量），
   两个点击的执行顺序不确定；现在按顺序调用。
"""
from __future__ import annotations

from typing import Optional

from actions.controller import GameController
from config import coordinates as coords
from flows.base import Flow
from states.battle_prepare_alt import BATTLE_PREPARE_ALT
from states.battle_settlement_alt import BATTLE_SETTLEMENT_ALT
from states.breakthrough_entry import BREAKTHROUGH_ENTRY
from states.breakthrough_failed import BREAKTHROUGH_FAILED
from states.marker_attack import MARKER_ATTACK
from states.marker_refresh import MARKER_REFRESH

#: 九宫格共 9 个结界
CELL_COUNT = 9


class BreakthroughFlow(Flow):
    """自动结界突破。"""

    name = "breakthrough"
    description = "自动结界突破（九宫格循环）"

    #: 点完一个结界后等「进攻」按钮出现的时间
    ATTACK_TIMEOUT = 20.0
    #: 战斗最长时间
    BATTLE_TIMEOUT = 300.0
    #: 等刷新按钮消失（即刷新完成）的时间
    REFRESH_TIMEOUT = 120.0

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        rounds: Optional[int] = None,
    ) -> None:
        """rounds=None 表示无限循环（与旧脚本一致），否则跑指定轮数。"""
        super().__init__(controller=controller, machine=machine)
        self.rounds = rounds

    def run(self) -> None:
        self.click(coords.BREAKTHROUGH_ENTRY)
        self.expect(BREAKTHROUGH_ENTRY, timeout=60)

        round_index = 0
        while self.rounds is None or round_index < self.rounds:
            round_index += 1
            self.log.info("===== 第 %s 轮结界突破 =====", round_index)
            for cell in range(1, CELL_COUNT + 1):
                self._attack_cell(cell)
            self._refresh_list()

    # ------------------------------------------------------------------ 单格
    def _attack_cell(self, cell: int) -> None:
        """尝试突破九宫格里的第 cell 个结界。"""
        position = coords.breakthrough_cell(cell)
        self.click(position)
        self.sleep(3)

        attack = self.locate(MARKER_ATTACK)
        if attack is None:
            self.log.info("第 %s 格没有可进攻的结界，跳过", cell)
            return

        self.log.info("进攻第 %s 格结界", cell)
        self.click(attack)
        self.expect(BATTLE_PREPARE_ALT, timeout=self.ATTACK_TIMEOUT)

        self.wait_gone(
            BATTLE_PREPARE_ALT,
            timeout=self.BATTLE_TIMEOUT,
            on_wait=lambda rounds: self.click(coords.BREAKTHROUGH_CONFIRM),
        )
        self.sleep(20)

        result = self.wait_any(
            [BREAKTHROUGH_FAILED, BATTLE_SETTLEMENT_ALT],
            timeout=self.BATTLE_TIMEOUT,
            interval=2,
        )
        if result is None:
            self.log.warning("第 %s 格战斗结果未识别到", cell)
        else:
            self.log.info("第 %s 格战斗结束：%s", cell, result.state)
            # 战斗结束后点一下第一格，关掉结算 / 失败弹窗
            self.click(coords.breakthrough_cell(1))
            self.sleep(4)
        self.sleep(2)

    # ------------------------------------------------------------------ 刷新
    def _refresh_list(self) -> None:
        """9 格处理完后刷新结界列表。"""
        self.wait_gone(
            MARKER_REFRESH,
            timeout=self.REFRESH_TIMEOUT,
            on_wait=self._click_refresh,
        )
        self.sleep(3)

    def _click_refresh(self, rounds: int) -> None:
        """点刷新按钮并确认（顺序执行，修掉旧代码的集合字面量 bug）。"""
        self.log.info("刷新结界列表（第 %s 次尝试）", rounds)
        self.click(coords.BREAKTHROUGH_REFRESH)
        self.click(coords.BREAKTHROUGH_REFRESH_CONFIRM)
