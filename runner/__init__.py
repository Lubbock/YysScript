"""DSL 驱动的分组标注执行管线。

数据来自 `similarity/dataset/groups/<key>/`：截图 + 标注由标注采集页产出，
执行顺序由该分组目录下的 `flow.py`（DSL）声明。

分层：
    group.py    分组解析：标注数据 -> ShotRef / AnnotationRef / GroupRef
    dsl.py      DSL 加载：exec flow.py，注入 step / gfx / shots / group / log
    session.py  窗口 + 截屏 + 视口 + 拟人化鼠标
    matcher.py  单图比对：当前画面是不是这一张（调 similarity.llm_judge）
    actor.py    点击：标注坐标 -> Viewport -> HumanMouse
    engine.py   主循环：轮次控制 + 按 steps 推进 + 自适应等待
    gfx.py      外部图形算法，DSL 里直接调用

包入口懒加载，避免仅用 group / dsl 时被迫安装 cv2、pyautogui。
"""
from __future__ import annotations

import importlib
from typing import Any

_LAZY = {
    "Actor": "runner.actor",
    "ClickOutcome": "runner.actor",
    "AnnotationRef": "runner.group",
    "GroupRef": "runner.group",
    "ShotRef": "runner.group",
    "load_group": "runner.group",
    "list_groups": "runner.group",
    "open_dataset": "runner.group",
    "Flow": "runner.dsl",
    "Step": "runner.dsl",
    "step": "runner.dsl",
    "load_flow": "runner.dsl",
    "load_group_flow": "runner.dsl",
    "scaffold": "runner.dsl",
    "write_scaffold": "runner.dsl",
    "Context": "runner.engine",
    "Runner": "runner.engine",
    "RunReport": "runner.engine",
    "RoundReport": "runner.engine",
    "StepReport": "runner.engine",
    "ResolvedStep": "runner.engine",
    "build_runner": "runner.engine",
    "ScreenMatcher": "runner.matcher",
    "Verdict": "runner.matcher",
    "Session": "runner.session",
    "ClickResult": "runner.session",
    "RunnerError": "runner.errors",
    "GroupError": "runner.errors",
    "DslError": "runner.errors",
    "StepResolveError": "runner.errors",
    "StepTimeout": "runner.errors",
    "RoundTimeout": "runner.errors",
    "ClickError": "runner.errors",
}

__all__ = list(_LAZY)


def __getattr__(name: str) -> Any:  # PEP 562
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    return getattr(importlib.import_module(module_name), name)


def __dir__():
    return sorted(__all__)
