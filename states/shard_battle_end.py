"""式神碎片战斗结束画面。"""
from states.base import State

SHARD_BATTLE_END = State(
    key="SHARD_BATTLE_END",
    label="碎片战斗结束",
    templates=("碎片打完.png",),
    description="式神碎片挑战打完后的结算画面（魂碗），命中即点击退出",
)
