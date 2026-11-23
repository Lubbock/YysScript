"""式神碎片副本的挑战按钮。"""
from states.base import State, StateKind

SHARD_CHALLENGE = State(
    key="SHARD_CHALLENGE",
    label="碎片挑战",
    templates=("挑战_碎片.png",),
    kind=StateKind.MARKER,
    description="式神碎片副本界面上的菱形「挑战」按钮（带券次数），命中即点击开战",
    # 阈值 0.85 而不是默认 0.7：真命中很高（挑战界面尺度 1.0 实测 0.999~1.00，
    # 缩放尺度下也不会更高），抬阈值几乎不付出代价。上一版这里写的「战斗画面误命中
    # 0.713~0.721」是**旧尺度表试到 0.3** 时量出来的缩小匹配噪声，尺度收紧后不再复现，
    # 别拿那几个数字当依据 —— 真正挡住战斗画面误触发的是 BattleCycle 的阶段判断。
    threshold=0.85,
)
