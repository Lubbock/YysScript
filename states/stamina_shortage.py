"""体力不足弹窗。"""
from states.base import State

STAMINA_SHORTAGE = State(
    key="STAMINA_SHORTAGE",
    templates=("购买体力.png",),
    label="体力不足",
    description="体力耗尽时弹出的购买体力窗，出现即应停止流程",
)
