"""活动事件 Aj8fer 阶段 1。"""
from states.base import State

EVENT_AJ8FER_1 = State(
    key="EVENT_AJ8FER_1",
    label="事件Aj8fer-阶段1",
    templates=("Aj8fer-1.png",),
    description="带耗时预测的事件阶段：等待时间由 storage 里的历史均值推算",
)
