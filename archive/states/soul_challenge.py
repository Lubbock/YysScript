"""御魂副本的挑战按钮。"""
from states.base import State, StateKind

SOUL_CHALLENGE = State(
    key="SOUL_CHALLENGE",
    label="御魂挑战",
    templates=("挑战_御魂.png",),
    kind=StateKind.MARKER,
    description="御魂副本界面上的菱形「挑战」按钮（带券次数），命中即点击开战",
)
