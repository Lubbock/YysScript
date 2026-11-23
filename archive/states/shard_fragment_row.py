"""式神碎片：选择式神那一行（头像 + 等级）。"""
from states.base import State, StateKind

SHARD_FRAGMENT_ROW = State(
    key="SHARD_FRAGMENT_ROW",
    label="碎片列表行",
    templates=("碎片列表行.png",),
    kind=StateKind.MARKER,
    description="「式神碎片」入口点进去之后的选择式神界面里，「头像 + 等级」那一行；"
                "命中即点击选中该式神，之后才出现可点的菱形挑战按钮",
    # 阈值 0.9 是「选没选中式神」的判据。2026-11-21 真机在同一屏点击前后各量一次：
    #   未选中 0.978  ->  点一下之后 0.799（该行高亮变化，分数掉 0.18）
    # 所以 >=0.9 表示「还需要选式神」，<0.9 表示「已选好，该点挑战按钮」。
    # 别的界面都远低于此：章节界面 0.541 / 副本界面 0.511，不会误命中。
    threshold=0.9,
)
