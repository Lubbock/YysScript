"""式神碎片列表行（「章节入口」模式第三步）。"""
from states.base import State, StateKind

SHARD_FRAGMENT_ROW = State(
    key="SHARD_FRAGMENT_ROW",
    label="碎片列表行",
    templates=("碎片列表行.png",),
    kind=StateKind.MARKER,
    description="碎片列表里「头像 + 等级」的一行；命中即点击，进入挑战界面，"
                "之后由既有的 SHARD_CHALLENGE（菱形挑战按钮）接手开战",
)
