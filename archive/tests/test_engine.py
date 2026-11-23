"""主流程引擎 + 事件总线 + BattleCycle 的联动测试。

用「假游戏」同时充当 machine（识别界面）与 controller（响应点击），
配合假时钟与临时 sqlite，完整跑通 挑战 -> 战斗 -> 结算 -> 回到挑战 的循环，
不需要 cv2 / 截图 / 真机。
"""
import logging

import pytest

from config import settings
from core.bus import EventBus
from core.errors import FlowAbortedError
from core.timing import CycleTimer
from flows.battle_cycle import BattleCycle
from flows.engine import FlowEngine
from flows.signals import (
    PREFIX_STATE_ENTERED,
    PREFIX_STATE_EXITED,
    TOPIC_ACTION_PERFORMED,
    TOPIC_FLOW_FINISHED,
    TOPIC_FLOW_STARTED,
    TOPIC_POLL_COMPLETED,
    TOPIC_ROUND_DONE,
    TOPIC_ROUND_FINISHED,
    TOPIC_ROUND_STARTED,
    TOPIC_STATE_DETECTED,
    TOPIC_STATE_TIMEOUT,
    TOPIC_STATE_UNKNOWN,
    TOPIC_TIMING_RECORDED,
    topic_for,
)
from states.base import REGISTRY, State
from states.machine import Detection
from storage.database import Database
from storage.duration_store import DurationStore
from vision.types import Box, Match

CHALLENGE = State(key="T_CHALLENGE", label="挑战", templates=("t_challenge.png",))
BATTLE_END = State(key="T_BATTLE_END", label="结算", templates=("t_end.png",))
OTHER = State(key="T_OTHER", label="其它界面", templates=("t_other.png",))
TEST_STATE_KEYS = ("T_CHALLENGE", "T_BATTLE_END", "T_OTHER")

# State.__post_init__ 会把自己登记进全局 REGISTRY，而 pytest 在收集阶段就 import
# 全部测试模块 —— 不摘掉会污染 test_states_registry / test_asset_manager_api 的断言。
for _key in TEST_STATE_KEYS:
    REGISTRY.pop(_key, None)

#: 断言事件骨架时要过滤掉的「噪声」事件
NOISE = (TOPIC_POLL_COMPLETED, TOPIC_STATE_DETECTED, TOPIC_STATE_UNKNOWN,
         TOPIC_TIMING_RECORDED)


class FakeClock:
    """假时钟：sleep 会推进时间，所以「盲等 40 秒」在测试里是瞬时的。"""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += max(0.0, seconds)

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_match(state: State, score: float = 0.9) -> Match:
    return Match(box=Box(0, 0, 10, 10), score=score, template=state.template)


class FakeGame:
    """假游戏：既当 StateMachine（识别界面）又当 GameController（响应点击）。

    剧本：
        挑战界面 --点挑战--> 战斗（battle_seconds 秒内什么都识别不到）
                --时间到--> 结算界面 --点结算 settle_clicks 次--> 挑战界面
    """

    def __init__(self, clock, battle_seconds: float = 45.0, screen=CHALLENGE,
                 settle_clicks: int = 1) -> None:
        self.clock = clock
        self.battle_seconds = battle_seconds
        self.screen = screen
        self.settle_clicks = settle_clicks
        self.clicks = []
        self._battle_until = None
        self._settle_hits = 0

    # ------------------------------------------------------------ machine
    def detect_first(self, candidates):
        if self._battle_until is not None:
            if self.clock() < self._battle_until:
                return None                     # 战斗中：什么都识别不到
            self._battle_until = None
            self.screen = BATTLE_END            # 战斗结束，出现结算画面
        if self.screen is None:
            return None
        for candidate in candidates:
            if candidate.key == self.screen.key:
                return Detection(state=candidate, match=make_match(candidate))
        return None

    # ---------------------------------------------------------- controller
    def click(self, target, **kwargs):
        template = getattr(target, "template", None)
        self.clicks.append(template)
        if template == CHALLENGE.template:
            self.screen = None
            self._battle_until = self.clock() + self.battle_seconds
        elif template == BATTLE_END.template:
            self._settle_hits += 1
            if self._settle_hits >= self.settle_clicks:
                self._settle_hits = 0
                self.screen = CHALLENGE
        return getattr(target, "center", None)


@pytest.fixture()
def clock():
    return FakeClock()


@pytest.fixture()
def store(tmp_path):
    return DurationStore(database=Database(tmp_path / "engine.db"))


def make_engine(clock, store, game, name="soul", adaptive=True, strict=True):
    bus = EventBus(strict=strict, history_size=2000)
    timer = CycleTimer(store=store, clock=clock, bus=bus, adaptive=adaptive)
    return FlowEngine(
        name, machine=game, controller=game, bus=bus, timer=timer,
        clock=clock, sleeper=clock.sleep,
    )


def make_cycle(engine, **kwargs):
    kwargs.setdefault("challenge", CHALLENGE)
    kwargs.setdefault("end_states", (BATTLE_END,))
    kwargs.setdefault("battle_interval", 3.0)
    kwargs.setdefault("challenge_timeout", 120.0)
    kwargs.setdefault("battle_timeout", 300.0)
    return BattleCycle(engine, **kwargs).attach()


def topics_of(engine):
    return [topic for _, topic, _ in engine.bus.history]


def skeleton_of(engine):
    """过滤掉高频事件后的事件骨架，便于断言流转顺序。"""
    return [topic for topic in topics_of(engine) if topic not in NOISE]


# --------------------------------------------------------------------------- #
# 事件流转
# --------------------------------------------------------------------------- #
def test_one_round_publishes_expected_event_sequence(clock, store):
    game = FakeGame(clock, battle_seconds=45.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine)

    assert engine.run_rounds(1, round_timeout=450.0) == 1

    assert skeleton_of(engine) == [
        TOPIC_FLOW_STARTED,
        TOPIC_ROUND_STARTED,
        topic_for(PREFIX_STATE_ENTERED, CHALLENGE),
        TOPIC_ACTION_PERFORMED,                       # 点挑战
        topic_for(PREFIX_STATE_EXITED, CHALLENGE),
        topic_for(PREFIX_STATE_ENTERED, BATTLE_END),
        TOPIC_ACTION_PERFORMED,                       # 点结算
        TOPIC_ROUND_DONE,
        TOPIC_ROUND_FINISHED,
        TOPIC_FLOW_FINISHED,
    ]


def test_one_round_clicks_challenge_then_settlement(clock, store):
    game = FakeGame(clock, battle_seconds=45.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine)
    engine.run_rounds(1, round_timeout=450.0)

    assert game.clicks == [CHALLENGE.template, BATTLE_END.template]


def test_extra_settle_clicks_are_used_until_challenge_returns(clock, store):
    """御魂的掉落界面：第一次点结算不回挑战界面，要补点。"""
    game = FakeGame(clock, battle_seconds=10.0, settle_clicks=3)
    engine = make_engine(clock, store, game)
    make_cycle(engine, extra_settle_clicks=4, retry_pause=2.0)
    engine.run_rounds(1, round_timeout=450.0)

    assert game.clicks == [CHALLENGE.template] + [BATTLE_END.template] * 3


def test_multiple_rounds_repeat_the_cycle(clock, store):
    game = FakeGame(clock, battle_seconds=20.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine)
    assert engine.run_rounds(3, round_timeout=450.0) == 3

    assert game.clicks == [CHALLENGE.template, BATTLE_END.template] * 3
    rounds = [event for _, topic, event in engine.bus.history
              if topic == TOPIC_ROUND_FINISHED]
    assert [event.index for event in rounds] == [1, 2, 3]
    assert all(event.duration > 0 for event in rounds)


def test_entered_event_fires_once_per_transition(clock, store):
    """同一个状态连续命中不该重复触发 entered（否则会被重复点击）。"""
    game = FakeGame(clock, battle_seconds=45.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine)
    engine.run_rounds(2, round_timeout=450.0)

    entered = [topic for topic in topics_of(engine)
               if topic == topic_for(PREFIX_STATE_ENTERED, CHALLENGE)]
    assert len(entered) == 2                      # 每轮一次


def test_unknown_state_is_broadcast(clock, store):
    game = FakeGame(clock, battle_seconds=45.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine)
    engine.run_rounds(1, round_timeout=450.0)

    unknown = [event for _, topic, event in engine.bus.history
               if topic == TOPIC_STATE_UNKNOWN]
    assert unknown, "战斗中连续识别不到状态时应广播 state.unknown"
    assert unknown[0].unknown_streak == settings.UNKNOWN_POLL_LIMIT


def test_flow_finished_event_carries_totals(clock, store):
    game = FakeGame(clock, battle_seconds=20.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine)
    engine.run_rounds(2, round_timeout=450.0)

    event = [event for _, topic, event in engine.bus.history
             if topic == TOPIC_FLOW_FINISHED][-1]
    assert event.name == "soul"
    assert event.rounds == 2
    assert event.aborted is False
    # 总耗时应等于逐轮记下来的计时样本之和（引擎自己记的账要对得上）
    assert event.total_seconds == pytest.approx(sum(store.samples("soul:round")), abs=0.5)
    assert event.total_seconds >= 40.0


# --------------------------------------------------------------------------- #
# 计时：每一轮 / 每一场都被记住
# --------------------------------------------------------------------------- #
def test_round_and_battle_durations_are_recorded(clock, store):
    game = FakeGame(clock, battle_seconds=45.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine)
    engine.run_rounds(2, round_timeout=450.0)

    assert store.samples("soul:round") == [pytest.approx(45.0)] * 2
    assert store.samples("soul:battle") == [pytest.approx(45.0)] * 2
    # 回到挑战界面的耗时也被记住（用于下一轮少截屏）
    assert len(store.samples("soul:challenge")) == 2


def test_timing_events_are_broadcast(clock, store):
    game = FakeGame(clock, battle_seconds=20.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine)
    engine.run_rounds(1, round_timeout=450.0)

    samples = [event for _, topic, event in engine.bus.history
               if topic == TOPIC_TIMING_RECORDED]
    assert {sample.key for sample in samples} >= {"soul:round", "soul:battle"}


def test_summary_reports_rounds_and_probe_cost(clock, store):
    game = FakeGame(clock, battle_seconds=20.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine)
    engine.run_rounds(2, round_timeout=450.0)

    text = engine.summary()
    assert "soul 总账：2 轮" in text
    assert "soul:battle" in text
    assert "识图" in text
    assert engine.probe_count > 0


# --------------------------------------------------------------------------- #
# 自适应等待：跑得越多，截图越少
# --------------------------------------------------------------------------- #
def test_probe_count_drops_once_timing_converges(clock, store):
    """收敛之后先盲等再细轮询，同样的战斗时长应该显著减少识图次数。"""
    game = FakeGame(clock, battle_seconds=45.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine)

    per_round = []
    engine.on(TOPIC_ROUND_FINISHED,
              lambda event: per_round.append(engine.probe_count), priority=90)
    engine.run_rounds(settings.TIMING_WARMUP_SAMPLES + 3, round_timeout=450.0)

    counts = [per_round[0]] + [b - a for a, b in zip(per_round, per_round[1:])]
    first, last = counts[0], counts[-1]
    assert last < first, "收敛后识图次数应下降，实际: {}".format(counts)
    # 战斗时长没变，轮次耗时不该因为盲等而变长
    assert engine.timer.estimate("soul:battle").p50 == pytest.approx(45.0, abs=2.0)


def test_blind_wait_is_actually_used(clock, store):
    game = FakeGame(clock, battle_seconds=45.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine)
    engine.run_rounds(settings.TIMING_WARMUP_SAMPLES + 2, round_timeout=450.0)

    # 收敛后应出现一次明显的长 sleep（盲等），远大于 BATTLE_INTERVAL
    assert max(clock.slept) > 3.0 * settings.TIMING_WARMUP_SAMPLES * 0.5
    assert max(clock.slept) <= settings.TIMING_MAX_BLIND_WAIT


def test_disabling_adaptive_wait_keeps_fixed_polling(clock, store):
    game = FakeGame(clock, battle_seconds=45.0)
    engine = make_engine(clock, store, game, adaptive=False)
    make_cycle(engine)
    engine.run_rounds(settings.TIMING_WARMUP_SAMPLES + 3, round_timeout=450.0)

    # 关掉自适应后不该出现盲等：每次 sleep 都不超过探测间隔
    assert max(clock.slept) <= 3.0
    assert engine.timer.adaptive is False


# --------------------------------------------------------------------------- #
# 超时与中止（与改造前的行为对齐）
# --------------------------------------------------------------------------- #
def test_missing_challenge_aborts_with_legacy_message(clock, store):
    game = FakeGame(clock, screen=OTHER)            # 永远看不到挑战按钮
    engine = make_engine(clock, store, game)
    make_cycle(engine, challenge_timeout=10.0)

    with pytest.raises(FlowAbortedError) as exc_info:
        engine.run_rounds(5, round_timeout=450.0)
    assert "未匹配到挑战按钮" in str(exc_info.value)
    assert game.clicks == []

    finished = [event for _, topic, event in engine.bus.history
                if topic == TOPIC_FLOW_FINISHED][-1]
    assert finished.aborted is True


def test_round_timeout_without_challenge_also_aborts(clock, store):
    """引擎层面的整轮超时兜底：同样按「挑战按钮没出现」处理。"""
    game = FakeGame(clock, screen=OTHER)
    engine = make_engine(clock, store, game)
    make_cycle(engine, challenge_timeout=None)      # 只靠引擎的 round_timeout

    with pytest.raises(FlowAbortedError):
        engine.run_rounds(1, round_timeout=15.0)
    assert any(topic == TOPIC_STATE_TIMEOUT for topic in topics_of(engine))


def test_battle_timeout_continues_next_round(clock, store, caplog):
    """战斗等不到结算：告警一次并进入下一轮，不中止流程（旧行为）。"""
    game = FakeGame(clock, battle_seconds=60.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine, battle_timeout=20.0, challenge_timeout=None)

    with caplog.at_level(logging.WARNING):
        assert engine.run_rounds(2, round_timeout=450.0) == 2
    assert "未识别到战斗结算，按超时继续下一轮" in caplog.text
    # 超时的战斗不入库，避免把最小值顶高；整轮仍然算跑完了一轮
    assert store.samples("soul:battle") == []
    assert len(store.samples("soul:round")) == 2


def test_stale_settlement_is_dismissed_then_round_continues(clock, store):
    """开局就停在结算画面：先点掉它，再正常打完这一轮（旧 _dismiss_settlement）。"""
    game = FakeGame(clock, battle_seconds=10.0, screen=BATTLE_END)
    engine = make_engine(clock, store, game)
    make_cycle(engine)

    assert engine.run_rounds(1, round_timeout=450.0) == 1
    assert game.clicks == [BATTLE_END.template, CHALLENGE.template, BATTLE_END.template]
    battle = store.samples("soul:battle")
    assert len(battle) == 1
    # 战斗实际 10 秒、探测间隔 3 秒，所以测出来落在 10~13 秒之间
    assert 10.0 <= battle[0] <= 13.0


def test_timed_out_round_is_not_recorded_as_sample(clock, store):
    game = FakeGame(clock, screen=OTHER)
    engine = make_engine(clock, store, game)
    make_cycle(engine, challenge_timeout=None)

    with pytest.raises(FlowAbortedError):
        engine.run_rounds(1, round_timeout=15.0)
    assert store.samples("soul:round") == []


def test_stop_ends_rounds_gracefully(clock, store):
    game = FakeGame(clock, battle_seconds=5.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine)

    def stop_after_two(event):
        if event.index == 2:
            engine.stop("够了")

    engine.on(TOPIC_ROUND_STARTED, stop_after_two)
    assert engine.run_rounds(10, round_timeout=450.0) == 1
    finished = [event for _, topic, event in engine.bus.history
                if topic == TOPIC_FLOW_FINISHED][-1]
    assert finished.aborted is False


def test_keyboard_interrupt_is_reported_and_reraised(clock, store):
    game = FakeGame(clock, battle_seconds=5.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine)

    def interrupt(event):
        raise KeyboardInterrupt()

    engine.on(TOPIC_ROUND_STARTED, interrupt)
    with pytest.raises(KeyboardInterrupt):
        engine.run_rounds(3, round_timeout=450.0)
    finished = [event for _, topic, event in engine.bus.history
                if topic == TOPIC_FLOW_FINISHED][-1]
    assert finished.aborted is True
    assert finished.reason == "用户中断"


def test_infinite_rounds_until_stopped(clock, store):
    game = FakeGame(clock, battle_seconds=5.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine)
    engine.on(TOPIC_ROUND_FINISHED,
              lambda event: engine.stop() if event.index >= 4 else None)
    assert engine.run_rounds(None, round_timeout=450.0) == 4


# --------------------------------------------------------------------------- #
# 引擎本身的契约
# --------------------------------------------------------------------------- #
def test_run_rounds_requires_watched_states(clock, store):
    engine = make_engine(clock, store, FakeGame(clock))
    with pytest.raises(FlowAbortedError):
        engine.run_rounds(1)


def test_click_without_target_raises(clock, store):
    engine = make_engine(clock, store, FakeGame(clock))
    with pytest.raises(FlowAbortedError):
        engine.click(None, detail="测试")


def test_click_accepts_detection_and_publishes_action(clock, store):
    game = FakeGame(clock)
    engine = make_engine(clock, store, game)
    engine.watch(CHALLENGE)
    detection = engine.observe()
    engine.click(detection, detail="点它")

    assert game.clicks == [CHALLENGE.template]
    event = [event for _, topic, event in engine.bus.history
             if topic == TOPIC_ACTION_PERFORMED][-1]
    assert event.state_key == CHALLENGE.key
    assert event.detail == "点它"


def test_peek_does_not_publish(clock, store):
    game = FakeGame(clock)
    engine = make_engine(clock, store, game)
    engine.watch(CHALLENGE)

    assert engine.peek((CHALLENGE,)) is not None
    assert topics_of(engine) == []
    assert engine.current is None


def test_reset_current_makes_next_hit_fire_entered_again(clock, store):
    game = FakeGame(clock)
    engine = make_engine(clock, store, game)
    engine.watch(CHALLENGE)
    seen = []
    engine.on(topic_for(PREFIX_STATE_ENTERED, CHALLENGE), seen.append)

    engine.observe()
    engine.observe()                    # 同一状态持续命中，不再触发 entered
    assert len(seen) == 1
    engine.reset_current()
    engine.observe()
    assert len(seen) == 2


def test_unwatch_removes_state(clock, store):
    engine = make_engine(clock, store, FakeGame(clock))
    engine.watch(CHALLENGE, BATTLE_END)
    engine.unwatch(CHALLENGE)
    assert engine.watched == (BATTLE_END,)


def test_wait_for_returns_detection_and_can_publish(clock, store):
    game = FakeGame(clock)
    engine = make_engine(clock, store, game)
    engine.watch(CHALLENGE)

    assert engine.wait_for((CHALLENGE,), timeout=5.0) is not None
    assert topics_of(engine) == []                    # 默认不广播

    engine.wait_for((CHALLENGE,), timeout=5.0, publish=True)
    assert TOPIC_STATE_DETECTED in topics_of(engine)


def test_wait_for_timeout_returns_none(clock, store):
    game = FakeGame(clock, screen=OTHER)
    engine = make_engine(clock, store, game)
    engine.watch(CHALLENGE)
    assert engine.wait_for((CHALLENGE,), timeout=3.0, interval=1.0) is None


def test_subscriber_exception_does_not_break_the_flow(clock, store):
    """非 strict 总线下，一个写坏的订阅方不该把挂机流程带崩。"""
    game = FakeGame(clock, battle_seconds=5.0)
    engine = make_engine(clock, store, game, strict=False)
    make_cycle(engine)

    def boom(event):
        raise RuntimeError("订阅方 bug")

    engine.on(topic_for(PREFIX_STATE_ENTERED, CHALLENGE), boom)
    assert engine.run_rounds(1, round_timeout=450.0) == 1
    assert engine.bus.errors >= 1


# --------------------------------------------------------------------------- #
# 回归：评审发现的三个缺陷
# --------------------------------------------------------------------------- #
def test_battle_timing_excludes_settlement_overhead(clock, store):
    """battle 样本只能覆盖「点挑战 -> 出现结算」。

    要是把点结算 / 补点 / 等回挑战界面的时间也算进去，盲等就会逐轮自我放大：
    等得越久 -> 样本越大 -> 下次盲等更久，正好是 timing 模块要防的不收敛。
    """
    battle = 45.0
    game = FakeGame(clock, battle_seconds=battle, settle_clicks=3)
    engine = make_engine(clock, store, game)
    make_cycle(engine, extra_settle_clicks=4, retry_pause=2.0)

    rounds = settings.TIMING_WARMUP_SAMPLES + 4
    assert engine.run_rounds(rounds, round_timeout=450.0) == rounds

    samples = store.samples("soul:battle")
    assert len(samples) == rounds
    # 结算 + 补点实际要花 16 秒左右，绝不能被算进 battle 样本
    assert max(samples) <= battle + 4.0
    assert engine.timer.estimate("soul:battle").p50 == pytest.approx(battle, abs=4.0)
    # 收敛后的盲等不该超过战斗本身
    assert engine.timer.plan("soul:battle", timeout=300.0, interval=3.0).blind_wait <= battle
    # 结算段的耗时另记在 challenge key 上，没有丢
    assert max(store.samples("soul:challenge")) > 10.0


def test_challenge_hit_on_timeout_tick_wins_over_abort(clock, store):
    """超时判定不能压过同一拍的命中。

    poll.completed 比 state.entered 先发，如果这一拍既越过了 challenge_timeout
    又正好识别到挑战按钮，正确行为是「命中优先」照常开战；
    否则会变成先点挑战开打、再抛「未匹配到挑战按钮」退出，把战斗丢着没人收尾。
    """
    class LateGame(FakeGame):
        def detect_first(self, candidates):
            if self.clock() < 12.0:                 # 前 12 秒什么都识别不到
                return None
            return FakeGame.detect_first(self, candidates)

    game = LateGame(clock, battle_seconds=5.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine, challenge_timeout=10.0)

    assert engine.run_rounds(1, round_timeout=450.0) == 1
    assert game.clicks[0] == CHALLENGE.template
    assert store.samples("soul:battle")              # 这一场正常打完并记账


def test_challenge_poll_interval_is_restored_each_round(clock, store):
    """挑战阶段的探测间隔不能被上一轮的战斗阶段带跑（3.0s 粘滞 -> 应变回 2.0s）。"""
    game = FakeGame(clock, battle_seconds=10.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine, battle_interval=3.0)

    seen = []
    engine.on(TOPIC_ROUND_STARTED,
              lambda event: seen.append(engine.poll_interval), priority=50)
    engine.run_rounds(3, round_timeout=450.0)

    assert seen == [settings.DEFAULT_WAIT_INTERVAL] * 3


def test_elapsed_round_works_when_clock_starts_at_zero(clock, store):
    """时钟从 0 起步时 elapsed_round 也必须准确（起始时刻的哨兵不能用 0.0）。"""
    game = FakeGame(clock, battle_seconds=30.0)
    engine = make_engine(clock, store, game)
    engine.watch(CHALLENGE, BATTLE_END)

    seen = []
    engine.on(TOPIC_POLL_COMPLETED,
              lambda event: seen.append((clock(), engine.elapsed_round())))
    engine.run_rounds(1, round_timeout=450.0)

    assert seen[0] == (0.0, 0.0)                 # 第一轮从 t=0 开始
    assert max(elapsed for _, elapsed in seen) >= 30.0


# --------------------------------------------------------------------------- #
# 窗口激活失败：点击未送达时要重试，而不是崩掉或空等
# --------------------------------------------------------------------------- #
class FlakyGame(FakeGame):
    """前 fail_times 次点击「没送达」（模拟窗口激活失败被 actions/mouse.py 跳过）。"""

    def __init__(self, clock, fail_times=1, **kwargs):
        super().__init__(clock, **kwargs)
        self.fail_times = fail_times
        self.attempts = 0

    def click(self, target, **kwargs):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            return None                       # 未送达
        return FakeGame.click(self, target, **kwargs)


def test_undelivered_click_does_not_publish_action_event(clock, store):
    """action.performed 只描述真的发生过的动作，没送达就不能广播。"""
    game = FlakyGame(clock, fail_times=99)
    engine = make_engine(clock, store, game)
    engine.watch(CHALLENGE)
    detection = engine.observe()

    assert engine.click(detection, detail="点它") is None
    assert [topic for topic in topics_of(engine) if topic == TOPIC_ACTION_PERFORMED] == []


def test_battle_cycle_retries_undelivered_challenge_click(clock, store):
    """点挑战没送达时不能推进到战斗阶段，否则会白等一场没开打的战斗。"""
    game = FlakyGame(clock, fail_times=1, battle_seconds=20.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine)

    assert engine.run_rounds(1, round_timeout=450.0) == 1
    # 第一次没送达 -> reset_current -> 下一拍重新 entered -> 再点，这次成功
    assert game.clicks == [CHALLENGE.template, BATTLE_END.template]
    # attempts 含那次未送达的调用：1 次失败 + 挑战 + 结算；clicks 只记真的点下去的
    assert game.attempts == 3
    # 没有傻等 BATTLE_TIMEOUT：整轮耗时应接近战斗本身
    assert store.samples("soul:round")[0] < 60.0


def test_battle_cycle_retries_undelivered_settlement_click(clock, store):
    """点结算没送达时不能把这一轮丢掉，下一拍要重新处理结算。"""
    class LateSettleGame(FakeGame):
        """第一次点击（挑战）成功，第二次（结算）没送达，之后都成功。"""

        def __init__(self, clock, **kwargs):
            super().__init__(clock, **kwargs)
            self.attempts = 0

        def click(self, target, **kwargs):
            self.attempts += 1
            if self.attempts == 2:
                return None
            return FakeGame.click(self, target, **kwargs)

    game = LateSettleGame(clock, battle_seconds=10.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine)

    assert engine.run_rounds(1, round_timeout=450.0) == 1
    assert game.clicks == [CHALLENGE.template, BATTLE_END.template]
    assert store.samples("soul:battle"), "这一轮必须正常收尾并记账"


def test_persistent_activation_error_aborts_flow_cleanly(clock, store):
    """连续激活失败到上限时抛 WindowActivationError（YysError），不是裸 traceback。"""
    from core.errors import WindowActivationError, YysError

    class DeadGame(FakeGame):
        def click(self, target, **kwargs):
            raise WindowActivationError("连续 10 次无法激活目标窗口，中止流程。")

    game = DeadGame(clock, battle_seconds=5.0)
    engine = make_engine(clock, store, game)
    make_cycle(engine)

    with pytest.raises(WindowActivationError) as exc_info:
        engine.run_rounds(3, round_timeout=450.0)
    assert isinstance(exc_info.value, YysError)

    finished = [event for _, topic, event in engine.bus.history
                if topic == TOPIC_FLOW_FINISHED][-1]
    assert finished.aborted is True
    assert "无法激活" in finished.reason
