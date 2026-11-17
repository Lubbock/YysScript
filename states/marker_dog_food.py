"""狗粮（式神）选择列表。"""
from states.base import State, StateKind

MARKER_DOG_FOOD = State(
    key="MARKER_DOG_FOOD",
    label="狗粮列表",
    templates=("狗粮.png",),
    kind=StateKind.MARKER,
    description="双击队伍槽位后弹出的式神选择面板，出现即表示可以换狗粮",
)
