"""主循环：按 DSL 顺序推进，每步只比对一张图。

一轮 = 走完 DSL 里的全部 steps；跑完最后一步回到第一步，循环次数由 --times 控制。
每一步的流程：

    自适应盲等（core/timing.py 按历史 p10 算） -> 轮询判定（只比对这一张目标图）
    -> 命中后停顿 -> on_step_matched 钩子 -> 标注坐标经 Viewport 换算 -> HumanMouse 点击

判定耗时会被记进 CycleTimer 的 probe 窗口，所以盲等会自动扣掉一次模型调用的成本；
每步的总耗时入库，下一轮就能盲等得更准。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import settings
from config.coordinates import Point
from core.logger import get_logger
from core.timing import CycleTimer
from runner import gfx
from runner.actor import Actor, ClickOutcome
from runner.dsl import Flow, Step
from runner.errors import RoundTimeout, RunnerError, StepResolveError, StepTimeout
from runner.group import AnnotationRef, GroupRef, ShotRef
from runner.matcher import ScreenMatcher, Verdict
from runner.session import ClickResult, Session

log = get_logger(__name__)


@dataclass(frozen=True)
class ResolvedStep:
    """Step 解析到具体截图与标注之后的样子。"""

    step: Step
    shot: ShotRef
    annotation: Optional[AnnotationRef]
    timeout: float
    interval: float

    @property
    def name(self) -> str:
        return self.step.name

    def timing_key(self, prefix: str) -> str:
        return "{}:{}".format(prefix, self.name)

    def describe(self) -> str:
        target = "点击「{}」".format(self.annotation.label) if self.annotation else "只识别不点击"
        return "[{}] {} -> {}（超时 {:.0f}s）".format(
            self.shot.id, self.step.describe(), target, self.timeout)


@dataclass
class StepReport:
    """一步的执行结果。"""

    index: int
    name: str
    shot_id: str
    matched: bool = False
    score: float = 0.0
    probes: int = 0
    waited: float = 0.0
    clicked: bool = False
    click: str = ""
    skipped: bool = False
    error: str = ""

    def describe(self) -> str:
        if self.skipped:
            state = "跳过"
        elif self.matched:
            state = "命中" if self.clicked else "命中未点"
        else:
            state = "超时"
        return "{} {}「{}」可信度{:.2f} 判定{}次 等待{:.1f}s{}".format(
            self.index + 1, state, self.name, self.score, self.probes, self.waited,
            "（{}）".format(self.error) if self.error else "")


@dataclass
class RoundReport:
    """一轮的执行结果。"""

    index: int
    steps: List[StepReport] = field(default_factory=list)
    duration: float = 0.0
    ok: bool = False
    timed_out: bool = False
    error: str = ""

    @property
    def clicks(self) -> int:
        return sum(1 for item in self.steps if item.clicked)

    @property
    def probes(self) -> int:
        return sum(item.probes for item in self.steps)


@dataclass
class RunReport:
    """整次运行的总账。"""

    group: str
    flow: str
    requested: Optional[int]
    rounds: List[RoundReport] = field(default_factory=list)
    duration: float = 0.0
    stopped: bool = False
    stop_reason: str = ""
    steps_per_round: int = 0
    probes: int = 0

    @property
    def completed(self) -> int:
        return sum(1 for item in self.rounds if item.ok)

    @property
    def failed(self) -> int:
        return sum(1 for item in self.rounds if not item.ok)

    @property
    def clicks(self) -> int:
        return sum(item.clicks for item in self.rounds)

    def summary(self) -> str:
        lines = [
            "分组「{}」流程「{}」执行完毕".format(self.group, self.flow),
            "  轮次   : 完成 {} / 失败 {}（要求 {}）".format(
                self.completed, self.failed,
                "无限" if self.requested is None else self.requested),
            "  总耗时 : {:.1f}s".format(self.duration),
            "  模型判定: {} 次".format(self.probes),
            "  点击   : {} 次".format(self.clicks),
        ]
        if self.stopped:
            lines.append("  已中止 : {}".format(self.stop_reason or "外部请求"))
        durations = [item.duration for item in self.rounds if item.ok and item.duration]
        if durations:
            lines.append("  单轮均值: {:.1f}s（最快 {:.1f}s / 最慢 {:.1f}s）".format(
                sum(durations) / len(durations), min(durations), max(durations)))
        for item in self.rounds:
            if item.ok:
                continue
            lines.append("  第 {} 轮失败: {}".format(
                item.index, item.error or ("整轮超时" if item.timed_out else "未知")))
        return "\n".join(lines)


class Context:
    """DSL 钩子拿到的运行期上下文。"""

    def __init__(self, runner: "Runner") -> None:
        self._runner = runner
        self.vars: Dict[str, Any] = {}
        self.log = log
        self.gfx = gfx

    @property
    def group(self) -> GroupRef:
        return self._runner.group

    @property
    def flow(self) -> Flow:
        return self._runner.flow

    @property
    def session(self) -> Session:
        return self._runner.session

    @property
    def matcher(self) -> ScreenMatcher:
        return self._runner.matcher

    @property
    def actor(self) -> Actor:
        return self._runner.actor

    @property
    def timer(self) -> CycleTimer:
        return self._runner.timer

    @property
    def round_index(self) -> int:
        return self._runner.round_index

    @property
    def times(self) -> Optional[int]:
        return self._runner.times

    @property
    def shots(self) -> Tuple[ShotRef, ...]:
        return self._runner.group.shots

    def shot(self, name: str) -> ShotRef:
        """按标注名 / 备注 / id 取一张截图。"""
        return self._runner.find_shot(name)

    def grab(self) -> bytes:
        """截当前画面，返回 PNG 字节。"""
        png, _frame = self.session.grab()
        return png

    def matches(self, name: str) -> Verdict:
        """当前画面是不是这张图。"""
        return self.matcher.matches(self._runner.find_shot(name))

    def compare(self, left: Any, right: Any) -> Verdict:
        """任意两张图互比。"""
        return self.matcher.compare(left, right)

    def click_label(self, name: str, label: Optional[str] = None,
                    settle: Optional[float] = None) -> ClickOutcome:
        """点某张图上的某个标注。"""
        shot = self._runner.find_shot(name)
        return self.actor.click_label(shot, label, settle=settle)

    def click_logical(self, point: Point) -> ClickResult:
        """点一个基准逻辑坐标。"""
        return self.session.click_logical(point)

    def click_screen(self, point: Tuple[int, int]) -> ClickResult:
        """点一个屏幕绝对坐标。"""
        return self.session.click_screen(point)

    def wait(self, seconds: float) -> None:
        """睡一会。"""
        self._runner.sleep(max(0.0, float(seconds)))

    def stop(self, reason: str = "") -> None:
        """优雅停止，跑完当前步骤就退出。"""
        self._runner.stop(reason or "DSL 请求停止")

    def fail(self, message: str) -> None:
        """立即中止并报错。"""
        raise RunnerError(message)


class Runner:
    """主循环。"""

    def __init__(
        self,
        group: GroupRef,
        flow: Flow,
        session: Session,
        matcher: ScreenMatcher,
        actor: Actor,
        timer: Optional[CycleTimer] = None,
        times: Optional[int] = None,
        round_timeout: Optional[float] = None,
        continue_on_error: bool = False,
        dry_run: bool = False,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.group = group
        self.flow = flow
        self.session = session
        self.matcher = matcher
        self.actor = actor
        self.timer = timer if timer is not None else CycleTimer()
        self.times = times
        self.continue_on_error = continue_on_error
        self.dry_run = dry_run
        self.sleep = sleep
        self.clock = clock
        self.prefix = group.timing_prefix()
        self.probe_key = "{}:probe".format(self.prefix)
        self.round_timeout = float(
            round_timeout if round_timeout is not None
            else (flow.round_timeout or settings.RUNNER_ROUND_TIMEOUT))
        self.context = Context(self)
        self.round_index = 0
        self._stopped = False
        self._stop_reason = ""
        self.steps: List[ResolvedStep] = []
        self.entry_indexes: List[int] = []

    def stop(self, reason: str = "") -> None:
        """请求停止。"""
        self._stopped = True
        self._stop_reason = reason

    @property
    def stopped(self) -> bool:
        return self._stopped

    def find_shot(self, name: str) -> ShotRef:
        """按标注名 / 备注 / 截图 id 定位一张图。"""
        if not isinstance(name, str) or not name.strip():
            raise StepResolveError("截图名不能为空")
        wanted = name.strip()
        hits = self.group.by_label(wanted)
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise StepResolveError("标注「{}」出现在 {} 张截图里（{}），请用 shot= 指明".format(
                wanted, len(hits), ", ".join(item.id for item in hits)))
        by_note = self.group.by_note(wanted)
        if len(by_note) == 1:
            return by_note[0]
        if len(by_note) > 1:
            raise StepResolveError("备注「{}」对应 {} 张截图，请用 shot= 指明".format(
                wanted, len(by_note)))
        for shot in self.group.shots:
            if shot.id == wanted:
                return shot
        raise StepResolveError(
            "分组「{}」里找不到「{}」。可用标注：{}；可用备注：{}".format(
                self.group.name, wanted,
                ", ".join(self.group.all_labels()) or "无",
                ", ".join(sorted({s.note for s in self.group.shots if s.note})) or "无"))

    def resolve(self) -> List[ResolvedStep]:
        """把 DSL 的 steps 解析成可执行步骤。"""
        resolved: List[ResolvedStep] = []
        for index, item in enumerate(self.flow.steps):
            shot = self.group.shot(item.shot) if item.shot else self.find_shot(item.target)
            annotation = self._resolve_annotation(item, shot)
            resolved.append(ResolvedStep(
                step=item,
                shot=shot,
                annotation=annotation,
                timeout=float(item.timeout if item.timeout is not None
                              else settings.RUNNER_STEP_TIMEOUT),
                interval=float(item.interval if item.interval is not None
                               else settings.RUNNER_PROBE_INTERVAL),
            ))
        self.steps = resolved
        self.entry_indexes = self._entry_indexes(resolved)
        return resolved

    def _entry_indexes(self, resolved: List[ResolvedStep]) -> List[int]:
        """把 flow.entry 里的名字映射到 steps 下标，顺序即探测优先级。"""
        indexes: List[int] = []
        for wanted in self.flow.entry:
            position = next((index for index, item in enumerate(resolved)
                             if wanted in {item.step.target, item.step.click or "",
                                           item.step.label or "", item.name}), None)
            if position is None:
                raise StepResolveError("entry 里的「{}」对不上任何一步".format(wanted))
            if position not in indexes:
                indexes.append(position)
        return indexes

    def _resolve_annotation(self, item: Step, shot: ShotRef) -> Optional[AnnotationRef]:
        label = item.click or (item.target if shot.find(item.target) else None)
        if label:
            annotation = shot.find(label)
            if annotation is None:
                raise StepResolveError("截图 {} 里没有名为「{}」的标注，可选：{}".format(
                    shot.id, label, ", ".join(shot.labels()) or "无"))
            return annotation
        if not shot.annotations:
            return None
        return shot.only()

    def run(self) -> RunReport:
        """执行主循环。"""
        if not self.steps:
            self.resolve()
        report = RunReport(group=self.group.name, flow=self.flow.name,
                           requested=self.times, steps_per_round=len(self.steps))
        started = self.clock()
        log.info("开始执行：%s，%d 步，轮次=%s，整轮超时 %.0fs%s",
                 self.group.describe(), len(self.steps),
                 "无限" if self.times is None else self.times, self.round_timeout,
                 "，入口探测 " + "→".join(self.steps[i].name for i in self.entry_indexes)
                 if self.entry_indexes else "")
        for index, item in enumerate(self.steps, 1):
            log.info("  步骤 %d: %s", index, item.describe())
        if self.dry_run:
            log.info("--dry-run：只解析不执行")
            report.duration = self.clock() - started
            return report

        self._hook("before_run", self.context)
        try:
            while not self._stopped:
                if self.times is not None and self.round_index >= self.times:
                    break
                self.round_index += 1
                log.info("=== 第 %d 轮%s ===", self.round_index,
                         "" if self.times is None else " / {}".format(self.times))
                round_report = self._run_round(self.round_index)
                report.rounds.append(round_report)
                if not round_report.ok and not self.continue_on_error:
                    break
        except KeyboardInterrupt:
            self._stopped = True
            self._stop_reason = "用户中断（Ctrl-C）"
            log.warning("收到 Ctrl-C，停止执行")
        finally:
            report.duration = self.clock() - started
            report.stopped = self._stopped
            report.stop_reason = self._stop_reason
            report.probes = self.matcher.calls
            self._hook("after_run", self.context, report)
            log.info("%s", report.summary())
            for line in self.timer.describe_summary(self.prefix).splitlines():
                log.info("%s", line)
        return report

    def _run_round(self, index: int) -> RoundReport:
        report = RoundReport(index=index)
        cycle = self.timer.begin("{}:round".format(self.prefix))
        deadline = self.clock() + self.round_timeout
        self._hook("on_round_started", self.context)
        try:
            start, prescreened = self._locate_entry(deadline)
            for position, item in enumerate(self.steps[start:], start):
                if self._stopped:
                    report.error = report.error or "已请求停止"
                    break
                if self.clock() >= deadline:
                    report.timed_out = True
                    report.error = "整轮超时（{:.0f}s），卡在第 {} 步「{}」".format(
                        self.round_timeout, position + 1, item.name)
                    log.warning("%s", report.error)
                    break
                step_report = self._run_step(item, position, deadline, prescreened)
                prescreened = None
                report.steps.append(step_report)
                log.info("  %s", step_report.describe())
                if step_report.skipped:
                    continue
                if not step_report.matched:
                    report.error = "第 {} 步「{}」等不到：{}".format(
                        position + 1, item.name, step_report.error or "超时")
                    break
            else:
                report.ok = True
            report.duration = self.timer.commit(cycle)
        except RunnerError as exc:
            self.timer.discard(cycle, str(exc))
            report.duration = cycle.elapsed()
            report.error = str(exc)
            log.error("第 %d 轮中止：%s", index, exc)
        except Exception as exc:
            self.timer.discard(cycle, "{}: {}".format(type(exc).__name__, exc))
            report.duration = cycle.elapsed()
            report.error = "{}: {}".format(type(exc).__name__, exc)
            log.exception("第 %d 轮出现未预期异常", index)
        if report.timed_out or report.error:
            report.ok = False
        self._hook("on_round_finished", self.context, report)
        return report

    def _locate_entry(self, deadline: float) -> Tuple[int, Optional[Verdict]]:
        """按 flow.entry 的顺序探测当前画面，决定本轮从第几步起跑。"""
        if not self.entry_indexes or self.dry_run or self._stopped:
            return 0, None
        if self.clock() >= deadline:
            return 0, None
        for index in self.entry_indexes:
            item = self.steps[index]
            verdict = self.matcher.matches(item.shot)
            if verdict.matched:
                if index:
                    log.info("  入口对齐：当前是「%s」（第 %d 步），从这一步起跑",
                             item.name, index + 1)
                return index, verdict
            log.debug("    入口探测未命中：%s", verdict.describe())
        log.warning("  入口探测：%d 张候选都不是当前画面，从第 1 步「%s」开始等",
                    len(self.entry_indexes), self.steps[0].name)
        return 0, None


    def _run_step(self, item: ResolvedStep, position: int, deadline: float,
                  prescreened: Optional[Verdict] = None) -> StepReport:
        report = StepReport(index=position, name=item.name, shot_id=item.shot.id)
        key = item.timing_key(self.prefix)
        timeout = min(item.timeout, max(1.0, deadline - self.clock()))
        plan = self.timer.plan(key, timeout=timeout, interval=item.interval,
                               probe_key=self.probe_key)
        blind = (item.step.blind_wait if item.step.blind_wait is not None
                 else plan.blind_wait)
        blind = max(0.0, min(blind, timeout - settings.TIMING_FINE_WINDOW))
        log.info("  等「%s」：%s（盲等 %.1fs，间隔 %.1fs）", item.name,
                 plan.reason or "默认", blind, plan.interval)

        cycle = self.timer.begin(key)
        started = self.clock()
        if prescreened is not None:
            report.probes = 1
            report.score = prescreened.score
            verdict: Optional[Verdict] = prescreened
        else:
            verdict = None
            if blind > 0:
                self.sleep(blind)
            while True:
                if self._stopped:
                    break
                verdict = self.matcher.matches(item.shot)
                report.probes += 1
                report.score = verdict.score
                if verdict.matched:
                    break
                log.debug("    未命中：%s", verdict.describe())
                remaining = timeout - (self.clock() - started)
                if remaining <= 0:
                    break
                self.sleep(min(plan.interval, remaining))
        report.waited = self.clock() - started
        report.matched = bool(verdict and verdict.matched)

        if not report.matched:
            self.timer.discard(cycle, "等不到「{}」".format(item.name))
            report.error = "超时 {:.1f}s，{} 次判定都没命中（最后可信度 {:.2f}）".format(
                timeout, report.probes, report.score)
            handled = self._call_timeout_hooks(item)
            if handled:
                report.skipped = True
                report.error = "超时后由钩子接管"
                log.warning("  「%s」%s", item.name, report.error)
            elif item.step.optional:
                report.skipped = True
                report.error = "可跳过步骤，未命中"
                log.warning("  「%s」%s", item.name, report.error)
            return report

        self.timer.commit(cycle)
        if verdict is not None:
            log.info("  命中「%s」：%s", item.name, verdict.describe())

        proceed = self._call_match_hooks(item)
        if not proceed:
            report.skipped = True
            report.clicked = False
            return report

        if item.annotation is None:
            log.info("  「%s」没有可点标注，只识别", item.name)
            return report

        outcome = self.actor.click_annotation(item.shot, item.annotation,
                                              settle=item.step.settle)
        report.clicked = outcome.ok
        report.click = item.annotation.label
        if not outcome.ok:
            report.error = outcome.reason
            log.warning("  点击未送达：%s", outcome.describe())
        return report

    def _call_match_hooks(self, item: ResolvedStep) -> bool:
        for hook in (self.flow.hook("on_step_matched"), item.step.on_match):
            if hook is None:
                continue
            result = self._invoke("on_step_matched", hook, self.context, item.step)
            if result is False:
                log.info("  钩子要求跳过「%s」的点击", item.name)
                return False
        return True

    def _call_timeout_hooks(self, item: ResolvedStep) -> bool:
        handled = False
        for hook in (item.step.on_timeout, self.flow.hook("on_step_timeout")):
            if hook is None:
                continue
            if self._invoke("on_step_timeout", hook, self.context, item.step) is True:
                handled = True
        return handled

    def _hook(self, name: str, *args: Any) -> None:
        hook = self.flow.hook(name)
        if hook is None:
            return
        self._invoke(name, hook, *args)

    def _invoke(self, name: str, hook: Callable, *args: Any) -> Any:
        try:
            return hook(*args)
        except RunnerError:
            raise
        except Exception as exc:
            raise RunnerError("DSL 钩子 {} 抛异常 {}: {}".format(
                name, type(exc).__name__, exc))


def build_runner(
    group: GroupRef,
    flow: Flow,
    session: Optional[Session] = None,
    judge: Optional[Any] = None,
    timer: Optional[CycleTimer] = None,
    times: Optional[int] = None,
    round_timeout: Optional[float] = None,
    continue_on_error: bool = False,
    dry_run: bool = False,
    humanize: bool = True,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Runner:
    """组装一个可直接 run() 的 Runner。"""
    from actions.mouse import HumanMouse
    from similarity.llm_judge import OmniJudge

    session = session or Session()
    if not humanize:
        session.mouse = HumanMouse(humanize=False)
        session.mouse.pid_provider = session._pid
    active_timer = timer if timer is not None else CycleTimer()
    matcher = ScreenMatcher(session, judge=judge or OmniJudge(), timer=active_timer,
                            probe_key="{}:probe".format(group.timing_prefix()))
    actor = Actor(session, sleep=sleep)
    return Runner(
        group=group, flow=flow, session=session, matcher=matcher, actor=actor,
        timer=active_timer, times=times, round_timeout=round_timeout,
        continue_on_error=continue_on_error, dry_run=dry_run, sleep=sleep, clock=clock,
    )
