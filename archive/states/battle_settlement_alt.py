"""战斗结算界面（样式二）。"""
from states.base import State

BATTLE_SETTLEMENT_ALT = State(
    key="BATTLE_SETTLEMENT_ALT",
    label="战斗结算(样式2)",
    templates=("妖气封印打完_2.png",),
    description="另一种样式的战斗结算界面，觉醒 / 妖气封印流程用它判断战斗结束",
)
