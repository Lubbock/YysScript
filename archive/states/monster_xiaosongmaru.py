"""妖气封印目标：小松丸。"""
from states.base import State, StateKind

MONSTER_XIAOSONGMARU = State(
    key="MONSTER_XIAOSONGMARU",
    label="小松丸",
    templates=("小松丸.png",),
    kind=StateKind.MARKER,
    description="妖气封印列表里要选的目标式神",
)
