"""开始战斗按钮界面。"""
from states.base import State

BATTLE_START = State(
    key="BATTLE_START",
    label="开始战斗",
    templates=("开始战斗.png",),
    description="需要再点一次「开始战斗」才真正进入战斗的中间界面",
)
