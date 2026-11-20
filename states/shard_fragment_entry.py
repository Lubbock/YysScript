"""式神碎片入口面板（「章节入口」模式第二步）。"""
from states.base import State, StateKind

SHARD_FRAGMENT_ENTRY = State(
    key="SHARD_FRAGMENT_ENTRY",
    label="碎片入口面板",
    templates=("碎片入口面板.png",),
    kind=StateKind.MARKER,
    description="点完章节头像后弹出的「式神碎片」面板（带「挑战」页签）；"
                "命中即点击，进入碎片列表",
)
