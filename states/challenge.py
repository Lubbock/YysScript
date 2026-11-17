"""挑战确认界面。"""
from states.base import State

CHALLENGE = State(
    key="CHALLENGE",
    label="挑战界面",
    templates=("挑战.png",),
    description="觉醒 / 御魂副本里点「挑战」前的确认界面",
)
