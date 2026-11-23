"""结界突破失败。"""
from states.base import State

BREAKTHROUGH_FAILED = State(
    key="BREAKTHROUGH_FAILED",
    label="结界突破失败",
    templates=("突破失败.png",),
    description="突破战斗失败的结果界面，出现后应换下一个结界",
)
