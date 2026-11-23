"""游戏首页（主城）。"""
from states.base import State

HOME = State(
    key="HOME",
    label="游戏首页",
    templates=("首页.png",),
    description="登录后的主城界面，大部分流程的起点与回归点",
)
