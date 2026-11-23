"""状态层：图像模板 -> 具名状态常量 -> 状态机。

组织方式：
- base.py    : State / StateKind 定义与全局注册表 REGISTRY
- machine.py : StateMachine（is_active / locate / wait_for / wait_gone / wait_any）
- 其余每个文件 = 一个状态，文件名即状态 key 的小写形式

导入本包会自动扫描并加载所有状态文件，因此 `states.REGISTRY` 里包含全部状态；
业务代码推荐直接 `from states.home import HOME` 引用具体常量，可读性更好。
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import List

from states.base import REGISTRY, State, StateKind, all_states, get_state, register
from states.machine import Detection, StateMachine

_SKIP_MODULES = {"base", "machine"}


def _autoload() -> None:
    """扫描本包下的状态文件并导入，触发 State 自动注册。"""
    package_dir = Path(__file__).parent
    for module_info in pkgutil.iter_modules([str(package_dir)]):
        name = module_info.name
        if name.startswith("_") or name in _SKIP_MODULES:
            continue
        importlib.import_module("states.{}".format(name))


_autoload()

#: 全部界面状态（SCREEN），常用于「我现在到底在哪个页面」的判断
SCREEN_STATES: List[State] = all_states(StateKind.SCREEN)
#: 全部定位标记（MARKER）
MARKER_STATES: List[State] = all_states(StateKind.MARKER)

__all__ = [
    "REGISTRY",
    "State",
    "StateKind",
    "StateMachine",
    "Detection",
    "all_states",
    "get_state",
    "register",
    "SCREEN_STATES",
    "MARKER_STATES",
]
