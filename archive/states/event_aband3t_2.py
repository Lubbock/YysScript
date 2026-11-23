"""活动事件 Aband3t 阶段 2（结束）。"""
from states.base import State

EVENT_ABAND3T_2 = State(
    key="EVENT_ABAND3T_2",
    label="事件Aband3t-阶段2",
    templates=("Aband3t-2.png",),
    description="单次事件战斗结束后的结算按钮，点击后进入下一轮",
)
