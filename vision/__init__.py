"""图像识别层：截屏、模板匹配、颜色轮廓检测。

职责边界：只回答「屏幕/窗口上有什么、在哪里」，输出**屏幕绝对坐标**；
不负责点击，也不关心游戏窗口在哪（窗口区域由 actions 层通过 region_provider 注入）。

包入口做**懒加载**，避免仅使用 vision.types 时也被迫安装 cv2 / pyautogui。
"""
from __future__ import annotations

import importlib
from typing import Any

_LAZY = {
    "ScreenCapture": "vision.capture",
    "TemplateMatcher": "vision.template_matcher",
    "MonsterDetector": "vision.color_detector",
    "find_contours": "vision.color_detector",
    "Box": "vision.types",
    "Frame": "vision.types",
    "Match": "vision.types",
}

__all__ = list(_LAZY)


def __getattr__(name: str) -> Any:  # PEP 562
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    return getattr(importlib.import_module(module_name), name)


def __dir__():
    return sorted(__all__)
