"""活动事件 Aj8fer 循环（事件驱动版，带耗时预测）。

对应旧 scripts/aj8fer.py：
点阶段 1 -> 用历史耗时预测要等多久 -> 等阶段 2（结算）-> 记录本次耗时 -> 点击结算。

与旧实现的差别只在「怎么预测」：
- 旧：`core/stopwatch.py` 的 WaitPredictor，取全部历史样本的**均值 + 1 秒**，
  然后死等这么久再开始识图；
- 新：`core/timing.py` 的 CycleTimer，取最近窗口内**剔除异常值后的 p10 × 0.85**
  再减去一次识图成本，之后按 1 秒细轮询。均值会被偶发的超长等待一路拉高，
  p10 不会；连续异常还会触发回退重新收敛（见 core/timing.py 的说明）。

计时 key 仍然沿用旧的 `Aj8fer-1`，所以 **老 gray_scan.db 里的历史样本直接可用**，
不需要重新攒 warm-up。

`Flow.predictor`（WaitPredictor）不再被本流程使用，但基类仍然创建它，
以免其它地方（或用户脚本）引用时出错。
"""
from __future__ import annotations

from typing import Optional

from actions.controller import GameController
from flows.base import Flow
from flows.stage_cycle import StageCycle
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
    #: 等阶段 2 时的探测间隔
    SETTLE_INTERVAL = 3.0
    #: 没有历史数据时的默认等待秒数（仅在计时样本未收敛时使用）
    DEFAULT_WAIT = 20.0
    #: 点完结算后的停顿
    SETTLE_PAUSE = 1.0
    #: 等待结算期间每拍的进度日志
    PROGRESS_MESSAGE = "战斗进行中，未检测到结算界面（第 %s 次）"

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        loops: int = 101,
        **kwargs,
    ) -> None:
        """kwargs 透传给 Flow（bus / timer / adaptive）。"""
        super().__init__(controller=controller, machine=machine, **kwargs)
        self.loops = loops

    def run(self) -> None:
        engine = self.create_engine()
        cycle = StageCycle(
            engine,
            start_state=EVENT_AJ8FER_1,
            end_state=EVENT_ABAND3T_2,
            timing_key=self.PREDICT_KEY,
            start_timeout=self.STAGE_TIMEOUT,
            start_interval=2.0,
            end_timeout=self.SETTLE_TIMEOUT,
            end_interval=self.SETTLE_INTERVAL,
            initial_blind_wait=self.DEFAULT_WAIT,
            end_pause=self.SETTLE_PAUSE,
            # 旧行为：等不到结算只告警并继续下一轮（click_state(required=False)）
            end_required=False,
            progress_message=self.PROGRESS_MESSAGE,
        ).attach()
        engine.run_rounds(self.loops, round_timeout=cycle.round_timeout())
        self.log.info("Aj8fer 事件循环结束")
