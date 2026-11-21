"""式神碎片列表行（「章节入口」模式第三步）。"""
from states.base import State, StateKind

SHARD_FRAGMENT_ROW = State(
    key="SHARD_FRAGMENT_ROW",
    label="碎片列表行",
    templates=("碎片列表行.png",),
    kind=StateKind.MARKER,
    description="碎片列表里「头像 + 等级」的一行。第十八章实测**没有这一屏**："
                "点入口条直接到挑战界面。保留登记是为了别的章节可能出现列表；"
                "模板尚未按当前比例重截，匹配不上时不触发任何东西（宁缺毋滥）",
)
