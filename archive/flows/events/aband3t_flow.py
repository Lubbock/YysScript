"""活动事件 Aband3t 循环（事件驱动版）。

对应旧 scripts/abnd3t.py：
等阶段 3 出现 -> 点击 -> 长等待（约 120 秒）-> 等阶段 2 出现 -> 点击 -> 下一轮。

迁移到事件驱动后：流程本体只负责组装 `flows/stage_cycle.py` 的 StageCycle，
「等哪个界面、点完等多久、超时怎么办」都变成订阅方的参数。

与旧实现的差异：
1. 旧代码用 ExitEvent 计数，超限直接 exit(300)；现在等不到起始阶段抛 FlowAbortedError，
   由 main.py 统一处理退出码。
2. 旧代码把模板匹配到的右下角再减 50,50 当作点击点；现在直接点匹配框中心。
3. 中间那段固定 `sleep(STAGE_WAIT=120)` 只在**还没有历史样本**时使用；
   跑满 5 轮后改由 core/timing.py 按真实耗时的 p10 盲等，通常比 120 秒短得多，
   而且不会像固定值那样在阶段提前结束时空等。
4. 每一轮的耗时会被记进 sqlite（key = `event-aband3t:stage`），流程结束打总账。
"""
from __future__ import annotations

from typing import Optional

from actions.controller import GameController
from flows.base import Flow
from flows.stage_cycle import StageCycle
from states.event_aband3t_0 import EVENT_ABAND3T_0
from states.event_aband3t_2 import EVENT_ABAND3T_2
from states.event_aband3t_3 import EVENT_ABAND3T_3


class Aband3tFlow(Flow):
    """Aband3t 活动事件循环。"""

    name = "event-aband3t"
    description = "活动事件 Aband3t 循环"

    #: 等阶段 3 出现的超时（旧代码 ExitEvent(20) x 2 秒）
    STAGE_TIMEOUT = 40.0
    #: 点击阶段 3 后的固定长等待；仅在计时样本未收敛时使用，收敛后由盲等取代
    STAGE_WAIT = 120.0
    #: 等阶段 2（结算）出现的超时（旧代码 ExitEvent(150) x 10 秒）
    SETTLE_TIMEOUT = 1500.0
    #: 等阶段 2 时的探测间隔
    SETTLE_INTERVAL = 10.0
    #: 点完结算后的停顿
    SETTLE_PAUSE = 2.0
    #: 阶段耗时的计时 key
    TIMING_KEY = "event-aband3t:stage"

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        loops: int = 20,
        **kwargs,
    ) -> None:
        """kwargs 透传给 Flow（bus / timer / adaptive）。"""
        super().__init__(controller=controller, machine=machine, **kwargs)
        self.loops = loops

    def start_event(self) -> None:
        """点击活动入口（旧 complete00000）。run() 不调用它，保留给手工/外部编排。"""
        self.log.info("开始事件 Aband3t-0")
        self.click_state(EVENT_ABAND3T_0, timeout=self.STAGE_TIMEOUT, interval=2)

    def run(self) -> None:
        engine = self.create_engine()
        cycle = StageCycle(
            engine,
            start_state=EVENT_ABAND3T_3,
            end_state=EVENT_ABAND3T_2,
            timing_key=self.TIMING_KEY,
            start_timeout=self.STAGE_TIMEOUT,
            start_interval=2.0,
            end_timeout=self.SETTLE_TIMEOUT,
            end_interval=self.SETTLE_INTERVAL,
            initial_blind_wait=self.STAGE_WAIT,
            end_pause=self.SETTLE_PAUSE,
            end_required=True,
        ).attach()
        engine.run_rounds(self.loops, round_timeout=cycle.round_timeout())
        self.log.info("Aband3t 事件循环结束")
