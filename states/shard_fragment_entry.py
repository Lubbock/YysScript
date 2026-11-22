"""式神碎片：副本界面上的「式神碎片」入口条。"""
from states.base import State, StateKind

SHARD_FRAGMENT_ENTRY = State(
    key="SHARD_FRAGMENT_ENTRY",
    label="碎片入口面板",
    templates=("碎片入口面板.png",),
    kind=StateKind.MARKER,
    description="点完章节 Boss 头像后，副本界面上的「式神碎片」入口条（111x41）；"
                "命中即点击，进入选择式神界面",
    # 阈值 0.95：2026-11-21 用探针法按当前窗口比例从实时截屏重裁后实测
    #   副本界面（真正要点的）1.000
    #   选择式神界面 0.928 / 挑战界面 0.927 / 章节界面 0.806
    # 正常靠 watch 顺序让更该点的模板先赢（结算 > 列表行 > 挑战按钮 > 本条 > 头像），
    # 抬到 0.95 是第二道保险：界面切换动画里挑战按钮短暂识别不到时，
    # 也不会从挑战界面误点回副本界面。真命中 1.000，余量 0.05。
    threshold=0.95,
)
