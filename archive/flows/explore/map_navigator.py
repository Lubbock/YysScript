"""探索地图导航：选章节、翻页。

对应旧 scripts/adventure.py 里的 find_map() 和 a_base.next_page()。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from config import coordinates as coords
from states.base import State
from states.marker_chapter_nine import MARKER_CHAPTER_NINE
from vision.types import Match

if TYPE_CHECKING:  # 避免循环导入
    from flows.explore.explore_flow import ExploreFlow


class MapNavigator:
    """探索地图的翻页与章节选择。"""

    #: 选章节时向下 / 向上滚动的次数（沿用旧脚本的经验值）
    SCROLL_DOWN_STEPS = (3, 2, 2, 3)
    SCROLL_UP_ROUNDS = 6

    def __init__(self, flow: "ExploreFlow") -> None:
        self._flow = flow

    def next_page(self) -> None:
        """把地图向左拖一屏（下一页）。"""
        self._flow.drag(
            coords.EXPLORE_PAGE_FROM,
            coords.EXPLORE_PAGE_TO,
            duration=coords.EXPLORE_PAGE_DURATION,
        )

    def select_chapter(
        self,
        chapter: State = MARKER_CHAPTER_NINE,
        settle: float = 4.0,
    ) -> Optional[Match]:
        """在章节列表里滚动查找目标章节并点击。

        返回命中的 Match；找不到返回 None（调用方决定是否继续）。
        """
        for steps in self.SCROLL_DOWN_STEPS:
            self._flow.scroll(steps, at=coords.EXPLORE_MAP_SCROLL, pause=1.0)

        found: Optional[Match] = None
        for _ in range(self.SCROLL_UP_ROUNDS):
            self._flow.scroll(-1, at=coords.EXPLORE_MAP_SCROLL, pause=1.0)
            self._flow.scroll(-1, at=coords.EXPLORE_MAP_SCROLL, pause=1.0)
            found = self._flow.locate(chapter)
            if found is not None:
                self._flow.click(found)
                break

        self._flow.sleep(settle)
        if found is None:
            self._flow.log.warning("未能在章节列表中定位到 %s", chapter)
        return found
