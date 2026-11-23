"""探索 Boss 奖励。"""
from states.base import State, StateKind

MARKER_BOSS_REWARD = State(
    key="MARKER_BOSS_REWARD",
    label="Boss奖励",
    templates=("boos奖励.png",),
    kind=StateKind.MARKER,
    description="探索章节 Boss 掉落的奖励图标，需要逐个点击领取",
)
