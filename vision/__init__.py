"""视觉输入层：截屏。

只负责把窗口区域取成 BGR 数组；不负责点击，窗口矩形由 actions 层注入。

包入口懒加载，仅用 vision.types 时不需要 cv2 / pyautogui。
"""
from __future__ import annotations

import importlib
from typing import Any

_LAZY = {
    "ScreenCapture": "vision.capture",
    "Frame": "vision.types",
}

__all__ = list(_LAZY)


def __getattr__(name: str) -> Any:  # PEP 562
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError("module {!r} has no attribute {!r}" % (__name__, name))
    return getattr(importlib.import_module(module_name), name)


def __dir__():
    return sorted(__all__)
