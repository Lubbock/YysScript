"""循环计时与自适应等待。

要解决的问题
------------
以前的流程「点一下 → sleep 固定秒数 → 轮询识图」，一整轮花了多少时间从来没被记住：
- 御魂一轮实际 45 秒，代码却按 `BATTLE_INTERVAL = 3.0` 一直截屏识图，
  绝大部分时间都在做无用的空等 + 重复截图；
- 只有 `event-aj8fer` 用 `core/stopwatch.py` 的均值预测过等待时间，别处没有。

本模块提供两件事：

1. **计时**：`CycleTimer.cycle("soul:battle")` 记录一个阶段/一整轮的真实耗时，
   样本写进 `storage.DurationStore`（沿用 `GAMETIME_RECORD` 表，老 gray_scan.db 直接可用）；
2. **自适应等待**：`plan(key, timeout, interval)` 返回 `WaitPlan(blind_wait, interval)`：
   先「盲等」blind_wait 秒（这期间**完全不截屏**），之后用更细的 interval 轮询识图。
   跑得越多，盲等越贴近真实耗时，无用截图越少。

为什么不能简单地「记住最小值」
------------------------------
测出来的耗时里包含我们自己的盲等：盲等 60 秒、战斗其实 45 秒，样本就是 60 秒。
一旦出现一次异常长的等待（战斗超时、手机卡住、去喝了杯咖啡），这个偏大的样本
会把分位数顶高 → 下次盲等更久 → 样本更大 → **最小值永远收敛不下来**。

对策（三条一起用）：
1. **异常值剔除**：`s > p50 * TIMING_OUTLIER_FACTOR` 的样本不计入 min/p10，
   只累加 overruns（仍然写库，便于事后审计）；
2. **连续超限回退**：连续 `TIMING_OVERRUN_RESET` 次异常 → 丢掉该 key 的内存窗口、
   强制回到 warm-up（盲等 0，按调用方给的探测频率截图重新攒样本），
   并用更保守的 `TIMING_RESET_SAFETY` 重新收敛；
3. **硬上限**：盲等永远不超过 `TIMING_MAX_BLIND_WAIT`，也不会吃掉整个 timeout
   （至少留 `TIMING_FINE_WINDOW` 秒给细粒度轮询），估计再离谱也不会长时间瞎等。

样本不足（`usable < TIMING_WARMUP_SAMPLES`）时 `blind_wait = 0`、interval 用调用方
传进来的值 —— 也就是**完全等于改造前的行为**。所以新流程第一次跑仍然是老频率截图，
边跑边攒样本，之后自动收敛，不需要人工标定。

依赖方向：core 层，只依赖 config / storage / core.bus，不认识任何 flow 或 state。
key 约定 `"<flow>:<phase>"`，例如 `soul:round` / `soul:battle` / `soul:probe`
（`probe` 是「一次截屏 + 模板匹配」的成本，只在内存里滑动平均，不入库）。
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

try:  # Python 3.8+
    from typing import Protocol
except ImportError:  # pragma: no cover - 兜底，项目要求 3.8+
    Protocol = object  # type: ignore[assignment,misc]

from config import settings
from core.bus import EventBus
from core.logger import get_logger
from storage.duration_store import DurationStore

log = get_logger(__name__)

#: 计时样本入库 / 广播用的 topic（领域侧在 flows/signals.py 里有同名常量）
TOPIC_TIMING_RECORDED = "timing.recorded"


# --------------------------------------------------------------------------- #
# 数据结构（对外接口协议）
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Estimate:
    """某个 key 的历史耗时估计。

    samples   : 窗口内样本总数（含被判为异常的）
    usable    : 剔除异常后参与统计的样本数
    minimum   : usable 里的最小值；无样本时 None
    p10 / p50 : 分位数（线性插值）
    mean      : 窗口内**全部**样本的均值（含异常值，供人看真实情况）
    spread    : (max-min)/p50，衡量稳定度，越大说明这个阶段耗时越飘
    converged : 样本是否已足够、可以用来做盲等
    overruns  : 当前连续异常次数（达到 TIMING_OVERRUN_RESET 会触发回退）
    """

    samples: int = 0
    usable: int = 0
    minimum: Optional[float] = None
    p10: Optional[float] = None
    p50: Optional[float] = None
    mean: Optional[float] = None
    spread: float = 0.0
    converged: bool = False
    overruns: int = 0

    def describe(self) -> str:
        if not self.samples:
            return "无样本"
        return ("样本 {} 个（可用 {}）min={:.1f}s p10={:.1f}s p50={:.1f}s "
                "mean={:.1f}s 波动={:.0%} 连续异常={}{}".format(
                    self.samples, self.usable, self.minimum or 0.0, self.p10 or 0.0,
                    self.p50 or 0.0, self.mean or 0.0, self.spread, self.overruns,
                    "" if self.converged else " 未收敛"))


@dataclass(frozen=True)
class WaitPlan:
    """一次等待的执行计划。

    blind_wait : 先盲等多少秒（这期间不截屏、不识图）
    interval   : 盲等结束后轮询识图的间隔
    reason     : 为什么是这个计划（写进日志，便于事后核对）
    estimate   : 依据的历史估计，可能为 None
    """

    blind_wait: float = 0.0
    interval: float = settings.DEFAULT_WAIT_INTERVAL
    reason: str = ""
    estimate: Optional[Estimate] = None

    def describe(self) -> str:
        return "盲等 {:.1f}s 后以 {:.1f}s 间隔轮询（{}）".format(
            self.blind_wait, self.interval, self.reason or "默认")


@dataclass(frozen=True)
class TimingSample:
    """一次计时结果，随 `timing.recorded` 事件广播。"""

    key: str
    seconds: float
    estimate: Estimate
    plan: Optional[WaitPlan] = None


class WaitScheduler(Protocol):
    """等待策略接口。

    谁需要「等多久、隔多久识一次图」就问它，实现方决定是固定间隔还是自适应。
    `states.machine.StateMachine` 的 wait_* 系列、`flows.engine.FlowEngine`
    都只依赖这个协议，因此可以整体换成 FixedScheduler 做对照 / 关闭自适应。
    """

    def plan(self, key: str, timeout: float,
             interval: Optional[float] = None) -> WaitPlan:  # pragma: no cover
        ...


class FixedScheduler:
    """永远返回「不盲等 + 调用方给的间隔」，即改造前的行为。

    用途：`--no-adaptive-wait` / `YYS_ADAPTIVE_WAIT=0`，以及单测里的对照组。
    """

    adaptive = False

    def plan(self, key: str, timeout: float,
             interval: Optional[float] = None) -> WaitPlan:
        return WaitPlan(
            blind_wait=0.0,
            interval=settings.DEFAULT_WAIT_INTERVAL if interval is None else interval,
            reason="固定间隔（自适应等待已关闭）",
        )


class Cycle:
    """一次计时的句柄。由 CycleTimer.begin() 产出，不要手工构造。"""

    __slots__ = ("key", "start", "seconds", "finished", "_clock")

    def __init__(self, key: str, clock, start: Optional[float] = None) -> None:
        self.key = key
        self._clock = clock
        self.start = clock() if start is None else start
        self.seconds: Optional[float] = None
        self.finished = False

    def elapsed(self) -> float:
        """已经过去的秒数；已 commit/discard 的返回定格值。"""
        if self.seconds is not None:
            return self.seconds
        return max(0.0, self._clock() - self.start)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "<Cycle {} {:.2f}s{}>".format(
            self.key, self.elapsed(), " done" if self.finished else "")


# --------------------------------------------------------------------------- #
# 主体
# --------------------------------------------------------------------------- #
class CycleTimer:
    """循环计时器 + 自适应等待调度器（实现 WaitScheduler）。

    典型用法：
        timer = CycleTimer()
        with timer.cycle("soul:battle"):
            ...打一场...
        plan = timer.plan("soul:battle", timeout=300.0, interval=3.0)
        sleep(plan.blind_wait)          # 这段时间不截屏
        while not 命中: sleep(plan.interval)

    参数：
        store    : 样本持久化，默认 storage.DurationStore()（var/gray_scan.db）
        clock    : 计时函数，默认 time.monotonic；单测注入假时钟
        window   : 参与统计的最近样本数，默认 settings.TIMING_WINDOW
        adaptive : 是否启用自适应等待，默认读 settings.ADAPTIVE_WAIT
        bus      : 给了就在每次 commit 后广播 TimingSample 到 timing.recorded
    """

    def __init__(
        self,
        store: Optional[DurationStore] = None,
        clock=time.monotonic,
        window: Optional[int] = None,
        adaptive: Optional[bool] = None,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._store = store if store is not None else DurationStore()
        self._clock = clock
        self.window = settings.TIMING_WINDOW if window is None else int(window)
        self.adaptive = settings.ADAPTIVE_WAIT if adaptive is None else bool(adaptive)
        self.bus = bus
        #: key -> 最近 window 个样本（内存窗口，首次访问从 DB 载入）
        self._samples: Dict[str, List[float]] = {}
        #: 已从 DB 载入过的 key，避免每次 estimate 都读盘
        self._loaded: set = set()
        #: key -> 连续异常样本数
        self._overruns: Dict[str, int] = {}
        #: 触发过回退、正在用保守安全系数重新收敛的 key
        self._conservative: set = set()
        #: key -> 「一次截屏+匹配」的成本窗口（只在内存，不入库）
        self._probes: Dict[str, List[float]] = {}

    # ------------------------------------------------------------------ 计时
    def begin(self, key: str) -> Cycle:
        """开始计时，返回 Cycle 句柄。"""
        cycle = Cycle(key, self._clock)
        log.debug("计时开始 %s", key)
        return cycle

    @contextmanager
    def cycle(self, key: str) -> Iterator[Cycle]:
        """with 语法糖：正常退出 commit，异常退出 discard（异常样本会污染估计）。"""
        cycle = self.begin(key)
        try:
            yield cycle
        except BaseException as exc:
            self.discard(cycle, "{}: {}".format(type(exc).__name__, exc))
            raise
        else:
            if not cycle.finished:
                self.commit(cycle)

    def commit(self, cycle: Cycle, seconds: Optional[float] = None) -> float:
        """结束计时并把样本写库，返回本次耗时（秒）。

        重复 commit 只记一次（返回定格的值），避免样本被重复写入。
        """
        if cycle.finished:
            log.warning("计时 %s 已结束，忽略重复提交", cycle.key)
            return cycle.elapsed()
        value = cycle.elapsed() if seconds is None else float(seconds)
        cycle.seconds = value
        cycle.finished = True
        key = cycle.key

        history = self.estimate(key)
        outlier = self._is_outlier(history, value)
        # 审计用途：异常样本也入库，只是不参与 min/p10 统计
        self._store.record(key, value)
        samples = self._window(key)
        if outlier:
            self._overruns[key] = self._overruns.get(key, 0) + 1
            log.warning(
                "计时 %s 本次 %.1f 秒，明显高于历史 p50=%.1f 秒（连续第 %s 次），"
                "不计入最小值统计", key, value, history.p50 or 0.0, self._overruns[key])
            if self._overruns[key] >= settings.TIMING_OVERRUN_RESET:
                self._reset(key, samples)
        else:
            self._overruns[key] = 0
            samples.append(value)
            if len(samples) > self.window:
                del samples[: len(samples) - self.window]
            if key in self._conservative and len(self._usable(samples)) >= \
                    settings.TIMING_RESET_RECOVER_SAMPLES:
                self._conservative.discard(key)
                log.info("计时 %s 已连续 %s 个正常样本，恢复常规安全系数",
                         key, settings.TIMING_RESET_RECOVER_SAMPLES)

        estimate = self.estimate(key)
        log.info("计时 %s 本次 %.1f 秒；%s", key, value, estimate.describe())
        self._publish(key, value, estimate)
        return value

    def discard(self, cycle: Cycle, reason: str = "") -> None:
        """放弃这次计时（超时 / 异常），不写样本。"""
        cycle.finished = True
        cycle.seconds = cycle.elapsed()
        log.info("计时 %s 作废（%.1f 秒）：%s", cycle.key, cycle.seconds, reason or "未说明")

    def _reset(self, key: str, samples: List[float]) -> None:
        """连续异常达到上限：丢掉内存窗口，强制重新 warm-up 收敛。"""
        del samples[:]
        self._overruns[key] = 0
        self._conservative.add(key)
        log.warning(
            "计时 %s 连续 %s 次异常，丢弃历史窗口回到探测频率重新收敛"
            "（安全系数临时降到 %.2f）；数据库里的样本保留可审计",
            key, settings.TIMING_OVERRUN_RESET, settings.TIMING_RESET_SAFETY)

    def _publish(self, key: str, value: float, estimate: Estimate) -> None:
        if self.bus is None:
            return
        self.bus.publish(TOPIC_TIMING_RECORDED,
                         TimingSample(key=key, seconds=value, estimate=estimate))

    # ------------------------------------------------------------------ 统计
    def estimate(self, key: str) -> Estimate:
        """key 的历史耗时估计（剔除异常值后统计）。"""
        samples = self._window(key)
        overruns = self._overruns.get(key, 0)
        if not samples:
            return Estimate(samples=0, usable=0, converged=False, overruns=overruns)
        usable = self._usable(samples)
        p50 = _percentile(usable, 0.5)
        p10 = _percentile(usable, 0.1)
        low, high = min(usable), max(usable)
        spread = ((high - low) / p50) if p50 else 0.0
        converged = (
            len(usable) >= settings.TIMING_WARMUP_SAMPLES and overruns == 0
        )
        return Estimate(
            samples=len(samples),
            usable=len(usable),
            minimum=low,
            p10=p10,
            p50=p50,
            mean=sum(samples) / len(samples),
            spread=spread,
            converged=converged,
            overruns=overruns,
        )

    def _usable(self, samples: Sequence[float]) -> List[float]:
        """剔除异常值后的样本（异常判据与 commit 时保持一致）。"""
        data = list(samples)
        if not data:
            return []
        median = _percentile(data, 0.5)
        if median <= 0:
            return data
        limit = median * settings.TIMING_OUTLIER_FACTOR
        kept = [value for value in data if value <= limit]
        # 全部被判异常时退回原样，避免 usable 为空导致永远不收敛
        return kept or data

    def _is_outlier(self, history: Estimate, value: float) -> bool:
        """新样本相对历史是否算异常（历史不足时一律不算）。"""
        if history.usable <= 0 or not history.p50:
            return False
        return value > history.p50 * settings.TIMING_OUTLIER_FACTOR

    def _window(self, key: str) -> List[float]:
        """key 的内存样本窗口；首次访问从 DB 载入最近 window 条。"""
        if key not in self._loaded:
            self._loaded.add(key)
            try:
                stored = self._store.samples(key)
            except Exception as exc:  # 库坏了不该让流程跑不起来
                log.warning("读取计时样本 %s 失败，从空窗口开始: %s", key, exc)
                stored = []
            self._samples[key] = list(stored[-self.window:]) if self.window else []
            if self._samples[key]:
                log.info("计时 %s 载入历史样本 %s 个（最近 %s 个参与统计）",
                         key, len(stored), len(self._samples[key]))
        return self._samples.setdefault(key, [])

    # ------------------------------------------------------------------ 等待计划
    def plan(self, key: str, timeout: float, interval: Optional[float] = None,
             probe_key: Optional[str] = None) -> WaitPlan:
        """决定「先盲等多久、之后隔多久识一次图」。

        key       : 计时 key，例如 "soul:battle"
        timeout   : 本次等待的总超时，盲等不会吃掉全部超时
        interval  : 调用方原本想用的轮询间隔（未收敛时就用它 = 老行为）
        probe_key : 「截屏+匹配」成本的 key，默认取 "<flow>:probe"
        """
        probe_interval = settings.DEFAULT_WAIT_INTERVAL if interval is None else interval
        if not self.adaptive:
            return WaitPlan(0.0, probe_interval, "自适应等待已关闭")

        estimate = self.estimate(key)
        if not estimate.converged or not estimate.p10:
            return WaitPlan(
                0.0, probe_interval,
                "样本不足（可用 {} 个 < {}）或刚回退，按探测频率截图攒样本".format(
                    estimate.usable, settings.TIMING_WARMUP_SAMPLES),
                estimate)

        safety = (settings.TIMING_RESET_SAFETY if key in self._conservative
                  else settings.TIMING_SAFETY)
        cost = self.probe_cost(probe_key or _probe_key_of(key))
        # 盲等目标 = 大概率还没结束的时间点；扣掉一次识图成本，避免刚盲等完就白截一次
        raw = estimate.p10 * safety - cost
        ceiling = min(settings.TIMING_MAX_BLIND_WAIT,
                      timeout - settings.TIMING_FINE_WINDOW)
        blind = max(0.0, min(raw, max(0.0, ceiling)))
        fine = settings.TIMING_FINE_INTERVAL
        if blind <= 0:
            return WaitPlan(0.0, fine,
                            "超时 {:.0f}s 太短，不盲等，直接 {:.1f}s 细轮询".format(
                                timeout, fine), estimate)
        return WaitPlan(
            blind_wait=blind,
            interval=fine,
            reason="p10={:.1f}s×{:.2f} 扣掉识图 {:.2f}s，盲等上限 {:.0f}s".format(
                estimate.p10, safety, cost, ceiling),
            estimate=estimate,
        )

    # ------------------------------------------------------------------ 识图成本
    def record_probe(self, key: str, seconds: float) -> None:
        """记录一次「截屏 + 模板匹配」的成本（只存内存滑动窗口）。

        盲等时间要扣掉它：识图本身要花时间，盲等就该少等这么多。
        不入库 —— 它跟机器负载强相关，跨进程复用没有意义，还会把样本表刷爆。
        """
        if seconds < 0:
            return
        window = self._probes.setdefault(key, [])
        window.append(float(seconds))
        limit = settings.TIMING_PROBE_WINDOW
        if len(window) > limit:
            del window[: len(window) - limit]

    def probe_cost(self, key: Optional[str] = None) -> float:
        """一次识图的平均成本（秒）；没有样本时返回 0。"""
        if key is None:
            return 0.0
        window = self._probes.get(key)
        if not window:
            return 0.0
        return sum(window) / len(window)

    # ------------------------------------------------------------------ 汇总
    def summary(self, prefix: str = "") -> List[Tuple[str, Estimate]]:
        """按 key 排序返回估计值，给流程收尾打总账用。"""
        keys = set(self._samples) | set(self._probes)
        if prefix:
            keys = {key for key in keys if key.startswith(prefix)}
        result = [(key, self.estimate(key)) for key in sorted(keys) if key in self._samples]
        return result

    def describe_summary(self, prefix: str = "") -> str:
        """把 summary 拼成多行文本。"""
        rows = self.summary(prefix)
        if not rows:
            return "（暂无计时样本）"
        width = max(len(key) for key, _ in rows)
        return "\n".join("  {:<{width}}  {}".format(key, est.describe(), width=width)
                         for key, est in rows)


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def _percentile(values: Sequence[float], q: float) -> Optional[float]:
    """线性插值分位数；空序列返回 None。"""
    data = sorted(values)
    if not data:
        return None
    if len(data) == 1:
        return float(data[0])
    position = (len(data) - 1) * max(0.0, min(1.0, q))
    low = int(position)
    high = min(low + 1, len(data) - 1)
    ratio = position - low
    return float(data[low] + (data[high] - data[low]) * ratio)


def _probe_key_of(key: str) -> str:
    """从 "soul:battle" 推出同流程的识图成本 key "soul:probe"。"""
    prefix = key.split(":", 1)[0]
    return "{}:probe".format(prefix)
