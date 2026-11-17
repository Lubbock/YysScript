"""退出探索确认弹窗。"""
from states.base import State

EXPLORE_EXIT_CONFIRM = State(
    key="EXPLORE_EXIT_CONFIRM",
    label="退出探索确认",
    templates=("探索退出.png",),
    description="点左上角返回后弹出的「是否退出探索」确认框",
)
