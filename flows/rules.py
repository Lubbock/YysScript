"""可复用的通用订阅方（不含任何玩法知识）。

旧代码里到处是这种写法：

    self.wait(SOME_STATE, timeout=60, on_wait=lambda rounds: self.click(SOME_COORD))

也就是「一边等某个界面出现，一边每隔一会儿点一下别的东西」—— 因为游戏经常需要
你先点一下才会真的跳到那个界面（觉醒的挑战按钮、御心道场的选择、妖气封印的入口…）。

迁移到事件驱动后，等待发生在引擎的主循环里，`on_wait` 回调没有位置可挂，
所以把这个模式抽成一个独立订阅方：监听 `poll.completed`，在指定阶段按冷却时间补点。

触发条件与旧 `on_wait` 严格对齐：
- 旧 `wait(X, on_wait=f)`   -> f 在「X 没出现」的每一拍调用  -> `unless_state=X`
- 旧 `wait_gone(X, on_wait=f)` -> f 在「X 还在」的每一拍调用  -> `only_state=X`

放在 flows 层（而不是 core）是因为它认识 PollEvent / engine 这些领域概念。
"""
from __future__ import annotations

from typing import Any, List, Optional

from core.bus import Subscription
from flows.engine import FlowEngine
from flows.signals import (
    TOPIC_POLL_COMPLETED,
    TOPIC_ROUND_STARTED,
    PollEvent,
)


class ProbeWhileWaiting:
    """在引擎等待某个阶段期间，按冷却时间反复点击一个目标。

    参数：
        engine     : 目标引擎
        timing_key : 只在 `engine.wait_key == timing_key` 时生效，
                     即「正在等这个阶段」才补点，别的阶段不干扰
        target     : 要点的目标（Point / Match / Box / 屏幕坐标）
        unless_state: 命中这个状态时**不**点（等价旧 `wait(该状态, on_wait=...)`）
        only_state : 只有命中这个状态才点（等价旧 `wait_gone(该状态, on_wait=...)`）
        cooldown   : 两次补点之间的最小间隔（秒），0 表示每拍都点
        detail     : 写进 action.performed 的说明
        enabled    : 初始是否启用；订阅方可以随时关掉（例如进入战斗后就别再点了）

    `unless_state` 与 `only_state` 互斥，都不给则每拍都点。
    """

    def __init__(
        self,
        engine: FlowEngine,
        timing_key: str,
        target: Any,
        unless_state: Any = None,
        only_state: Any = None,
        cooldown: float = 0.0,
        detail: str = "",
        enabled: bool = True,
    ) -> None:
        if unless_state is not None and only_state is not None:
            raise ValueError("unless_state 与 only_state 不能同时给")
        self.engine = engine
        self.timing_key = timing_key
        self.target = target
        self.unless_key = _key_of(unless_state)
        self.only_key = _key_of(only_state)
        self.cooldown = float(cooldown)
        self.detail = detail or "等待 {} 期间补点".format(timing_key)
        self.enabled = enabled
        self.clicks = 0
        self._last_click = -1.0
        self._subs: List[Subscription] = []

    # ------------------------------------------------------------------ 挂载
    def attach(self) -> "ProbeWhileWaiting":
        """登记订阅；返回自身以便链式调用。"""
        self._subs = [
            self.engine.on(TOPIC_POLL_COMPLETED, self.on_poll),
            # 冷却基于 elapsed_round()，每轮都会归零，所以换轮时要清掉上一轮的记录
            self.engine.on(TOPIC_ROUND_STARTED, self.on_round_started),
        ]
        return self

    def detach(self) -> None:
        """退订全部事件。"""
        for sub in self._subs:
            self.engine.bus.unsubscribe(sub)
        self._subs = []

    def reset(self) -> None:
        """清掉冷却，保证下一拍就能点。"""
        self._last_click = -1.0

    # ------------------------------------------------------------------ 事件
    def on_round_started(self, event: Any = None) -> None:
        self.reset()

    def on_poll(self, event: PollEvent) -> None:
        if not self.enabled or self.engine.wait_key != self.timing_key:
            return
        if self.engine.interrupted:
            return
        if self.unless_key and event.state_key == self.unless_key:
            return                       # 等的界面已经出现了，不用再点
        if self.only_key and event.state_key != self.only_key:
            return                       # 只在目标界面还挂着时才点
        now = self.engine.elapsed_round()
        if self.cooldown > 0 and self._last_click >= 0 and \
                now - self._last_click < self.cooldown:
            return
        self._last_click = now
        self.clicks += 1
        self.engine.click(
            self.target, detail="{}（第 {} 次）".format(self.detail, self.clicks))


def _key_of(state: Any) -> str:
    """State 对象或 key 字符串 -> key 字符串；None -> 空串。"""
    if state is None:
        return ""
    return getattr(state, "key", str(state))
