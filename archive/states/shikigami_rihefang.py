"""式神图标：日和坊。"""
from states.base import State, StateKind

SHIKIGAMI_RIHEFANG = State(
    key="SHIKIGAMI_RIHEFANG",
    label="日和坊",
    templates=("日和仿.png",),
    kind=StateKind.MARKER,
    description="式神选择列表中的日和坊头像（模板已就位，暂无流程使用）",
)
