"""主流程引擎：轮询识图 -> 广播事件 -> 订阅方决定动作 -> 推进轮次。

改造前 flows 里的写法是硬编码链条：

    self.wait(SOUL_CHALLENGE) -> self.click(...) -> self.wait_any(END_STATES) -> ...

「识别到什么就做什么」写死在 run() 里，加一条规则（例如结算后再点两下、
遇到某个弹窗先关掉）就得改流程本体，而且每一步都在按固定间隔空转截图。

改造后：

    engine = FlowEngine("soul", machine, controller)
    engine.watch(SOUL_CHALLENGE, SHARD_BATTLE_END)      # 引擎只关心「看哪些状态」
    BattleCycle(engine, ...).attach()                    # 规则都在订阅方里
    engine.run_rounds(times, round_timeout=...)          # 引擎负责推进与计时

引擎本身**不含任何玩法知识**：它只做四件事
1. 按 `watch()` 给的候选状态轮询识图（`states.machine.detect_first`）；
2. 把「识图完成 / 命中状态 / 状态跳变 / 什么都没识别到 / 超时」广播到 EventBus；
3. 接受订阅方的反馈：`round.done`（本轮结束）、`fail()`（中止流程）、`stop()`（优雅停止）、
   `begin_wait()`（声明接下来在等什么，从而决定盲等与轮询节奏）；
4. 用 `core.timing.CycleTimer` 记录每轮 / 每阶段耗时，并据此决定「先盲等多久、
   之后隔多久识一次图」，把无用截图压到最低。

事件与 topic 见 `flows/signals.py`；通用发布订阅见 `core/bus.py`。
"""
from __future__ import annotations

import time
from typing import Any, Callable, List, Optional, Sequence, Tuple

from config import settings
from core.bus import EventBus, Subscription
from core.errors import FlowAbortedError
from core.logger import get_logger
from core.timing import CycleTimer, FixedScheduler, WaitPlan
from flows.signals import (
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
    PREFIX_STATE_ENTERED,
    PREFIX_STATE_EXITED,
    ActionEvent,
    FlowEvent,
    PollEvent,
    RoundEvent,
    StateEvent,
    TimeoutEvent,
    topic_for,
)
from states.machine import Detection

#: 订阅方回调
Handler = Callable[[Any], None]


class FlowEngine:
    """事件驱动的流程推进器。

    参数：
        name       : 流程名（同时作为计时 key 前缀，例如 "soul" -> "soul:round"）
        machine    : states.machine.StateMachine（或任何有 detect_first 的对象）
        controller : actions.controller.GameController，订阅方通过 engine.click() 用它
        bus        : 事件总线，默认新建一条（一个流程一条总线，互不串台）
        timer      : 计时器，默认新建并绑定到 bus（commit 时广播 timing.recorded）
        adaptive   : None = 跟随 settings.ADAPTIVE_WAIT；False = 固定间隔（老行为）
        clock / sleeper : 可注入，单测用假时钟把「盲等 40 秒」变成瞬时
    """

    def __init__(
        self,
        name: str,
        machine,
        controller=None,
        bus: Optional[EventBus] = None,
        timer: Optional[CycleTimer] = None,
        adaptive: Optional[bool] = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Optional[Callable[[float], None]] = None,
        poll_interval: Optional[float] = None,
    ) -> None:
        self.name = name
        self.machine = machine
        self.controller = controller
        self.bus = bus or EventBus()
        self.timer = timer or CycleTimer(bus=self.bus, adaptive=adaptive)
        #: 等待策略：关掉自适应时换成 FixedScheduler（永远 blind_wait=0）
        self.adaptive = self.timer.adaptive if adaptive is None else bool(adaptive)
        self.scheduler = self.timer if self.adaptive else FixedScheduler()
        self._clock = clock
        self._sleep = sleeper if sleeper is not None else time.sleep
        self.log = get_logger("flows.engine.{}".format(name))

        #: 计时 key
        self.round_key = "{}:round".format(name)
        self.probe_key = "{}:probe".format(name)
        #: 当前「在等什么」：决定盲等依据哪个 key 的历史；None 表示不盲等
        self.wait_key: Optional[str] = None
        #: 未收敛 / 不盲等时的轮询间隔
        self.poll_interval: float = (settings.DEFAULT_WAIT_INTERVAL
                                     if poll_interval is None else float(poll_interval))

        self._watched: Tuple[Any, ...] = ()
        self._current: Optional[Detection] = None
        self._plan: Optional[WaitPlan] = None
        self._plan_signature: Optional[Tuple[Any, ...]] = None
        self._blind_used = False

        #: 运行状态
        self.round_index = 0
        self.rounds_completed = 0
        #: 计划要跑的总轮数（None = 无限），仅用于日志
        self._rounds_total: Optional[int] = None
        self.flow_seconds = 0.0
        self._round_done = False
        #: 本轮起始时刻；用 None 而不是 0.0 作哨兵 —— 时钟恰好从 0 起步时
        #: （单测的假时钟、或某些平台的 monotonic 起点）0.0 是合法时刻
        self._round_started_at: Optional[float] = None
        self._poll_index = 0
        self._unknown_streak = 0
        self._seen_states: List[str] = []
        self._durations: List[float] = []
        self._stop = False
        self._pending_error: Optional[BaseException] = None
        #: 识图统计：一共截了多少次屏、花了多少秒（收尾打总账用）
        self.probe_count = 0
        self.probe_seconds = 0.0

        # 订阅方发 round.done 表示「这一轮我处理完了」，引擎据此结束本轮
        self.bus.subscribe(TOPIC_ROUND_DONE, self._on_round_done, priority=-100)

    # ------------------------------------------------------------------ 配置
    def watch(self, *states) -> "FlowEngine":
        """登记要轮询识别的状态（顺序即优先级，detect_first 按序命中）。"""
        self._watched = self._watched + tuple(states)
        return self

    def unwatch(self, state) -> None:
        key = getattr(state, "key", state)
        self._watched = tuple(item for item in self._watched
                              if getattr(item, "key", item) != key)

    @property
    def watched(self) -> Tuple[Any, ...]:
        return self._watched

    @property
    def current(self) -> Optional[Detection]:
        """最近一次命中的状态。"""
        return self._current

    @property
    def current_key(self) -> str:
        return self._current.state.key if self._current else ""

    @property
    def interrupted(self) -> bool:
        """引擎是否已被要求停止 / 中止。

        订阅方在真正动手（点击）之前可以先看一眼：事件是同步投递的，
        同一个 tick 里可能先有别的订阅方调用了 stop() / fail()。
        """
        return self._stop or self._pending_error is not None

    def on(self, topic: str, handler: Handler, priority: int = 0,
           once: bool = False) -> Subscription:
        """订阅事件（bus.subscribe 的简写）。"""
        return self.bus.subscribe(topic, handler, priority=priority, once=once)

    def publish(self, topic: str, event: Any = None) -> int:
        return self.bus.publish(topic, event)

    # ------------------------------------------------------------------ 节奏
    def begin_wait(self, key: Optional[str], interval: Optional[float] = None) -> None:
        """声明「接下来在等什么」，引擎据此重新规划盲等与轮询间隔。

        key      : 计时 key，例如 "soul:battle"；None 表示不盲等、只按固定间隔轮询
        interval : 该阶段的探测间隔（未收敛时用），None 表示沿用当前值
        """
        self.wait_key = key
        if interval is not None:
            self.poll_interval = float(interval)
        self._plan_signature = None
        self._blind_used = False
        self._plan = None

    def _plan_for(self, key: Optional[str], timeout: float,
                  interval: float) -> WaitPlan:
        if not key:
            return WaitPlan(0.0, interval, "未指定计时 key，不盲等")
        return self.scheduler.plan(key, timeout=timeout, interval=interval)

    def _idle(self, remaining: float) -> None:
        """两次识图之间的等待：先一次性盲等，之后按 interval 轮询。"""
        signature = (self.wait_key, self.poll_interval)
        if signature != self._plan_signature:
            self._plan_signature = signature
            self._blind_used = False
            self._plan = self._plan_for(self.wait_key, remaining, self.poll_interval)
            if self.wait_key:
                self.log.info("等待阶段 %s：%s", self.wait_key, self._plan.describe())
        plan = self._plan or WaitPlan(0.0, self.poll_interval, "默认")
        if plan.blind_wait > 0 and not self._blind_used:
            self._blind_used = True
            blind = min(plan.blind_wait, max(0.0, remaining))
            self.log.info("盲等 %.1f 秒（这期间不截屏、不识图）", blind)
            self._sleep(blind)
            remaining -= blind
            if remaining <= 0:
                return
        self._sleep(min(plan.interval, max(0.0, remaining)))

    # ------------------------------------------------------------------ 识图
    def observe(self, states: Optional[Sequence] = None) -> Optional[Detection]:
        """识一次图并广播事件；states 为空时用 watch() 登记的候选。"""
        return self._observe(self._watched if states is None else tuple(states),
                             publish=True)

    def step(self) -> Optional[Detection]:
        """observe(watched) 的别名，主循环用。"""
        return self.observe(self._watched)

    def peek(self, states: Sequence) -> Optional[Detection]:
        """识一次图但**不广播**：订阅方内部做阻塞等待时用，避免干扰主循环的状态跟踪。"""
        return self._observe(tuple(states), publish=False)

    def _observe(self, candidates: Sequence, publish: bool) -> Optional[Detection]:
        if not candidates:
            raise FlowAbortedError("引擎没有登记任何要识别的状态，请先 watch(...)")
        started = self._clock()
        detection = self.machine.detect_first(candidates)
        cost = self._clock() - started
        self.timer.record_probe(self.probe_key, cost)
        self.probe_count += 1
        self.probe_seconds += cost
        self._poll_index += 1
        if not publish:
            return detection

        if detection is None:
            self._unknown_streak += 1
        else:
            self._unknown_streak = 0
        poll_event = PollEvent(
            index=self._poll_index,
            cost=cost,
            hit=detection is not None,
            state_key=detection.state.key if detection else "",
            round_index=self.round_index,
            unknown_streak=self._unknown_streak,
        )
        self.publish(TOPIC_POLL_COMPLETED, poll_event)
        if detection is None:
            self._exit_current()
            if self._unknown_streak and \
                    self._unknown_streak % settings.UNKNOWN_POLL_LIMIT == 0:
                self.log.warning("连续 %s 次没有识别到任何已知状态（当前可能在战斗动画中）",
                                 self._unknown_streak)
                self.publish(TOPIC_STATE_UNKNOWN, poll_event)
            return None

        self.publish(TOPIC_STATE_DETECTED, self._state_event(detection))
        self._enter(detection)
        return detection

    def _state_event(self, detection: Detection, previous: str = "") -> StateEvent:
        return StateEvent(
            state=detection.state,
            match=detection.match,
            score=detection.score,
            round_index=self.round_index,
            waited=self.elapsed_round(),
            previous=previous,
        )

    def _enter(self, detection: Detection) -> None:
        previous = self._current
        if previous is not None and previous.state.key == detection.state.key:
            return  # 同一个状态持续命中，不算跳变，避免重复触发动作
        if previous is not None:
            self._publish_exit(previous, detection.state.key)
        self._current = detection
        self.log.info("进入状态 %s（置信度 %.3f，本轮第 %.1f 秒）",
                      detection.state, detection.score, self.elapsed_round())
        self.publish(topic_for(PREFIX_STATE_ENTERED, detection.state),
                     self._state_event(detection, previous.state.key if previous else ""))

    def _exit_current(self) -> None:
        if self._current is None:
            return
        self._publish_exit(self._current, "")
        self._current = None

    def _publish_exit(self, detection: Detection, next_key: str) -> None:
        self.log.debug("离开状态 %s", detection.state)
        self.publish(topic_for(PREFIX_STATE_EXITED, detection.state),
                     self._state_event(detection, next_key))

    def elapsed_round(self) -> float:
        """本轮已经跑了多少秒。"""
        if self._round_started_at is None:
            return 0.0
        return max(0.0, self._clock() - self._round_started_at)

    def reset_current(self) -> None:
        """清掉「当前状态」，让下一次识图必然产生一次跳变事件。

        每轮开始时引擎自己会调用。订阅方在内部做过不广播的阻塞等待
        （peek / wait_for(publish=False)）之后也可以调用它，
        否则主循环会以为画面还停在旧状态，从而漏掉 state.entered。
        """
        self._current = None

    # ------------------------------------------------------------------ 阻塞等待
    def wait_for(
        self,
        states: Sequence,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        key: Optional[str] = None,
        publish: bool = False,
        on_wait: Optional[Callable[[int], None]] = None,
    ) -> Optional[Detection]:
        """等候选状态中任意一个出现，返回命中结果；超时返回 None。

        与 states.machine.wait_any 的区别：
        1. 等待节奏由 scheduler 决定 —— 先按历史耗时无截图盲等，再细粒度轮询；
        2. publish=True 时命中 / 超时也会广播事件（默认 False：这是订阅方内部的
           阻塞等待，不该反过来驱动主循环的状态跟踪，否则会出现重入）。
        """
        timeout = settings.DEFAULT_WAIT_TIMEOUT if timeout is None else timeout
        interval = self.poll_interval if interval is None else interval
        candidates = tuple(states)
        started = self._clock()
        deadline = started + timeout
        plan = self._plan_for(key or self.wait_key, timeout, interval)
        if plan.blind_wait > 0:
            self.log.debug("wait_for %s：%s", [getattr(c, "key", c) for c in candidates],
                           plan.describe())
            self._sleep(min(plan.blind_wait, timeout))
        rounds = 0
        while True:
            detection = self._observe(candidates, publish=publish)
            if detection is not None:
                return detection
            rounds += 1
            if on_wait is not None:
                on_wait(rounds)
            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            self._sleep(min(plan.interval, remaining))
        if publish:
            self.publish(TOPIC_STATE_TIMEOUT, TimeoutEvent(
                key=key or self.wait_key or "wait",
                waited=self._clock() - started,
                timeout=timeout,
                round_index=self.round_index,
                states=tuple(getattr(c, "key", str(c)) for c in candidates),
            ))
        self.log.warning("等待 %s 超时（%.1f 秒）",
                         [getattr(c, "key", c) for c in candidates], timeout)
        return None

    # ------------------------------------------------------------------ 动作
    def click(self, target: Any, detail: str = "", state_key: str = "", **kwargs) -> Any:
        """点击并广播 action.performed。

        target 支持 controller 能接受的一切（Point / Match / Box / 屏幕坐标），
        另外还支持直接传 Detection（自动取它的 match）。
        """
        if isinstance(target, Detection):
            state_key = state_key or target.state.key
            target = target.match
        if target is None:
            raise FlowAbortedError("click 目标为空（{}）".format(detail or "未说明"))
        result = None
        if self.controller is not None:
            result = self.controller.click(target, **kwargs)
        self.publish(TOPIC_ACTION_PERFORMED, ActionEvent(
            kind="click", target=target, state_key=state_key,
            round_index=self.round_index, detail=detail))
        return result

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self._sleep(seconds)

    # ------------------------------------------------------------------ 控制
    def finish_round(self, reason: str = "") -> None:
        """订阅方调用：本轮已经处理完，引擎可以进入下一轮。"""
        self.publish(TOPIC_ROUND_DONE, RoundEvent(index=self.round_index, reason=reason))

    def _on_round_done(self, event: Any = None) -> None:
        self._round_done = True

    def stop(self, reason: str = "") -> None:
        """优雅停止：跑完当前这一步就退出轮次循环，不抛异常。"""
        self.log.info("引擎收到停止请求：%s", reason or "未说明")
        self._stop = True

    def fail(self, error: Any) -> None:
        """订阅方调用：中止整个流程。

        异常不会在订阅方里直接抛（那样会被 EventBus 的异常隔离吞掉），
        而是记下来，等本次事件投递结束后由引擎抛出，语义与改造前一致。
        """
        self._pending_error = (error if isinstance(error, BaseException)
                               else FlowAbortedError(str(error)))
        self._stop = True
        self.log.error("引擎被要求中止：%s", self._pending_error)

    # ------------------------------------------------------------------ 主循环
    def run_rounds(
        self,
        rounds: Optional[int] = None,
        round_timeout: Optional[float] = None,
        on_round: Optional[Callable[[int], None]] = None,
    ) -> int:
        """推进 rounds 轮（None 表示无限，直到 stop() / fail()），返回完成轮数。"""
        if not self._watched:
            raise FlowAbortedError("引擎没有登记任何要识别的状态，请先 watch(...)")
        self._stop = False
        self._pending_error = None
        self.rounds_completed = 0
        self._rounds_total = rounds
        self.publish(TOPIC_FLOW_STARTED, FlowEvent(name=self.name, rounds=rounds or 0))
        started = self._clock()
        try:
            while not self._stop and (rounds is None or self.rounds_completed < rounds):
                if self._run_one_round(self.rounds_completed + 1, round_timeout, on_round):
                    self.rounds_completed += 1
                if self._stop or self._pending_error is not None:
                    break
        except KeyboardInterrupt:
            self.flow_seconds = self._clock() - started
            self.publish(TOPIC_FLOW_FINISHED, FlowEvent(
                name=self.name, rounds=self.rounds_completed,
                total_seconds=self.flow_seconds, aborted=True, reason="用户中断"))
            raise
        self.flow_seconds = self._clock() - started
        aborted = self._pending_error is not None
        self.publish(TOPIC_FLOW_FINISHED, FlowEvent(
            name=self.name, rounds=self.rounds_completed,
            total_seconds=self.flow_seconds, aborted=aborted,
            reason=str(self._pending_error) if aborted else ""))
        self.log.info("%s", self.summary())
        if self._pending_error is not None:
            raise self._pending_error
        return self.rounds_completed

    def _run_one_round(
        self,
        index: int,
        round_timeout: Optional[float],
        on_round: Optional[Callable[[int], None]],
    ) -> bool:
        """跑一轮。

        返回这一轮是否算「跑完了」：订阅方发了 round.done、或整轮预算超时都算；
        被 stop() / fail() 打断的半轮返回 False —— 既不计入完成轮数，
        也不写计时样本（半轮数据会把最小值带偏）。
        """
        self.round_index = index
        self._poll_index = 0
        self._unknown_streak = 0
        self._round_done = False
        self._seen_states = []
        self._round_started_at = self._clock()
        # 每轮重新观察世界：清掉上一轮残留的「当前状态」，
        # 这样本轮第一次识图必然产生一次 state.entered（订阅方靠它触发动作）
        self._current = None
        timeout = (settings.DEFAULT_WAIT_TIMEOUT if round_timeout is None
                   else float(round_timeout))
        if self._rounds_total:
            self.log.info("---------- %s 第 %s/%s 轮 ----------",
                          self.name, index, self._rounds_total)
        else:
            self.log.info("---------- %s 第 %s 轮 ----------", self.name, index)
        self.publish(TOPIC_ROUND_STARTED, RoundEvent(index=index))
        if on_round is not None:
            on_round(index)

        cycle = self.timer.begin(self.round_key)
        timed_out = False
        deadline = self._round_started_at + timeout
        while not self._round_done and not self._stop:
            detection = self.step()
            if detection is not None and detection.state.key not in self._seen_states:
                self._seen_states.append(detection.state.key)
            if self._round_done or self._stop or self._pending_error is not None:
                break
            remaining = deadline - self._clock()
            if remaining <= 0:
                timed_out = True
                break
            self._idle(remaining)

        elapsed = self._clock() - self._round_started_at
        # 被 stop() / fail() 打断的轮次不算「跑完了一轮」
        interrupted = ((self._stop or self._pending_error is not None)
                       and not self._round_done)
        if timed_out:
            self.timer.discard(cycle, "本轮超时（上限 {:.0f} 秒）".format(timeout))
            self.log.warning("第 %s 轮超时（%.1f 秒），已识别到 %s",
                             index, elapsed, self._seen_states or "无")
            self.publish(TOPIC_STATE_TIMEOUT, TimeoutEvent(
                key=self.round_key, waited=elapsed, timeout=timeout,
                round_index=index, states=tuple(self._seen_states)))
        elif interrupted:
            # 半轮的数据不是完整样本，入库会把最小值带偏，直接作废
            self.timer.discard(cycle, "本轮被打断（stop / fail）")
        else:
            elapsed = self.timer.commit(cycle)
            self._durations.append(elapsed)

        reason = "超时" if timed_out else ("被打断" if interrupted else "")
        self.publish(TOPIC_ROUND_FINISHED, RoundEvent(
            index=index, duration=elapsed, states=tuple(self._seen_states),
            timed_out=timed_out, reason=reason))
        return not interrupted

    # ------------------------------------------------------------------ 总账
    def summary(self) -> str:
        """收尾汇总：轮数、总耗时、每轮均值、各阶段估计、识图成本。"""
        lines = ["=== {} 总账：{} 轮，共 {:.1f} 秒 ===".format(
            self.name, self.rounds_completed, self.flow_seconds)]
        if self._durations:
            lines.append("  每轮耗时：均值 {:.1f}s / 最快 {:.1f}s / 最慢 {:.1f}s".format(
                sum(self._durations) / len(self._durations),
                min(self._durations), max(self._durations)))
        lines.append(self.timer.describe_summary("{}:".format(self.name)))
        lines.append("  识图：{} 次，共 {:.1f}s，平均 {:.2f}s/次".format(
            self.probe_count, self.probe_seconds,
            (self.probe_seconds / self.probe_count) if self.probe_count else 0.0))
        return "\n".join(lines)
