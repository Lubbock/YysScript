"""式神图标：骨女。"""
from states.base import State, StateKind

SHIKIGAMI_BONE_WOMAN = State(
    key="SHIKIGAMI_BONE_WOMAN",
    label="骨女",
    templates=("骨女.png",),
    kind=StateKind.MARKER,
    description="式神选择列表中的骨女头像（模板已就位，暂无流程使用）",
)
