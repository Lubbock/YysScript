"""状态定义与注册表。

约定：
1. **每一个状态一个 python 文件**，文件名是状态 key 的小写形式；
2. 文件里定义一个模块级常量（大写），类型是 State；
3. 状态自动注册到 REGISTRY，flows 通过 `from states.home import HOME` 直接引用；
4. 状态里不写坐标、不写业务逻辑，只描述「用哪张模板图、多高的阈值、代表什么界面」。

两种 kind：
- SCREEN : 用来判断「当前在哪个界面」，状态机 wait_for / is_active 的对象
- MARKER : 用来「定位某个按钮 / 图标」，配合 locate / locate_all 拿到坐标
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from config import settings
from core.errors import ConfigError


class StateKind(Enum):
    """状态用途分类。"""

    SCREEN = "screen"   # 界面状态：判断当前处于哪个页面
    MARKER = "marker"   # 定位标记：找出某个按钮 / 图标的位置


@dataclass(frozen=True)
class State:
    """一个可被图像识别判定的状态。

    key       : 常量名，全局唯一，例如 "HOME"
    label     : 中文描述，用于日志
    templates : 模板图片文件名（相对 assets/templates），命中任意一个即算命中
    threshold : 匹配阈值，默认 settings.DEFAULT_THRESHOLD
    kind      : SCREEN 或 MARKER
    """

    key: str
    label: str
    templates: Tuple[str, ...]
    threshold: float = settings.DEFAULT_THRESHOLD
    kind: StateKind = StateKind.SCREEN
    description: str = ""

    def __post_init__(self) -> None:
        if not self.templates:
            raise ConfigError("状态 {} 必须至少绑定一张模板图片".format(self.key))
        register(self)

    # -------------------------------------------------------------- 便捷属性
    @property
    def template(self) -> str:
        """主模板（第一个）。"""
        return self.templates[0]

    @property
    def is_screen(self) -> bool:
        return self.kind is StateKind.SCREEN

    def __str__(self) -> str:  # 日志里显示 key(label)
        return "{}({})".format(self.key, self.label)


# --------------------------------------------------------------------------- #
# 注册表
# --------------------------------------------------------------------------- #
REGISTRY: Dict[str, State] = {}


def register(state: State) -> State:
    """登记状态；key 冲突且定义不同时抛错，避免两个文件抢同一个名字。"""
    existing = REGISTRY.get(state.key)
    if existing is not None and existing != state:
        raise ConfigError(
            "状态 key 重复且定义不同: {} -> {} / {}".format(state.key, existing, state)
        )
    REGISTRY[state.key] = state
    return state


def get_state(key: str) -> State:
    """按 key 取状态，不存在时抛 ConfigError。"""
    try:
        return REGISTRY[key]
    except KeyError:
        raise ConfigError("未注册的状态: {}（已注册 {} 个）".format(key, len(REGISTRY)))


def all_states(kind: Optional[StateKind] = None) -> List[State]:
    """全部状态，可按 kind 过滤。"""
    states = list(REGISTRY.values())
    if kind is not None:
        states = [s for s in states if s.kind is kind]
    return sorted(states, key=lambda s: s.key)


def as_coerce(state: "State | str") -> State:
    """允许传 State 对象或 key 字符串。"""
    if isinstance(state, State):
        return state
    return get_state(str(state))
