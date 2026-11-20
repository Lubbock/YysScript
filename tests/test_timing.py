"""循环计时与自适应等待测试（core/timing.py）。

全部用假时钟 + 临时 sqlite，不需要 cv2 / 截图 / 游戏。
重点验证用户关心的那条：「等待时间过长导致最小时间一直不被正确收敛」必须能自愈。
"""
import pytest

from config import settings
from core.bus import EventBus
from core.timing import (
    CycleTimer,
    Estimate,
    FixedScheduler,
    TimingSample,
    WaitPlan,
    _percentile,
    _probe_key_of,
)
from storage.database import Database
from storage.duration_store import DurationStore

KEY = "soul:battle"


class FakeClock:
    """假时钟：只有 advance() 会让时间前进。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock():
    return FakeClock()


@pytest.fixture()
def store(tmp_path):
    return DurationStore(database=Database(tmp_path / "timing.db"))


@pytest.fixture()
def timer(store, clock):
    return CycleTimer(store=store, clock=clock)


def record(timer, clock, seconds, key=KEY):
    """跑一次「耗时 seconds 秒」的阶段并提交样本。"""
    cycle = timer.begin(key)
    clock.advance(seconds)
    return timer.commit(cycle)


def warm_up(timer, clock, seconds=45.0, count=None, key=KEY):
    """攒够收敛所需的样本。"""
    count = settings.TIMING_WARMUP_SAMPLES if count is None else count
    for _ in range(count):
        record(timer, clock, seconds, key)


# --------------------------------------------------------------------------- #
# 未收敛：必须与改造前的行为完全一致
# --------------------------------------------------------------------------- #
def test_no_samples_falls_back_to_legacy_polling(timer):
    plan = timer.plan(KEY, timeout=300.0, interval=3.0)
    assert plan.blind_wait == 0.0
    assert plan.interval == 3.0
    assert plan.estimate is not None and plan.estimate.samples == 0


def test_warmup_still_uses_caller_interval(timer, clock):
    """样本不足（< TIMING_WARMUP_SAMPLES）时不盲等，仍按调用方给的间隔截图。"""
    warm_up(timer, clock, count=settings.TIMING_WARMUP_SAMPLES - 1)
    plan = timer.plan(KEY, timeout=300.0, interval=3.0)
    assert plan.blind_wait == 0.0
    assert plan.interval == 3.0
    assert timer.estimate(KEY).converged is False


def test_default_interval_used_when_caller_gives_none(timer):
    plan = timer.plan(KEY, timeout=300.0)
    assert plan.interval == settings.DEFAULT_WAIT_INTERVAL


# --------------------------------------------------------------------------- #
# 收敛后：先盲等，再细粒度轮询
# --------------------------------------------------------------------------- #
def test_converged_plan_blind_waits_until_p10(timer, clock):
    warm_up(timer, clock, seconds=45.0)
    estimate = timer.estimate(KEY)
    assert estimate.converged is True
    assert estimate.p10 == pytest.approx(45.0)

    plan = timer.plan(KEY, timeout=300.0, interval=3.0)
    assert plan.blind_wait == pytest.approx(45.0 * settings.TIMING_SAFETY)
    assert plan.interval == settings.TIMING_FINE_INTERVAL


def test_probe_cost_is_subtracted_from_blind_wait(timer, clock):
    """识图本身要花时间，盲等就该少等这么多。"""
    warm_up(timer, clock, seconds=45.0)
    timer.record_probe("soul:probe", 0.6)
    plan = timer.plan(KEY, timeout=300.0, interval=3.0)
    assert plan.blind_wait == pytest.approx(45.0 * settings.TIMING_SAFETY - 0.6)


def test_probe_key_is_derived_from_flow_prefix(timer, clock):
    warm_up(timer, clock, seconds=45.0)
    timer.record_probe(_probe_key_of("soul:battle"), 5.0)
    # 显式传 probe_key 与按前缀推导应当拿到同一个成本
    assert timer.plan(KEY, 300.0, 3.0).blind_wait == pytest.approx(
        timer.plan(KEY, 300.0, 3.0, probe_key="soul:probe").blind_wait)
    assert _probe_key_of("soul:round") == "soul:probe"


def test_blind_wait_is_capped_by_max_setting(timer, clock):
    """估计再离谱，盲等也不会超过硬上限。"""
    warm_up(timer, clock, seconds=1000.0)
    plan = timer.plan(KEY, timeout=5000.0, interval=3.0)
    assert plan.blind_wait == pytest.approx(settings.TIMING_MAX_BLIND_WAIT)


def test_blind_wait_leaves_room_for_polling(timer, clock):
    """盲等不能吃掉整个 timeout，至少要留 TIMING_FINE_WINDOW 秒轮询。"""
    warm_up(timer, clock, seconds=1000.0)
    timeout = settings.TIMING_FINE_WINDOW + 20.0
    plan = timer.plan(KEY, timeout=timeout, interval=3.0)
    assert plan.blind_wait == pytest.approx(20.0)


def test_very_short_timeout_never_blind_waits(timer, clock):
    warm_up(timer, clock, seconds=45.0)
    plan = timer.plan(KEY, timeout=settings.TIMING_FINE_WINDOW - 1.0, interval=2.0)
    assert plan.blind_wait == 0.0
    assert plan.interval == settings.TIMING_FINE_INTERVAL


def test_adaptive_can_be_disabled(timer, clock, store):
    warm_up(timer, clock, seconds=45.0)
    fixed = CycleTimer(store=store, clock=clock, adaptive=False)
    plan = fixed.plan(KEY, timeout=300.0, interval=3.0)
    assert plan.blind_wait == 0.0
    assert plan.interval == 3.0


def test_fixed_scheduler_never_blind_waits():
    plan = FixedScheduler().plan("any:key", timeout=300.0, interval=2.5)
    assert isinstance(plan, WaitPlan)
    assert plan.blind_wait == 0.0
    assert plan.interval == 2.5


# --------------------------------------------------------------------------- #
# 异常样本：不收敛问题的核心
# --------------------------------------------------------------------------- #
def test_outlier_is_excluded_from_statistics(timer, clock):
    """一次超长等待不该把最小值 / p10 顶高。"""
    warm_up(timer, clock, seconds=45.0)
    record(timer, clock, 400.0)

    estimate = timer.estimate(KEY)
    assert estimate.minimum == pytest.approx(45.0)
    assert estimate.p10 == pytest.approx(45.0)
    assert estimate.usable == settings.TIMING_WARMUP_SAMPLES
    assert estimate.overruns == 1
    # 有异常在身时不算收敛，退回探测频率，避免用被污染的分位数去盲等
    assert estimate.converged is False
    assert timer.plan(KEY, 300.0, 3.0).blind_wait == 0.0


def test_outlier_is_still_persisted_for_audit(timer, clock, store):
    warm_up(timer, clock, seconds=45.0)
    record(timer, clock, 400.0)
    assert store.samples(KEY)[-1] == pytest.approx(400.0)
    assert len(store.samples(KEY)) == settings.TIMING_WARMUP_SAMPLES + 1


def test_single_outlier_recovers_on_next_normal_sample(timer, clock):
    warm_up(timer, clock, seconds=45.0)
    record(timer, clock, 400.0)
    assert timer.estimate(KEY).overruns == 1
    record(timer, clock, 46.0)
    estimate = timer.estimate(KEY)
    assert estimate.overruns == 0
    assert estimate.converged is True


def test_consecutive_overruns_drop_history_and_rewarm(timer, clock):
    """连续超限 -> 丢掉历史窗口 -> 回到探测频率重新收敛（不会被永久顶高）。"""
    warm_up(timer, clock, seconds=45.0)
    assert timer.plan(KEY, 300.0, 3.0).blind_wait > 0

    for _ in range(settings.TIMING_OVERRUN_RESET):
        record(timer, clock, 400.0)

    estimate = timer.estimate(KEY)
    assert estimate.samples == 0
    assert estimate.converged is False
    assert timer.plan(KEY, 300.0, 3.0).blind_wait == 0.0
    assert timer.plan(KEY, 300.0, 3.0).interval == 3.0


def test_after_reset_reconverges_with_conservative_safety(timer, clock):
    """回退之后重新攒够样本，先用更保守的安全系数。"""
    warm_up(timer, clock, seconds=45.0)
    for _ in range(settings.TIMING_OVERRUN_RESET):
        record(timer, clock, 400.0)

    warm_up(timer, clock, seconds=44.0)
    plan = timer.plan(KEY, timeout=300.0, interval=3.0)
    assert plan.blind_wait == pytest.approx(44.0 * settings.TIMING_RESET_SAFETY)
    assert plan.interval == settings.TIMING_FINE_INTERVAL


def test_conservative_safety_recovers_after_enough_clean_samples(timer, clock):
    warm_up(timer, clock, seconds=45.0)
    for _ in range(settings.TIMING_OVERRUN_RESET):
        record(timer, clock, 400.0)
    warm_up(timer, clock, seconds=44.0, count=settings.TIMING_RESET_RECOVER_SAMPLES)

    plan = timer.plan(KEY, timeout=300.0, interval=3.0)
    assert plan.blind_wait == pytest.approx(44.0 * settings.TIMING_SAFETY)


def test_outliers_do_not_push_blind_wait_up_over_time(timer, clock):
    """反复出现异常样本时，盲等时长必须保持收敛而不是单调上涨。"""
    warm_up(timer, clock, seconds=45.0)
    blind_before = timer.plan(KEY, 300.0, 3.0).blind_wait

    for _ in range(6):
        record(timer, clock, 600.0)          # 一直超时
        record(timer, clock, 45.0)           # 偶尔正常一轮

    blind_after = timer.plan(KEY, 300.0, 3.0).blind_wait
    assert blind_after <= blind_before + 1.0


def test_tiny_baseline_does_not_flag_real_sample_as_outlier(timer, clock):
    """真机复现：soul:challenge 的历史样本是 0.045 秒（点完结算瞬间就回到挑战界面）。

    纯相对判据（> p50 × 2.5）此时阈值只有 0.11 秒，于是真实的 20.5 秒
    （补点两次才回去）被判成异常剔除，窗口里永远只剩极小值 ->
    usable 永远到不了 warm-up 门槛 -> 永久不收敛。
    """
    record(timer, clock, 0.045)
    record(timer, clock, 20.5)

    estimate = timer.estimate(KEY)
    assert estimate.overruns == 0, "没有基线就不该判异常"
    assert estimate.usable == 2
    assert estimate.p50 == pytest.approx((0.045 + 20.5) / 2)


def test_no_outlier_policing_before_warmup(timer, clock):
    """warm-up 阶段一律放行：先攒够样本，才谈得上什么叫异常。"""
    for value in (0.04, 600.0, 0.03, 900.0):
        record(timer, clock, value)
    assert timer.estimate(KEY).overruns == 0
    assert timer.estimate(KEY).samples == 4


def test_absolute_floor_protects_short_phases(timer, clock):
    """收敛之后同样要有绝对下限：5 个 0.04 秒的样本不该让 20 秒变成异常。"""
    for _ in range(settings.TIMING_WARMUP_SAMPLES):
        record(timer, clock, 0.04)
    assert timer.estimate(KEY).converged is True

    record(timer, clock, 20.0)
    estimate = timer.estimate(KEY)
    assert estimate.overruns == 0
    assert estimate.usable == settings.TIMING_WARMUP_SAMPLES + 1


def test_bimodal_phase_still_converges(timer, clock):
    """双峰阶段（要么瞬间返回、要么补点花 20 秒）必须能收敛，不能永久卡住。"""
    for _ in range(settings.TIMING_WARMUP_SAMPLES):
        record(timer, clock, 0.04)
        record(timer, clock, 20.0)

    estimate = timer.estimate(KEY)
    assert estimate.converged is True
    assert estimate.overruns == 0
    # p10 落在「瞬间返回」那一侧，所以盲等接近 0 —— 对双峰阶段这是正确行为
    assert timer.plan(KEY, 300.0, 2.0).blind_wait < 1.0


def test_relative_rule_still_dominates_for_long_phases(timer, clock):
    """绝对下限不能削弱主场景：战斗几十秒时，200 秒仍然算异常。"""
    warm_up(timer, clock, seconds=60.0)
    record(timer, clock, 200.0)

    estimate = timer.estimate(KEY)
    assert estimate.overruns == 1
    assert estimate.minimum == pytest.approx(60.0)
    assert estimate.usable == settings.TIMING_WARMUP_SAMPLES


def test_outlier_limit_takes_the_larger_of_both_rules():
    from core.timing import _outlier_limit

    # 长耗时阶段：相对倍数占主导
    assert _outlier_limit(60.0) == pytest.approx(60.0 * settings.TIMING_OUTLIER_FACTOR)
    # 极短耗时阶段：绝对下限兜底，阈值不会退化到近 0
    assert _outlier_limit(0.04) == pytest.approx(0.04 + settings.TIMING_OUTLIER_FLOOR)


def test_discard_does_not_write_sample(timer, clock, store):
    cycle = timer.begin(KEY)
    clock.advance(120.0)
    timer.discard(cycle, "本轮超时")
    assert store.samples(KEY) == []
    assert timer.estimate(KEY).samples == 0


def test_context_manager_commits_on_success(timer, clock, store):
    with timer.cycle(KEY):
        clock.advance(30.0)
    assert store.samples(KEY) == [pytest.approx(30.0)]


def test_context_manager_discards_on_exception(timer, clock, store):
    with pytest.raises(RuntimeError):
        with timer.cycle(KEY):
            clock.advance(30.0)
            raise RuntimeError("炸了")
    assert store.samples(KEY) == []


def test_double_commit_is_ignored(timer, clock, store):
    cycle = timer.begin(KEY)
    clock.advance(30.0)
    first = timer.commit(cycle)
    second = timer.commit(cycle)
    assert first == pytest.approx(30.0)
    assert second == pytest.approx(30.0)
    assert len(store.samples(KEY)) == 1


def test_commit_can_take_explicit_seconds(timer, clock, store):
    cycle = timer.begin(KEY)
    timer.commit(cycle, seconds=12.5)
    assert store.samples(KEY) == [pytest.approx(12.5)]


# --------------------------------------------------------------------------- #
# 持久化与窗口
# --------------------------------------------------------------------------- #
def test_samples_are_reloaded_from_store(store, clock):
    """跨进程复用：上次跑出来的样本这次直接能用，不必重新 warm-up。"""
    first = CycleTimer(store=store, clock=clock)
    warm_up(first, clock, seconds=45.0)

    second = CycleTimer(store=store, clock=clock)
    estimate = second.estimate(KEY)
    assert estimate.usable == settings.TIMING_WARMUP_SAMPLES
    assert estimate.converged is True
    assert second.plan(KEY, 300.0, 3.0).blind_wait > 0


def test_window_is_trimmed(store, clock):
    timer = CycleTimer(store=store, clock=clock, window=3)
    for value in (10.0, 20.0, 30.0, 40.0, 50.0):
        record(timer, clock, value)
    estimate = timer.estimate(KEY)
    assert estimate.samples == 3
    assert estimate.minimum == pytest.approx(30.0)
    assert len(store.samples(KEY)) == 5      # 库里仍保留全部样本


def test_loaded_window_is_limited_to_recent_samples(store, clock):
    for value in range(1, 31):
        store.record(KEY, float(value))
    timer = CycleTimer(store=store, clock=clock)   # window 默认 20
    assert timer.estimate(KEY).samples == settings.TIMING_WINDOW


def test_broken_store_does_not_break_timing(tmp_path, clock):
    """数据库读不出来时降级成空窗口，流程照跑。"""
    class BrokenStore:
        def samples(self, key):
            raise OSError("磁盘坏了")

        def record(self, key, seconds):
            raise OSError("磁盘坏了")

    timer = CycleTimer(store=BrokenStore(), clock=clock)
    assert timer.estimate(KEY).samples == 0
    assert timer.plan(KEY, 300.0, 3.0).blind_wait == 0.0


# --------------------------------------------------------------------------- #
# 识图成本
# --------------------------------------------------------------------------- #
def test_probe_cost_is_sliding_average(timer):
    for _ in range(settings.TIMING_PROBE_WINDOW):
        timer.record_probe("soul:probe", 0.5)
    assert timer.probe_cost("soul:probe") == pytest.approx(0.5)
    for _ in range(settings.TIMING_PROBE_WINDOW):
        timer.record_probe("soul:probe", 1.5)
    assert timer.probe_cost("soul:probe") == pytest.approx(1.5)


def test_probe_cost_unknown_key_is_zero(timer):
    assert timer.probe_cost("nope:probe") == 0.0
    assert timer.probe_cost(None) == 0.0


def test_negative_probe_cost_is_ignored(timer):
    timer.record_probe("soul:probe", -1.0)
    assert timer.probe_cost("soul:probe") == 0.0


# --------------------------------------------------------------------------- #
# 事件广播与汇总
# --------------------------------------------------------------------------- #
def test_commit_publishes_timing_event(store, clock):
    bus = EventBus(strict=True)
    timer = CycleTimer(store=store, clock=clock, bus=bus)
    seen = []
    bus.subscribe("timing.recorded", seen.append)

    record(timer, clock, 30.0)
    assert len(seen) == 1
    sample = seen[0]
    assert isinstance(sample, TimingSample)
    assert sample.key == KEY
    assert sample.seconds == pytest.approx(30.0)
    assert sample.estimate.samples == 1


def test_summary_lists_all_timing_keys(timer, clock):
    record(timer, clock, 30.0, "soul:round")
    record(timer, clock, 20.0, "soul:battle")
    record(timer, clock, 5.0, "shard:round")
    timer.record_probe("soul:probe", 0.5)

    keys = [key for key, _ in timer.summary("soul:")]
    assert keys == ["soul:battle", "soul:round"]        # probe 不算计时样本
    assert "soul:battle" in timer.describe_summary("soul:")
    assert timer.describe_summary("nothing:") == "（暂无计时样本）"


def test_estimate_describe_is_human_readable(timer, clock):
    assert timer.estimate(KEY).describe() == "无样本"
    record(timer, clock, 30.0)
    text = timer.estimate(KEY).describe()
    assert "min=30.0s" in text and "未收敛" in text


def test_plan_describe_mentions_blind_wait(timer, clock):
    warm_up(timer, clock, seconds=45.0)
    text = timer.plan(KEY, 300.0, 3.0).describe()
    assert "盲等" in text and "轮询" in text


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def test_percentile():
    assert _percentile([], 0.5) is None
    assert _percentile([7.0], 0.1) == pytest.approx(7.0)
    assert _percentile([10.0, 20.0], 0.5) == pytest.approx(15.0)
    assert _percentile([10.0, 20.0, 30.0, 40.0], 0.0) == pytest.approx(10.0)
    assert _percentile([10.0, 20.0, 30.0, 40.0], 1.0) == pytest.approx(40.0)


def test_estimate_defaults():
    estimate = Estimate()
    assert estimate.samples == 0 and estimate.converged is False
    assert estimate.describe() == "无样本"


def test_wait_plan_defaults():
    plan = WaitPlan()
    assert plan.blind_wait == 0.0
    assert plan.interval == settings.DEFAULT_WAIT_INTERVAL
    assert "默认" in plan.describe()
