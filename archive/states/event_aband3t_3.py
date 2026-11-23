"""活动事件 Aband3t 阶段 3。"""
from states.base import State

EVENT_ABAND3T_3 = State(
    key="EVENT_ABAND3T_3",
    label="事件Aband3t-阶段3",
    templates=("Aband3t-3.png",),
    description="需要长时间等待（约 120 秒）的事件阶段",
)
