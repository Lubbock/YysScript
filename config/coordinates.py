"""坐标类型。

`Point` 是**基准客户区**下的逻辑坐标，基准尺寸见 `settings.BASE_CLIENT_SIZE`（1024x768），
由 `actions/viewport.py` 按真实窗口位置与大小换算成屏幕坐标。

runner 的点击坐标来自分组标注（`similarity/dataset/`），经 `Session.resolve()` 换算，
不在这里维护。
"""
from __future__ import annotations

from typing import NamedTuple


class Point(NamedTuple):
    """基准客户区下的一个逻辑坐标。"""

    x: int
    y: int
