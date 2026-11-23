"""操作层：找游戏窗口 -> 换算坐标 -> 拟人化点击。

- window.py     : 定位游戏窗口客户区（win32 / macOS 镜像 / 全屏回退）
- viewport.py   : 基准客户区逻辑坐标 <-> 屏幕绝对坐标（纯计算，可单测）
- mouse.py      : 抖动、随机停顿、分步拖动等拟人化鼠标动作

包入口懒加载：没有 pyautogui 的环境也能用 `Viewport` 跑单测。

"""
from __future__ import annotations

import importlib
from typing import Any

_LAZY = {
    "HumanMouse": "actions.mouse",
    "Viewport": "actions.viewport",
    "GameWindow": "actions.window",
    "WindowRect": "actions.window",
    "WindowFinder": "actions.window",
    "Win32WindowFinder": "actions.window",
    "MacWindowFinder": "actions.window",
    "FullScreenFinder": "actions.window",
    "create_window": "actions.window",
}

__all__ = list(_LAZY)


def __getattr__(name: str) -> Any:  # PEP 562
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    return getattr(importlib.import_module(module_name), name)


def __dir__():
    return sorted(__all__)
