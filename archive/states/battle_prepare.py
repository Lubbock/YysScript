"""战斗准备界面（样式一）。"""
from states.base import State

BATTLE_PREPARE = State(
    key="BATTLE_PREPARE",
    label="战斗准备",
    templates=("准备.png",),
    description="进入战斗前的「准备」按钮界面",
)
