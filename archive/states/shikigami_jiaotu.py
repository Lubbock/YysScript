"""式神图标：椒图。"""
from states.base import State, StateKind

SHIKIGAMI_JIAOTU = State(
    key="SHIKIGAMI_JIAOTU",
    label="椒图",
    templates=("椒图.png",),
    kind=StateKind.MARKER,
    description="式神选择列表中的椒图头像（模板已就位，暂无流程使用）",
)
