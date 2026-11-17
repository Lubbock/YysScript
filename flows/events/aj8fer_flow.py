"""活动事件 Aj8fer 循环（带耗时预测）。

对应旧 scripts/aj8fer.py：
点阶段 1 -> 用历史耗时预测要等多久 -> 等阶段 2（结算）-> 记录本次耗时 -> 点击结算。

预测数据来源 storage.DurationStore（sqlite var/gray_scan.db）：
跑得越多，等待时间越贴近真实值，不用一直按最坏情况 sleep。
"""
from __future__ import annotations

from typing import Optional

from actions.controller import GameController
from flows.base import Flow
from states.event_aband3t_2 import EVENT_ABAND3T_2
from states.event_aj8fer_1 import EVENT_AJ8FER_1


class Aj8ferFlow(Flow):
    """Aj8fer 活动事件循环。"""

    name = "event-aj8fer"
    description = "活动事件 Aj8fer 循环（带耗时预测）"

    #: 耗时样本在数据库里的 key，沿用旧脚本的命名以便复用历史数据
    PREDICT_KEY = "Aj8fer-1"
    #: 等阶段 1 出现的超时
    STAGE_TIMEOUT = 40.0
    #: 等阶段 2（结算）出现的超时
    SETTLE_TIMEOUT = 900.0
    #: 没有历史数据时的默认等待秒数
    DEFAULT_WAIT = 20.0

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        loops: int = 101,
    ) -> None:
        super().__init__(controller=controller, machine=machine)
        self.loops = loops

    def run(self) -> None:
        for index in range(self.loops):
            self.log.info("---------- Aj8fer 第 %s/%s 轮 ----------", index + 1, self.loops)

            self.click_state(EVENT_AJ8FER_1, timeout=self.STAGE_TIMEOUT, interval=2)

            predicted = self.predictor.predict(self.PREDICT_KEY, default=self.DEFAULT_WAIT)
            self.log.info("%s 预测等待 %s 秒", self.PREDICT_KEY, predicted)
            self.sleep(predicted)

            self.wait(
                EVENT_ABAND3T_2,
                timeout=self.SETTLE_TIMEOUT,
                interval=3,
                on_wait=lambda rounds: self.log.info("战斗进行中，未检测到结算界面（第 %s 次）", rounds),
            )
            self.predictor.record(self.PREDICT_KEY)

            self.click_state(EVENT_ABAND3T_2, required=False)
            self.sleep(1)

        self.log.info("Aj8fer 事件循环结束")
