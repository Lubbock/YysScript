"""自动探索主流程。

对应旧 scripts/adventure.py 的 Adventure 类。流程：

    进入副本 -> 选难度 -> 翻页扫怪 -> 打怪（顺带换狗粮）
             -> 战斗结算 -> 领 Boss 奖励 -> 退出 -> 重新进入

与旧实现的差异：
1. 旧代码 `for retry in range(34)` 末尾有一个无条件 break，导致扫怪只跑一轮、
   翻页逻辑形同虚设；这里恢复成「翻满 max_page 页才结束本次探索」。
2. 怪物坐标由 vision 的颜色检测给出（屏幕坐标），直接交给 controller 点击，
   不再假设屏幕分辨率。
3. 体力耗尽抛 StaminaExhaustedError，由 main.py 统一转成退出码 300。
"""
from __future__ import annotations

from typing import Optional

from actions.controller import GameController
from config import coordinates as coords
from config import settings
from core.errors import StaminaExhaustedError
from flows.base import Flow
from flows.explore.dog_food import DogFoodManager
from flows.explore.map_navigator import MapNavigator
from states.explore_battle_end import EXPLORE_BATTLE_END
from states.explore_entry import EXPLORE_ENTRY
from states.explore_exit_confirm import EXPLORE_EXIT_CONFIRM
from states.explore_map import EXPLORE_MAP
from states.home import HOME
from states.marker_boss_reward import MARKER_BOSS_REWARD
from states.stamina_shortage import STAMINA_SHORTAGE
from vision.types import Box


class ExploreFlow(Flow):
    """自动探索。"""

    name = "explore"
    description = "自动探索：扫怪 / 换狗粮 / 领 Boss 奖励 / 退出重进"

    #: 一场战斗最长等待时间
    BATTLE_TIMEOUT = 300.0
    #: 点完「开始战斗」后的固定等待（战斗动画 + 加载）
    BATTLE_PRE_WAIT = 30.0
    #: 战斗结算后的固定等待
    BATTLE_POST_WAIT = 7.0
    #: 单轮探索的最大尝试次数（找怪 + 打怪）
    MAX_ATTEMPTS = 34

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        times: int = 1,
        exp_only: bool = False,
    ) -> None:
        super().__init__(controller=controller, machine=machine)
        self.times = times
        self.exp_only = exp_only
        self.max_page = settings.EXPLORE_MAX_PAGE
        self.lost_limit = settings.EXPLORE_LOST_LIMIT
        self.navigator = MapNavigator(self)
        self.dog_food = DogFoodManager(self)

    # ------------------------------------------------------------------ 主流程
    def run(self) -> None:
        self.enter_dungeon()
        for index in range(self.times):
            self.log.info("---------- 第 %s/%s 次探索 ----------", index + 1, self.times)
            self._start_round()
            self._sweep_map()
            self._leave_round()

    def enter_dungeon(self) -> None:
        """点右侧副本入口，进入探索。"""
        self.click(coords.EXPLORE_ENTRY)
        self.expect(EXPLORE_ENTRY, timeout=60)
        self.log.info("已进入探索副本选择界面")

    def select_chapter(self) -> None:
        """在章节列表里选第九章（旧脚本的 find_map，默认不启用）。"""
        self.navigator.select_chapter()

    # ------------------------------------------------------------------ 单轮
    def _start_round(self) -> None:
        self.click(coords.EXPLORE_DIFFICULTY)
        self.expect(EXPLORE_MAP, timeout=60)
        self.navigator.next_page()

    def _sweep_map(self) -> None:
        """在当前副本里翻页找怪并逐个击破。"""
        page = 0
        lost = 0
        for _ in range(self.MAX_ATTEMPTS):
            monsters = self.controller.find_monsters(exp_only=self.exp_only)
            self.log.info("地图第 %s 页，定位到 %s 个怪物", page, len(monsters))
            if monsters:
                lost = 0
                self._fight(monsters[0])
            else:
                lost += 1
                self.log.info("第 %s 次未找到怪物", lost)
                if lost >= self.lost_limit:
                    page += 1
                    lost = 0
                    self.log.info("进入下一页寻找怪物")
                    self.navigator.next_page()
            if page > self.max_page:
                self.log.info("已翻满 %s 页，结束本次探索", self.max_page)
                break

    def _fight(self, monster: Box) -> None:
        """打一只怪：点击 -> 处理狗粮 -> 开战 -> 等结算 -> 退回地图。"""
        self.log.info("点击怪物 %s", monster.center)
        self.click(monster)

        if self.is_active(STAMINA_SHORTAGE):
            raise StaminaExhaustedError("体力已耗尽，探索流程停止")

        self.sleep(2)
        if self.is_active(EXPLORE_MAP):
            # 点到的是地图空白处，往右挪一步重新找
            self.click(coords.EXPLORE_MOVE_RIGHT)
            return

        self.sleep(1)
        if self.dog_food.needs_change():
            self.log.info("========== 开始替换狗粮 ==========")
            self.dog_food.replace_one()

        self.click(coords.EXPLORE_START_BATTLE)
        self.log.info("开始战斗 ...")
        self.sleep(self.BATTLE_PRE_WAIT)

        detection = self.wait_any(
            [EXPLORE_BATTLE_END, EXPLORE_ENTRY, HOME],
            timeout=self.BATTLE_TIMEOUT,
            interval=5,
            on_wait=lambda rounds: self.log.info("打怪中 ...（第 %s 次轮询）", rounds),
        )
        if detection is None:
            self.log.warning("战斗结束状态未识别到，按超时继续")
        else:
            self.log.info("战斗结束，当前界面 %s", detection.state)

        self.sleep(self.BATTLE_POST_WAIT)
        self._back_to_map()

    def _back_to_map(self) -> None:
        """从结算界面退回地图；顺便领 Boss 奖励，必要时重新进副本。"""
        self.click(coords.EXPLORE_EXIT)
        self.wait(
            EXPLORE_MAP,
            timeout=60,
            on_wait=lambda rounds: self.click(coords.EXPLORE_EXIT),
        )
        self.log.info("退出单场战斗结算页")
        self.sleep(4)

        if self.is_active(EXPLORE_ENTRY):
            self._collect_boss_rewards()
        if self.is_active(HOME):
            self.enter_dungeon()

    def _collect_boss_rewards(self) -> None:
        """领取章节 Boss 掉落的奖励（旧脚本点两次以关掉弹窗）。"""
        rewards = self.locate_all(MARKER_BOSS_REWARD)
        if not rewards:
            self.log.info("没有可领取的 Boss 奖励")
            return
        for reward in rewards:
            self.click(reward)
            self.sleep(1)
            self.click(reward)
        self.sleep(3)
        self.log.info("Boss 奖励领取完成")
        if self.is_active(HOME):
            self.enter_dungeon()

    def _leave_round(self) -> None:
        """退出本次探索副本，回到入口界面。"""
        if not self.is_active(EXPLORE_EXIT_CONFIRM):
            self.click(coords.EXPLORE_BACK)
        if not self.wait(EXPLORE_EXIT_CONFIRM, timeout=30):
            self.log.warning("未出现退出确认弹窗，仍尝试点击确定")
        self.click(coords.EXPLORE_EXIT_OK)
        self.sleep(4)

        if self.is_active(EXPLORE_ENTRY):
            return
        if self.is_active(HOME):
            self.enter_dungeon()
