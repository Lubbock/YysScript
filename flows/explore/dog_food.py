"""狗粮（满级式神）替换。

对应旧 scripts/adventure.py 里 activate() 中间那一大段：
用「满」标记判断队伍里有没有已经满级的式神，有就打开式神列表，
把一只未满级的狗粮拖到该槽位上。

坐标换算说明：
- 识别结果是屏幕坐标，先用 controller.to_logical() 转回基准客户区坐标，
  再和 coordinates.py 里的分区阈值比较，这样换分辨率也不会错位。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List

from config import coordinates as coords
from config.coordinates import Point
from states.marker_dog_food import MARKER_DOG_FOOD
from states.marker_full_level import MARKER_FULL_LEVEL

if TYPE_CHECKING:  # 避免循环导入
    from flows.explore.explore_flow import ExploreFlow


class DogFoodManager:
    """判断并执行狗粮替换。"""

    #: 打开式神列表的等待超时
    PANEL_TIMEOUT = 30.0

    def __init__(self, flow: "ExploreFlow") -> None:
        self._flow = flow

    # ------------------------------------------------------------------ 判断
    def full_level_marks(self) -> List[Point]:
        """当前画面上所有「满」标记，返回基准客户区逻辑坐标。"""
        marks = self._flow.locate_all(MARKER_FULL_LEVEL)
        return [self._flow.controller.to_logical(match.center) for match in marks]

    def needs_change(self) -> bool:
        """队伍里是否出现了需要替换的满级式神。"""
        marks = self.full_level_marks()
        if len(marks) <= 1:
            return False
        return any(mark.x > coords.DOG_CHANGE_X_LIMIT for mark in marks)

    # ------------------------------------------------------------------ 执行
    def replace_one(self) -> bool:
        """替换一只满级式神。成功返回 True。"""
        flow = self._flow
        flow.double_click(coords.DOG_SLOT)
        flow.wait(
            MARKER_DOG_FOOD,
            timeout=self.PANEL_TIMEOUT,
            on_wait=lambda rounds: flow.double_click(coords.DOG_SLOT),
        )
        flow.log.info("式神列表已打开，查找需要替换的满级式神")

        for mark in self.full_level_marks():
            if mark.y >= coords.DOG_FULL_Y_LIMIT:
                continue  # 只处理上半屏（队伍区域）的标记
            # 旧代码把 [BLOCK_LEFT, BLOCK_RIGHT] 与 [< BLOCK_LEFT] 两个分区
            # 写成两个分支但动作完全一样，这里合并成一个条件
            if mark.x >= coords.DOG_BLOCK_RIGHT:
                continue
            self._next_dog_page()
            target = Point(mark.x, mark.y + coords.DOG_DRAG_EXTRA_Y)
            flow.drag(coords.DOG_DRAG_FROM, target, duration=1.0)
            flow.log.info("已把狗粮拖到槽位 %s", target)
            return True

        flow.log.info("没有找到需要替换的满级式神")
        return False

    def _next_dog_page(self) -> None:
        """式神列表向右翻一页。"""
        self._flow.drag(
            coords.DOG_PAGE_FROM,
            coords.DOG_PAGE_TO,
            duration=coords.DOG_PAGE_DURATION,
        )
        self._flow.sleep(2)
