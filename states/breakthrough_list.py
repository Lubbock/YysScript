"""结界突破列表（九宫格）。"""
from states.base import State

BREAKTHROUGH_LIST = State(
    key="BREAKTHROUGH_LIST",
    label="结界突破列表",
    templates=("突破.png",),
    description="展示 9 个可突破结界的九宫格界面",
)
