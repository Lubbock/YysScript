"""探索地图界面（等待选怪）。"""
from states.base import State

EXPLORE_MAP = State(
    key="EXPLORE_MAP",
    label="探索地图",
    templates=("wait_adventure.png",),
    description="进入副本后的地图界面，此时可以拖动地图寻找怪物",
)
