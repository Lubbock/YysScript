"""探索入口界面（可以开始探索）。"""
from states.base import State

EXPLORE_ENTRY = State(
    key="EXPLORE_ENTRY",
    label="探索入口",
    templates=("start_adventure.png",),
    description="章节副本选择界面，点右侧副本即可进入探索",
)
