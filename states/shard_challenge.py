"""式神碎片副本的挑战按钮。"""
from states.base import State, StateKind

SHARD_CHALLENGE = State(
    key="SHARD_CHALLENGE",
    label="碎片挑战",
    templates=("挑战_碎片.png",),
    kind=StateKind.MARKER,
    description="式神碎片副本界面上的菱形「挑战」按钮（带券次数），命中即点击开战",
    # 阈值 0.85 是量出来的：挑战界面实测 0.995~0.999，战斗画面误命中 0.713~0.721。
    # 用默认 0.7 会让战斗画面也命中挑战按钮，等于在战斗里留一个「随时可能点出去」的
    # 隐患（BattleCycle 的 phase 判断能挡住，但轮次刚开始时挡不住）。0.85 两边都留了
    # 足够余量。
    threshold=0.85,
)
