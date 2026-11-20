"""项目统一异常。

旧代码用 exit(300) 直接终止进程，无法被上层捕获和复用；
现在一律抛异常，由 main.py 决定退出码。
"""
from __future__ import annotations


class YysError(Exception):
    """所有项目异常的基类。"""


class ConfigError(YysError):
    """配置错误，例如模板图片缺失。"""


class WindowNotFoundError(YysError):
    """找不到游戏窗口，且未开启全屏回退。"""


class StateTimeoutError(YysError):
    """等待某个界面状态超时。"""

    def __init__(self, state_key: str, timeout: float) -> None:
        self.state_key = state_key
        self.timeout = timeout
        super().__init__("等待状态 {} 超时（{} 秒）".format(state_key, timeout))


class StaminaExhaustedError(YysError):
    """体力耗尽，继续跑没有意义。"""


class FlowAbortedError(YysError):
    """流程主动中止（达到重试上限等）。"""


class WindowActivationError(YysError):
    """无法把目标窗口激活到前台（macOS 礼貌点击的前置条件）。

    是 YysError 的子类，所以 main.py 会把它转成退出码 1 并打印一句话，
    而不是抛出未捕获的 traceback 直接崩掉进程。
    """
