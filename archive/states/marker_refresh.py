"""结界突破「刷新」按钮。"""
from states.base import State, StateKind

MARKER_REFRESH = State(
    key="MARKER_REFRESH",
    label="突破刷新按钮",
    templates=("突破刷新.png",),
    kind=StateKind.MARKER,
    description="九宫格全部打完后用于刷新结界列表的按钮",
)
