"""探索地图上的宝箱。"""
from states.base import State, StateKind

MARKER_TREASURE_BOX = State(
    key="MARKER_TREASURE_BOX",
    label="宝箱",
    templates=("宝箱.png",),
    kind=StateKind.MARKER,
    description="探索章节中可开启的宝箱（预留，旧脚本中相关逻辑被注释）",
)
