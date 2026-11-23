"""战斗结算界面（样式一）。"""
from states.base import State

BATTLE_SETTLEMENT = State(
    key="BATTLE_SETTLEMENT",
    label="战斗结算",
    templates=("妖气封印打完.png",),
    description="一场战斗结束的结算界面",
)
