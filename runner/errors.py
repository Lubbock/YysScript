"""runner 层异常。"""
from __future__ import annotations

from core.errors import YysError


class RunnerError(YysError):
    """主流程异常基类。"""


class GroupError(RunnerError):
    """分组解析失败。"""


class DslError(RunnerError):
    """DSL 非法。"""


class StepResolveError(DslError):
    """step 定位不到截图。"""


class StepTimeout(RunnerError):
    """等待某一步超时。"""


class RoundTimeout(RunnerError):
    """整轮超时。"""


class ClickError(RunnerError):
    """点击失败。"""
