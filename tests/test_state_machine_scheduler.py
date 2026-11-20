"""状态机 wait_* 的 scheduler 参数测试。

关键契约：
1. **不传 scheduler 时，行为与改造前逐字一致**（固定 interval 轮询，不盲等）；
2. 传了 scheduler 就先盲等一次，再按 scheduler 给的间隔轮询；
3. 盲等额度只用一次，且不会超过本次等待的 timeout。

不截屏、不点击：matcher 是假的，time.sleep 被打桩成记录器。
"""
import time

import pytest

from config import settings
from core.timing import WaitPlan
from states.base import REGISTRY, State
from states.machine import StateMachine
from vision.types import Box, Match

STATE_A = State(key="TS_A", label="测试A", templates=("ts_a.png",))
STATE_B = State(key="TS_B", label="测试B", templates=("ts_b.png",))
TEST_STATE_KEYS = ("TS_A", "TS_B")

# 见 test_state_machine.py 的同款说明：测试状态不能污染全局注册表
for _key in TEST_STATE_KEYS:
    REGISTRY.pop(_key, None)


def make_match(template: str, score: float = 0.9) -> Match:
    return Match(box=Box(0, 0, 10, 10), score=score, template=template)


class FakeMatcher:
    def __init__(self, hits=None):
        self.hits = dict(hits or {})
        self.calls = []

    def match(self, filename, threshold=None, region=None):
        self.calls.append(filename)
        return self.hits.get(filename)

    def match_all(self, filename, threshold=None, region=None, limit=None):
        result = self.match(filename, threshold, region)
        return [result] if result else []


class FakeScheduler:
    """记录被问了什么，返回固定的等待计划。"""

    def __init__(self, blind_wait=0.0, interval=1.0):
        self.blind_wait = blind_wait
        self.interval = interval
        self.calls = []

    def plan(self, key, timeout, interval=None):
        self.calls.append((key, timeout, interval))
        return WaitPlan(blind_wait=self.blind_wait, interval=self.interval, reason="测试计划")


@pytest.fixture()
def sleeps(monkeypatch):
    """把 time.sleep 打桩成记录器（monkeypatch 会在用例结束后自动还原）。"""
    recorded = []
    monkeypatch.setattr(time, "sleep", recorded.append)
    time.sleep(1.5)                       # 自检：桩确实生效
    assert recorded == [1.5]
    recorded.clear()
    return recorded


# --------------------------------------------------------------------------- #
# 不传 scheduler：必须与改造前一致
# --------------------------------------------------------------------------- #
def test_wait_for_without_scheduler_uses_fixed_interval(sleeps):
    machine = StateMachine(FakeMatcher())
    assert machine.wait_for(STATE_A, timeout=3.0, interval=1.0) is False
    assert sleeps == [1.0, 1.0, 1.0]


def test_wait_any_without_scheduler_uses_fixed_interval(sleeps):
    machine = StateMachine(FakeMatcher())
    assert machine.wait_any([STATE_A, STATE_B], timeout=2.0, interval=1.0) is None
    assert sleeps == [1.0, 1.0]


def test_wait_gone_without_scheduler_uses_fixed_interval(sleeps):
    matcher = FakeMatcher({"ts_a.png": make_match("ts_a.png")})
    machine = StateMachine(matcher)
    assert machine.wait_gone(STATE_A, timeout=2.0, interval=1.0) is False
    assert sleeps == [1.0, 1.0]


def test_default_interval_is_used_when_not_given(sleeps):
    machine = StateMachine(FakeMatcher())
    machine.wait_for(STATE_A, timeout=settings.DEFAULT_WAIT_INTERVAL)
    assert sleeps == [settings.DEFAULT_WAIT_INTERVAL]


# --------------------------------------------------------------------------- #
# 传了 scheduler：先盲等，再细粒度轮询
# --------------------------------------------------------------------------- #
def test_wait_for_blind_waits_once_then_polls(sleeps):
    scheduler = FakeScheduler(blind_wait=5.0, interval=1.0)
    machine = StateMachine(FakeMatcher())

    assert machine.wait_for(STATE_A, timeout=20.0, interval=3.0,
                            scheduler=scheduler) is False
    assert sleeps[0] == 5.0, "第一次应该先盲等"
    assert set(sleeps[1:]) == {1.0}, "盲等之后按 scheduler 给的间隔轮询"
    assert len(sleeps) == 16


def test_scheduler_receives_key_timeout_and_interval(sleeps):
    scheduler = FakeScheduler(blind_wait=0.0, interval=2.0)
    machine = StateMachine(FakeMatcher())
    machine.wait_for(STATE_A, timeout=1.0, interval=3.0, scheduler=scheduler)

    assert scheduler.calls == [(STATE_A.key, 1.0, 3.0)]


def test_explicit_timing_key_overrides_state_key(sleeps):
    scheduler = FakeScheduler()
    machine = StateMachine(FakeMatcher())
    machine.wait_for(STATE_A, timeout=1.0, interval=3.0,
                     scheduler=scheduler, timing_key="soul:battle")

    assert scheduler.calls[0][0] == "soul:battle"


def test_wait_any_uses_first_candidate_key_by_default(sleeps):
    scheduler = FakeScheduler()
    machine = StateMachine(FakeMatcher())
    machine.wait_any([STATE_A, STATE_B], timeout=1.0, interval=3.0, scheduler=scheduler)

    assert scheduler.calls[0][0] == STATE_A.key


def test_wait_gone_uses_scheduler(sleeps):
    matcher = FakeMatcher({"ts_a.png": make_match("ts_a.png")})
    scheduler = FakeScheduler(blind_wait=4.0, interval=1.0)
    machine = StateMachine(matcher)

    assert machine.wait_gone(STATE_A, timeout=10.0, interval=3.0,
                             scheduler=scheduler, timing_key="soul:gone") is False
    assert sleeps[0] == 4.0
    assert set(sleeps[1:]) == {1.0}
    assert scheduler.calls[0][0] == "soul:gone"


def test_expect_passes_scheduler_through(sleeps):
    from core.errors import StateTimeoutError

    scheduler = FakeScheduler(blind_wait=2.0, interval=1.0)
    machine = StateMachine(FakeMatcher())
    with pytest.raises(StateTimeoutError):
        machine.expect(STATE_A, timeout=5.0, interval=3.0,
                       scheduler=scheduler, timing_key="soul:expect")
    assert sleeps[0] == 2.0
    assert scheduler.calls[0][0] == "soul:expect"


def test_blind_wait_is_capped_by_timeout(sleeps):
    """盲等再长也不能超过本次等待的 timeout。"""
    scheduler = FakeScheduler(blind_wait=100.0, interval=1.0)
    machine = StateMachine(FakeMatcher())
    machine.wait_for(STATE_A, timeout=10.0, interval=3.0, scheduler=scheduler)

    assert sleeps == [10.0]


def test_hit_after_blind_wait_returns_immediately(sleeps):
    """盲等结束后第一次识图就命中：不该再多睡。"""
    matcher = FakeMatcher()
    scheduler = FakeScheduler(blind_wait=30.0, interval=1.0)
    machine = StateMachine(matcher)

    calls = {"n": 0}

    def match(filename, threshold=None, region=None):
        calls["n"] += 1
        if calls["n"] >= 2:                       # 盲等之后的那次识别命中
            return make_match(filename)
        return None

    matcher.match = match
    assert machine.wait_for(STATE_A, timeout=60.0, interval=3.0, scheduler=scheduler) is True
    assert sleeps == [30.0]


def test_already_active_state_never_blind_waits(sleeps):
    """状态已经在那儿了：先识图命中，盲等额度根本不会用掉。"""
    matcher = FakeMatcher({"ts_a.png": make_match("ts_a.png")})
    scheduler = FakeScheduler(blind_wait=30.0, interval=1.0)
    machine = StateMachine(matcher)

    assert machine.wait_for(STATE_A, timeout=60.0, scheduler=scheduler) is True
    assert sleeps == []


def test_zero_blind_wait_behaves_like_before(sleeps):
    """scheduler 判定不盲等时，interval 就是它给的值，其余行为不变。"""
    scheduler = FakeScheduler(blind_wait=0.0, interval=2.0)
    machine = StateMachine(FakeMatcher())
    machine.wait_for(STATE_A, timeout=4.0, interval=3.0, scheduler=scheduler)

    assert sleeps == [2.0, 2.0]
