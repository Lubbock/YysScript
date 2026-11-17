"""状态机测试：用假 matcher 驱动，不需要 cv2 / 截图。"""
from contextlib import contextmanager

import pytest

from core.errors import StateTimeoutError
from states.base import State, StateKind
from states.machine import StateMachine
from vision.types import Box, Match

STATE_A = State(key="TEST_A", label="测试A", templates=("a.png",))
STATE_B = State(key="TEST_B", label="测试B", templates=("b.png",))
STATE_MULTI = State(key="TEST_MULTI", label="多模板", templates=("m1.png", "m2.png"))
TEST_STATE_KEYS = ("TEST_A", "TEST_B", "TEST_MULTI", "TEST_MARKER")

# State.__post_init__ 会自动注册进全局 REGISTRY，而 pytest 在**收集阶段**就 import
# 全部测试模块 —— 也就是说这些测试状态会在任何 fixture 运行之前污染注册表，
# 导致 test_states_registry / test_asset_manager_api 的数量断言失败。
# 所以这里在 import 当下就摘掉；需要按 key 字符串查找的用例用 _registered() 临时挂回。
from states.base import REGISTRY as _REGISTRY  # noqa: E402

for _key in TEST_STATE_KEYS:
    _REGISTRY.pop(_key, None)


@contextmanager
def _registered(*to_register):
    """临时把测试状态挂回 REGISTRY，供 as_coerce 按 key 字符串查找。"""
    for st in to_register:
        _REGISTRY[st.key] = st
    try:
        yield
    finally:
        for st in to_register:
            _REGISTRY.pop(st.key, None)


def make_match(template: str, score: float) -> Match:
    return Match(box=Box(0, 0, 10, 10), score=score, template=template)


class FakeMatcher:
    """按 template -> Match 的字典返回结果，可动态修改模拟界面变化。"""

    def __init__(self, hits=None):
        self.hits = dict(hits or {})
        self.calls = []

    def match(self, filename, threshold=None, region=None):
        self.calls.append(filename)
        return self.hits.get(filename)

    def match_all(self, filename, threshold=None, region=None, limit=None):
        result = self.match(filename, threshold, region)
        return [result] if result else []


def test_is_active_and_locate():
    matcher = FakeMatcher({"a.png": make_match("a.png", 0.91)})
    machine = StateMachine(matcher)
    assert machine.is_active(STATE_A)
    assert machine.locate(STATE_A).score == pytest.approx(0.91)
    assert not machine.is_active(STATE_B)


def test_locate_picks_best_template():
    matcher = FakeMatcher({
        "m1.png": make_match("m1.png", 0.72),
        "m2.png": make_match("m2.png", 0.88),
    })
    machine = StateMachine(matcher)
    assert machine.locate(STATE_MULTI).score == pytest.approx(0.88)


def test_accepts_key_string():
    matcher = FakeMatcher({"a.png": make_match("a.png", 0.8)})
    machine = StateMachine(matcher)
    with _registered(STATE_A):
        assert machine.is_active("TEST_A")


def test_detect_returns_highest_score():
    matcher = FakeMatcher({
        "a.png": make_match("a.png", 0.75),
        "b.png": make_match("b.png", 0.95),
    })
    detection = StateMachine(matcher).detect([STATE_A, STATE_B])
    assert detection.state is STATE_B
    assert detection.score == pytest.approx(0.95)


def test_detect_first_respects_order():
    matcher = FakeMatcher({
        "a.png": make_match("a.png", 0.75),
        "b.png": make_match("b.png", 0.95),
    })
    detection = StateMachine(matcher).detect_first([STATE_A, STATE_B])
    assert detection.state is STATE_A


def test_detect_none_when_nothing_matches():
    assert StateMachine(FakeMatcher()).detect([STATE_A, STATE_B]) is None


def test_wait_for_returns_immediately_when_active():
    matcher = FakeMatcher({"a.png": make_match("a.png", 0.9)})
    assert StateMachine(matcher).wait_for(STATE_A, timeout=0, interval=0)


def test_wait_for_times_out():
    machine = StateMachine(FakeMatcher())
    assert machine.wait_for(STATE_A, timeout=0.01, interval=0.01) is False


def test_wait_for_calls_hook():
    calls = []
    machine = StateMachine(FakeMatcher())
    machine.wait_for(STATE_A, timeout=0.03, interval=0.01, on_wait=calls.append)
    assert calls, "on_wait 回调应被调用"


def test_expect_raises_on_timeout():
    machine = StateMachine(FakeMatcher())
    with pytest.raises(StateTimeoutError) as exc_info:
        machine.expect(STATE_A, timeout=0.01, interval=0.01)
    assert exc_info.value.state_key == "TEST_A"


def test_wait_gone_succeeds_when_absent():
    machine = StateMachine(FakeMatcher())
    assert machine.wait_gone(STATE_A, timeout=0.01, interval=0.01)


def test_wait_gone_times_out_when_present():
    matcher = FakeMatcher({"a.png": make_match("a.png", 0.9)})
    machine = StateMachine(matcher)
    assert machine.wait_gone(STATE_A, timeout=0.02, interval=0.01) is False


def test_wait_gone_detects_transition():
    """界面从有到无：wait_gone 应在状态消失后返回 True。"""
    matcher = FakeMatcher({"a.png": make_match("a.png", 0.9)})
    machine = StateMachine(matcher)

    def hook(rounds):
        if rounds >= 2:
            matcher.hits.clear()

    assert machine.wait_gone(STATE_A, timeout=5, interval=0.01, on_wait=hook)


def test_wait_any_returns_first_hit():
    matcher = FakeMatcher({"b.png": make_match("b.png", 0.8)})
    detection = StateMachine(matcher).wait_any([STATE_A, STATE_B], timeout=0.02, interval=0.01)
    assert detection is not None and detection.state is STATE_B


def test_wait_any_timeout_returns_none():
    machine = StateMachine(FakeMatcher())
    assert machine.wait_any([STATE_A, STATE_B], timeout=0.02, interval=0.01) is None


def test_locate_all():
    matcher = FakeMatcher({"a.png": make_match("a.png", 0.9)})
    assert len(StateMachine(matcher).locate_all(STATE_A)) == 1
    assert StateMachine(FakeMatcher()).locate_all(STATE_A) == []


def test_marker_kind_flag():
    marker = State(key="TEST_MARKER", label="标记", templates=("x.png",),
                   kind=StateKind.MARKER)
    try:
        assert not marker.is_screen
        assert marker.template == "x.png"
    finally:
        _REGISTRY.pop("TEST_MARKER", None)
