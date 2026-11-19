"""式神碎片副本的挑战按钮。"""
from states.base import State, StateKind

SHARD_CHALLENGE = State(
    key="SHARD_CHALLENGE",
    label="碎片挑战",
    templates=("挑战_碎片.png",),
    kind=StateKind.MARKER,
    description="式神碎片副本界面上的菱形「挑战」按钮（带券次数），命中即点击开战",
)
