"""结界突破「进攻」按钮。"""
from states.base import State, StateKind

MARKER_ATTACK = State(
    key="MARKER_ATTACK",
    label="突破进攻按钮",
    templates=("突破进攻.png",),
    kind=StateKind.MARKER,
    description="选中某个结界后出现的进攻按钮",
)
