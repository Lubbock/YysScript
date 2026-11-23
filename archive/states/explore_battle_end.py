"""探索单场战斗结束。"""
from states.base import State

EXPLORE_BATTLE_END = State(
    key="EXPLORE_BATTLE_END",
    label="探索战斗结束",
    templates=("end_adventure.png",),
    description="探索中一场遭遇战打完的结算画面",
)
