"""探索地图上的愤怒的石距。"""
from states.base import State, StateKind

MARKER_ANGRY_SHIYU = State(
    key="MARKER_ANGRY_SHIYU",
    label="愤怒的石距",
    templates=("愤怒的石距.png",),
    kind=StateKind.MARKER,
    description="探索中随机出现的高奖励 Boss（预留，旧脚本中相关逻辑被注释）",
)
