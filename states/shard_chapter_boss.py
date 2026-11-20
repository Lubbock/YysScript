"""探索章节界面上的碎片 Boss 头像（式神碎片「章节入口」模式第一步）。"""
from states.base import State, StateKind

SHARD_CHAPTER_BOSS = State(
    key="SHARD_CHAPTER_BOSS",
    label="碎片章节头像",
    templates=("碎片章节头像.png",),
    kind=StateKind.MARKER,
    description="章节界面（如「第十八章」）上碎片 Boss 的头像方格；命中即点击，"
                "打开「式神碎片」入口面板。模板只裁了头像方格本身，"
                "所以匹配框中心正是要点的位置",
)
