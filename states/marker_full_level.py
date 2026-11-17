"""式神满级标记。"""
from states.base import State, StateKind

MARKER_FULL_LEVEL = State(
    key="MARKER_FULL_LEVEL",
    label="满级标记",
    templates=("满.png",),
    kind=StateKind.MARKER,
    description="式神头像上的「满」字，用于判断哪些狗粮需要替换（可能同屏多个）",
)
