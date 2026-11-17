"""活动事件 Aband3t 循环。

对应旧 scripts/abnd3t.py：
等阶段 3 出现 -> 点击 -> 长等待（约 120 秒）-> 等阶段 2 出现 -> 点击 -> 下一轮。

与旧实现的差异：
1. 旧代码用 ExitEvent 计数，超限直接 exit(300)；现在等待超时抛 StateTimeoutError，
   由 main.py 统一处理退出码。
2. 旧代码把模板匹配到的右下角再减 50,50 当作点击点；现在直接点匹配框中心。
"""
from __future__ import annotations

from typing import Optional

from actions.controller import GameController
from flows.base import Flow
from states.event_aband3t_0 import EVENT_ABAND3T_0
from states.event_aband3t_2 import EVENT_ABAND3T_2
from states.event_aband3t_3 import EVENT_ABAND3T_3


class Aband3tFlow(Flow):
    """Aband3t 活动事件循环。"""

    name = "event-aband3t"
    description = "活动事件 Aband3t 循环"

    #: 等阶段 3 出现的超时（旧代码 ExitEvent(20) x 2 秒）
    STAGE_TIMEOUT = 40.0
    #: 点击阶段 3 后的固定长等待
    STAGE_WAIT = 120.0
    #: 等阶段 2（结算）出现的超时（旧代码 ExitEvent(150) x 10 秒）
    SETTLE_TIMEOUT = 1500.0

    def __init__(
        self,
        controller: Optional[GameController] = None,
        machine=None,
        loops: int = 20,
    ) -> None:
        super().__init__(controller=controller, machine=machine)
        self.loops = loops

    def start_event(self) -> None:
        """点击活动入口（旧 complete00000）。"""
        self.log.info("开始事件 Aband3t-0")
        self.click_state(EVENT_ABAND3T_0, timeout=self.STAGE_TIMEOUT, interval=2)

    def run(self) -> None:
        for index in range(self.loops):
            self.log.info("---------- Aband3t 第 %s/%s 轮 ----------", index + 1, self.loops)

            self.click_state(EVENT_ABAND3T_3, timeout=self.STAGE_TIMEOUT, interval=2)
            self.sleep(self.STAGE_WAIT)

            self.log.info("等待 Aband3t-2 结算 ...")
            self.click_state(EVENT_ABAND3T_2, timeout=self.SETTLE_TIMEOUT, interval=10)
            self.sleep(2)

        self.log.info("Aband3t 事件循环结束")
