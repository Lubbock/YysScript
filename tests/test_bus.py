"""消息总线测试：投递顺序、通配符、退订、异常隔离、递归保护。

不需要 cv2 / 截图 / 游戏窗口。
"""
import pytest

import core.bus as bus_module
from core.bus import EventBus


def recorder(sink, label):
    def handler(event):
        sink.append((label, event))
    return handler


def test_publish_returns_number_of_handlers():
    bus = EventBus()
    sink = []
    bus.subscribe("a.b", recorder(sink, "first"))
    bus.subscribe("a.b", recorder(sink, "second"))
    assert bus.publish("a.b", 1) == 2
    assert sink == [("first", 1), ("second", 1)]


def test_publish_without_subscribers_returns_zero():
    assert EventBus().publish("nobody.listens", "x") == 0


def test_same_priority_keeps_registration_order():
    bus = EventBus()
    sink = []
    bus.subscribe("t", recorder(sink, "one"))
    bus.subscribe("t", recorder(sink, "two"))
    bus.subscribe("t", recorder(sink, "three"))
    bus.publish("t", None)
    assert [label for label, _ in sink] == ["one", "two", "three"]


def test_lower_priority_runs_first():
    bus = EventBus()
    sink = []
    bus.subscribe("t", recorder(sink, "normal"), priority=0)
    bus.subscribe("t", recorder(sink, "late"), priority=10)
    bus.subscribe("t", recorder(sink, "early"), priority=-10)
    bus.publish("t", None)
    assert [label for label, _ in sink] == ["early", "normal", "late"]


def test_exact_topic_only_matches_itself():
    bus = EventBus()
    sink = []
    bus.subscribe("state.detected", recorder(sink, "hit"))
    bus.publish("state.entered.HOME", None)
    assert sink == []
    bus.publish("state.detected", None)
    assert len(sink) == 1


def test_single_star_matches_exactly_one_segment():
    bus = EventBus()
    sink = []
    bus.subscribe("state.*", recorder(sink, "one-segment"))
    bus.publish("state.detected", None)
    bus.publish("state.timeout", None)
    bus.publish("state.entered.HOME", None)   # 三段，不该命中
    bus.publish("round.started", None)        # 前缀不同
    assert len(sink) == 2


def test_double_star_matches_nested_topics():
    bus = EventBus()
    sink = []
    bus.subscribe("state.**", recorder(sink, "deep"))
    bus.publish("state.detected", None)
    bus.publish("state.entered.SOUL_CHALLENGE", None)
    bus.publish("state.exited.HOME", None)
    bus.publish("round.started", None)
    assert len(sink) == 3


def test_bare_star_matches_everything():
    bus = EventBus()
    sink = []
    bus.subscribe("*", recorder(sink, "all"))
    for topic in ("a", "a.b", "a.b.c.d"):
        bus.publish(topic, None)
    assert len(sink) == 3


def test_state_key_topic_can_be_subscribed_precisely():
    """state.entered.<KEY> 精确订阅：这是「识别到状态 -> 订阅方动作」的核心用法。"""
    bus = EventBus()
    sink = []
    bus.subscribe("state.entered.SOUL_CHALLENGE", recorder(sink, "soul"))
    bus.subscribe("state.entered.SHARD_CHALLENGE", recorder(sink, "shard"))
    bus.publish("state.entered.SHARD_CHALLENGE", "payload")
    assert sink == [("shard", "payload")]


def test_unsubscribe_by_subscription_object():
    bus = EventBus()
    sink = []
    sub = bus.subscribe("t", recorder(sink, "x"))
    assert bus.unsubscribe(sub) is True
    assert bus.unsubscribe(sub) is False
    bus.publish("t", None)
    assert sink == []


def test_unsubscribe_by_topic_handler_pair():
    bus = EventBus()
    sink = []
    handler = recorder(sink, "x")
    bus.subscribe("t", handler)
    assert bus.unsubscribe(("t", handler)) is True
    bus.publish("t", None)
    assert sink == []


def test_once_subscription_fires_only_once():
    bus = EventBus()
    sink = []
    bus.subscribe("t", recorder(sink, "once"), once=True)
    bus.subscribe("t", recorder(sink, "always"))
    bus.publish("t", None)
    bus.publish("t", None)
    assert [label for label, _ in sink] == ["once", "always", "always"]


def test_clear_removes_all_subscriptions():
    bus = EventBus()
    sink = []
    bus.subscribe("t", recorder(sink, "x"))
    bus.clear()
    assert bus.subscriptions() == []
    assert bus.publish("t", None) == 0


def test_listen_decorator_subscribes_and_returns_handler():
    bus = EventBus()
    sink = []

    @bus.listen("t")
    def handler(event):
        sink.append(event)

    assert callable(handler)
    bus.publish("t", 42)
    assert sink == [42]


def test_subscribe_rejects_non_callable():
    with pytest.raises(TypeError):
        EventBus().subscribe("t", "not-callable")


def test_handler_exception_is_isolated_by_default():
    """一个订阅方炸了，其余订阅方照常执行，主流程不中断。"""
    bus = EventBus()
    sink = []

    def boom(event):
        raise RuntimeError("订阅方内部错误")

    bus.subscribe("t", boom)
    bus.subscribe("t", recorder(sink, "survivor"))
    assert bus.publish("t", None) == 1          # 只有 survivor 成功
    assert bus.errors == 1
    assert len(sink) == 1


def test_strict_bus_propagates_handler_exception():
    bus = EventBus(strict=True)

    def boom(event):
        raise RuntimeError("炸")

    bus.subscribe("t", boom)
    with pytest.raises(RuntimeError):
        bus.publish("t", None)


def test_handler_may_publish_nested_events():
    bus = EventBus()
    sink = []

    def outer(event):
        sink.append("outer")
        bus.publish("inner", event)

    bus.subscribe("outer", outer)
    bus.subscribe("inner", recorder(sink, "inner"))
    bus.publish("outer", None)
    assert sink == ["outer", ("inner", None)]


def test_recursion_is_capped():
    """两个订阅方互相触发时不能无限递归：超过上限就丢弃并计数。"""
    bus = EventBus()
    calls = []

    def loop(event):
        calls.append(event)
        bus.publish("loop", event + 1)

    bus.subscribe("loop", loop)
    bus.publish("loop", 0)
    assert len(calls) == bus_module.MAX_DEPTH
    assert bus.dropped == 1


def test_history_records_recent_topics():
    bus = EventBus(history_size=3)
    for index in range(5):
        bus.publish("t.{}".format(index), None)
    assert bus.recent_topics() == ["t.2", "t.3", "t.4"]
    assert [topic for _, topic, _ in bus.history] == ["t.2", "t.3", "t.4"]


def test_history_can_be_disabled():
    bus = EventBus(history_size=0)
    bus.publish("t", "payload")
    assert bus.history == []


def test_history_keeps_event_payload():
    bus = EventBus()
    bus.publish("t", {"key": "value"})
    _, topic, event = bus.history[-1]
    assert topic == "t"
    assert event == {"key": "value"}


def test_subscriptions_can_be_filtered_by_topic():
    bus = EventBus()
    bus.subscribe("state.*", lambda event: None)
    bus.subscribe("round.started", lambda event: None)
    assert len(bus.subscriptions("state.detected")) == 1
    assert len(bus.subscriptions()) == 2
