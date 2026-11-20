"""通用消息总线：进程内同步发布 / 订阅。

为什么要有它：flows 以前把「识别到 A 就点 A，然后等 B」写死在 run() 里，
状态与动作是硬编码的链条，加一条规则就得改流程本体。改成总线之后：

    识别到状态  ->  bus.publish("state.entered.SOUL_CHALLENGE", event)
    订阅方      ->  自己决定点哪里 / 记什么计时 / 是否结束本轮

流程主体（flows/engine.py）只负责推进与广播，业务规则都变成可插拔的订阅方。

设计约束（照 AGENTS.md 的分层）：
- 本模块是 core 层的通用能力，**只依赖标准库**，不 import states / vision /
  actions / flows，也不认识任何领域事件；
- 同步投递：publish 返回时所有订阅方都已执行完。自动化脚本是单线程的，
  同步语义让「点击 -> 等界面」的顺序可推理，也不会丢事件；
- 异常隔离：默认一个订阅方抛错只记日志，不让它把整条流程带崩
  （挂机跑一晚上比「立刻失败」更重要）；测试里用 strict=True 暴露问题；
- 递归保护：订阅方里再 publish 是允许的，但深度超过上限就丢弃并记错误日志，
  避免两个订阅方互相触发导致无限递归。

topic 命名约定（点分层级，领域定义在 flows/signals.py）：
    "flow.started" / "round.finished" / "state.entered.SOUL_CHALLENGE"

订阅 topic 支持通配符，按 `.` 分段匹配：
    "*"        匹配**所有** topic
    "state.*"  匹配恰好两段的 state.xxx（如 state.detected），
               不匹配三段的 state.entered.HOME
    "state.**" 匹配 state 下的任意层级（含 state.entered.HOME）
    字面量     必须逐段相等
"""
from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, List, Optional, Sequence, Tuple

from core.logger import get_logger

log = get_logger(__name__)

#: 订阅方回调：入参是事件对象（可能为 None），返回值被忽略
Handler = Callable[[Any], None]

#: handler 内再 publish 的最大嵌套深度，超过就丢弃并告警
MAX_DEPTH: int = 32
#: history 环形缓冲长度，仅供排障回看「刚才都发了什么」
HISTORY_SIZE: int = 200
#: 匹配所有 topic 的特殊通配符
MATCH_ALL: str = "*"
#: 段内多层通配符
MATCH_DEEP: str = "**"


class Subscription:
    """一次订阅的凭据，可用于退订。

    priority 小的先执行（同优先级按注册顺序），
    once=True 表示触发一次后自动退订（适合「只处理第一次命中」的规则）。
    """

    __slots__ = ("topic", "handler", "priority", "seq", "once", "name")

    def __init__(
        self,
        topic: str,
        handler: Handler,
        priority: int = 0,
        seq: int = 0,
        once: bool = False,
    ) -> None:
        self.topic = topic
        self.handler = handler
        self.priority = priority
        self.seq = seq
        self.once = once
        self.name = getattr(handler, "__name__", repr(handler))

    def matches(self, topic: str) -> bool:
        """本订阅是否关心 topic。"""
        pattern = self.topic
        if pattern == topic:
            return True
        if pattern == MATCH_ALL:
            return True
        return _segments_match(pattern.split("."), topic.split("."))

    @property
    def order(self) -> Tuple[int, int]:
        """排序键：优先级 -> 注册顺序。"""
        return (self.priority, self.seq)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "<Subscription {} -> {} p={}>".format(self.topic, self.name, self.priority)


def _segments_match(pattern: Sequence[str], parts: Sequence[str]) -> bool:
    """按段匹配通配符：`*` = 恰好一段，`**` = 任意多段（含零段）。

    段的数量很小（topic 一般 2~3 段），直接递归即可，不用写容易出错的双指针回溯。
    """
    if not pattern:
        return not parts
    head, tail = pattern[0], pattern[1:]
    if head == MATCH_DEEP:
        # `**` 可以吃掉 0..len(parts) 段，逐个尝试
        return any(_segments_match(tail, parts[skip:])
                   for skip in range(len(parts) + 1))
    if not parts:
        return False
    if head == MATCH_ALL or head == parts[0]:
        return _segments_match(tail, parts[1:])
    return False


class EventBus:
    """进程内同步事件总线。

    用法：
        bus = EventBus()
        bus.subscribe("state.entered.SOUL_CHALLENGE", on_challenge)
        bus.publish("state.entered.SOUL_CHALLENGE", StateEvent(...))

    同一个 bus 实例通常由 Flow 创建（见 flows/base.py），一个流程一条总线，
    互不干扰；测试里可以直接构造。
    """

    def __init__(self, strict: bool = False, history_size: int = HISTORY_SIZE) -> None:
        """
        strict       : True 时订阅方抛出的异常直接向上传播（测试用）；
                       False（默认）只记日志，流程继续跑。
        history_size : history 环形缓冲长度，0 表示不记录。
        """
        self.strict = strict
        self._subs: List[Subscription] = []
        self._lock = threading.RLock()
        self._seq = itertools.count()
        self._depth = 0
        #: publish 因递归超深被丢弃的次数
        self.dropped: int = 0
        #: 订阅方抛错被吞掉的次数
        self.errors: int = 0
        # maxlen=0 时 deque 会直接丢弃写入，正好实现「history_size=0 表示不记录」
        self._history: Deque[Tuple[float, str, Any]] = deque(
            maxlen=max(0, int(history_size)))

    # ------------------------------------------------------------------ 订阅
    def subscribe(
        self,
        topic: str,
        handler: Handler,
        priority: int = 0,
        once: bool = False,
    ) -> Subscription:
        """登记订阅，返回可用于退订的 Subscription。"""
        if not callable(handler):
            raise TypeError("handler 必须是可调用对象: {!r}".format(handler))
        sub = Subscription(topic, handler, priority=priority,
                           seq=next(self._seq), once=once)
        with self._lock:
            self._subs.append(sub)
            self._subs.sort(key=lambda item: item.order)
        log.debug("订阅 %s -> %s（priority=%s once=%s）", topic, sub.name, priority, once)
        return sub

    def listen(self, topic: str, priority: int = 0, once: bool = False):
        """subscribe 的装饰器写法：

            @bus.listen("state.detected")
            def on_state(event): ...
        """

        def decorator(handler: Handler) -> Handler:
            self.subscribe(topic, handler, priority=priority, once=once)
            return handler

        return decorator

    def unsubscribe(self, target) -> bool:
        """退订。target 可以是 Subscription，也可以是 (topic, handler)。"""
        with self._lock:
            if isinstance(target, Subscription):
                if target in self._subs:
                    self._subs.remove(target)
                    return True
                return False
            topic, handler = target
            before = len(self._subs)
            self._subs = [
                sub for sub in self._subs
                if not (sub.topic == topic and sub.handler == handler)
            ]
            return len(self._subs) != before

    def clear(self) -> None:
        """清空全部订阅（流程结束时调用，避免复用实例时串台）。"""
        with self._lock:
            self._subs.clear()

    def subscriptions(self, topic: Optional[str] = None) -> List[Subscription]:
        """当前订阅快照；给了 topic 就只返回关心它的订阅。"""
        with self._lock:
            subs = list(self._subs)
        if topic is None:
            return subs
        return [sub for sub in subs if sub.matches(topic)]

    # ------------------------------------------------------------------ 发布
    def publish(self, topic: str, event: Any = None) -> int:
        """同步投递事件，返回实际执行的订阅方数量。

        订阅方抛错时：strict=True 直接抛出；否则记日志后继续下一个。
        嵌套深度超过 MAX_DEPTH 时丢弃本次投递（记 error 日志 + self.dropped 自增）。
        """
        with self._lock:
            targets = [sub for sub in self._subs if sub.matches(topic)]
            if self._depth >= MAX_DEPTH:
                self.dropped += 1
                log.error("事件嵌套超过 %s 层，丢弃 %s（检查订阅方是否互相触发）",
                          MAX_DEPTH, topic)
                return 0
            self._depth += 1
        fired = 0
        consumed: List[Subscription] = []
        try:
            # 这两行放在 try 里：万一抛异常，下面的 finally 仍会把 _depth 减回去，
            # 否则累计到 MAX_DEPTH 次之后所有事件都会被递归保护静默丢弃
            self._history.append((time.time(), topic, event))
            log.debug("publish %s -> %s 个订阅方", topic, len(targets))
            for sub in targets:
                try:
                    sub.handler(event)
                except Exception:  # noqa: BLE001 - 订阅方异常不应打断主流程
                    self.errors += 1
                    if self.strict:
                        raise
                    log.exception("订阅方 %s 处理 %s 失败", sub.name, topic)
                else:
                    fired += 1
                if sub.once:
                    consumed.append(sub)
        finally:
            with self._lock:
                self._depth -= 1
                for sub in consumed:
                    if sub in self._subs:
                        self._subs.remove(sub)
        return fired

    # ------------------------------------------------------------------ 排障
    @property
    def history(self) -> List[Tuple[float, str, Any]]:
        """最近的 (时间戳, topic, 事件) 列表，按时间正序。"""
        return list(self._history)

    def recent_topics(self, limit: int = 10) -> List[str]:
        """最近 limit 条 topic，给日志 / --debug 排障用。"""
        return [topic for _, topic, _ in list(self._history)[-limit:]]
