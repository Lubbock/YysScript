"""计时与等待时间预测。

对应旧 scripts/a_base.py 里的 StopWatch / WaitPredication：
把每个动作实际耗时记到 storage，下次用历史均值代替拍脑袋的 time.sleep。

⚠️ 新的流程请优先用 `core/timing.py` 的 `CycleTimer`：它除了记耗时，还会给出
「先盲等多久、之后隔多久识图」的等待计划，并处理异常样本导致的不收敛问题。
本模块保留给 `event-aj8fer`（历史样本 key `Aj8fer-1` 语义不变，老数据可继续用）。
"""
from __future__ import annotations

import time
from typing import Dict, Optional

from core.logger import get_logger
from storage.duration_store import DurationStore

log = get_logger(__name__)


class Stopwatch:
    """按关键字记录开始 / 结束时间。"""

    def __init__(self) -> None:
        self._start: Dict[str, float] = {}
        self._end: Dict[str, float] = {}

    def start(self, key: str) -> None:
        now = time.time()
        self._start[key] = now
        self._end[key] = now
        log.info("%s 开始计时", key)

    def end(self, key: str) -> int:
        if key not in self._start:
            raise KeyError("未开始计时: {}".format(key))
        now = time.time()
        self._end[key] = now
        elapsed = int(now - self._start[key])
        log.info("%s 耗时 %s 秒", key, elapsed)
        return elapsed

    def duration(self, key: str) -> int:
        return int(self._end[key] - self._start[key])


class WaitPredictor:
    """用历史耗时预测「这一步大概要等多久」。"""

    def __init__(self, store: Optional[DurationStore] = None) -> None:
        self._store = store or DurationStore()
        self._watch = Stopwatch()

    def predict(self, key: str, default: float = 20.0) -> float:
        """返回预测等待秒数；没有历史数据时返回 default。"""
        self._watch.start(key)
        average = self._store.average(key)
        if average is None:
            return default
        return average + 1

    def record(self, key: str) -> int:
        """结束计时并把耗时写入存储。"""
        elapsed = self._watch.end(key)
        self._store.record(key, elapsed)
        return elapsed
