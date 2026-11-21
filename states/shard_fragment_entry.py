"""式神碎片入口面板（「章节入口」模式第二步）。"""
from states.base import State, StateKind

SHARD_FRAGMENT_ENTRY = State(
    key="SHARD_FRAGMENT_ENTRY",
    label="碎片入口面板",
    templates=("碎片入口面板.png",),
    kind=StateKind.MARKER,
    description="点完章节头像后弹出的「式神碎片」面板（带「挑战」页签）；"
                "命中即点击，进入碎片列表",
    # 阈值 0.92：模板已按当前窗口比例从实时截屏重裁（111x41），三屏实测
    #   副本界面（真正要点的）1.000 / 挑战界面 0.895 / 章节界面 0.774。
    # 挑战界面上这条入口栏仍会显示，正常靠 watch 顺序让挑战按钮（0.999）先赢；
    # 抬到 0.92 是第二道保险：界面切换动画里挑战按钮短暂看不见时也不会误点入口。
    threshold=0.92,
)
