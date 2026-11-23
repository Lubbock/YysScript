"""分组 DSL：声明式 steps + 钩子。

DSL 就是分组目录下的一个 Python 文件（默认 `flow.py`），主流程发现它就自动加载。
文件里**不需要任何 import** —— 加载时会把下面这些名字注入进去：

    step(target, ...)   声明一步：等到 target 这张图出现，然后点某个标注
    gfx                 图形算法库（runner/gfx.py），可直接调 gfx.brightness() 等
    shots               本分组全部截图（ShotRef 列表，按采集时间排序）
    group               本分组信息（GroupRef）
    labels              本分组全部标注名（去重）
    log                 日志器
    settings            全局配置

最小可用的 DSL：

    steps = [
        step("挑战"),
        step("完成", timeout=240),
    ]

跑完最后一步自动回到第一步，循环由主流程的 --times 控制。
一轮从 steps[0] 跑到最后一格；如果真实起点可能在序列中间
（例如手机卡在「碎片副本选中」），声明 entry，每轮开头先探测当前是哪张图，
命中哪一步就从那一步起跑：

    entry = ["挑战", "碎片副本选中", "式神选中", "完成"]

复杂逻辑写钩子函数（可选，函数名固定）：

    def on_step_matched(ctx, st):   # 命中后、点击前；返回 False 跳过本次点击
    def on_step_timeout(ctx, st):   # 超时兜底；返回 True 表示已自愈，继续下一步
    def on_round_started(ctx):
    def on_round_finished(ctx, report):
    def before_run(ctx):
    def after_run(ctx, report):

ctx 是运行期上下文（runner/engine.Context），能截屏、比对、点任意标注、读写变量。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from config import settings
from core.logger import get_logger
from runner import gfx
from runner.errors import DslError
from runner.group import GroupRef

log = get_logger(__name__)

HOOKS = (
    "before_run",
    "after_run",
    "on_round_started",
    "on_round_finished",
    "on_step_matched",
    "on_step_timeout",
)


@dataclass(frozen=True)
class Step:
    """一步：等一张图出现，然后点一个标注。"""

    target: str
    click: Optional[str] = None
    shot: Optional[str] = None
    label: Optional[str] = None
    timeout: Optional[float] = None
    interval: Optional[float] = None
    blind_wait: Optional[float] = None
    settle: Optional[float] = None
    optional: bool = False
    on_match: Optional[Callable] = None
    on_timeout: Optional[Callable] = None

    @property
    def name(self) -> str:
        return self.label or self.click or self.target

    def describe(self) -> str:
        parts = [self.name]
        if self.shot:
            parts.append("shot={}".format(self.shot))
        if self.interval is not None:
            parts.append("间隔{:.1f}s".format(self.interval))
        if self.blind_wait is not None:
            parts.append("盲等{:.0f}s".format(self.blind_wait))
        if self.optional:
            parts.append("可跳过")
        return " ".join(parts)


def step(
    target: str,
    click: Optional[str] = None,
    shot: Optional[str] = None,
    label: Optional[str] = None,
    timeout: Optional[float] = None,
    interval: Optional[float] = None,
    blind_wait: Optional[float] = None,
    settle: Optional[float] = None,
    optional: bool = False,
    on_match: Optional[Callable] = None,
    on_timeout: Optional[Callable] = None,
) -> Step:
    """声明一步。

    target     : 期望出现的界面，用标注名 / 截图备注 / 截图 id 指认
    click      : 命中后点哪个标注名，默认与 target 同名
    shot       : 标注名有歧义时，显式指定截图 id
    timeout    : 这一步最多等多少秒
    interval   : 两次判定之间的额外间隔（判定本身还要 1~3 秒）
    blind_wait : 强制盲等秒数，覆盖自适应等待算出来的值
    settle     : 命中后、点击前的停顿秒数
    optional   : True 时等不到就跳过这一步，不算失败
    on_match   : 本步专属的命中钩子
    on_timeout : 本步专属的超时钩子
    """
    if not isinstance(target, str) or not target.strip():
        raise DslError("step() 的第一个参数必须是非空的标注名 / 备注 / 截图 id")
    return Step(
        target=target.strip(),
        click=click.strip() if isinstance(click, str) else click,
        shot=shot.strip() if isinstance(shot, str) else shot,
        label=label.strip() if isinstance(label, str) else label,
        timeout=None if timeout is None else float(timeout),
        interval=None if interval is None else float(interval),
        blind_wait=None if blind_wait is None else float(blind_wait),
        settle=None if settle is None else float(settle),
        optional=bool(optional),
        on_match=on_match,
        on_timeout=on_timeout,
    )


@dataclass(frozen=True)
class Flow:
    """加载好的 DSL。"""

    name: str
    steps: Tuple[Step, ...]
    round_timeout: Optional[float]
    hooks: Dict[str, Callable]
    namespace: Dict[str, Any]
    source: Path
    entry: Tuple[str, ...] = ()

    def hook(self, name: str) -> Optional[Callable]:
        return self.hooks.get(name)


def build_namespace(group: GroupRef) -> Dict[str, Any]:
    """DSL 的执行命名空间。"""
    return {
        "__name__": "group_flow",
        "__builtins__": __builtins__,
        "step": step,
        "Step": Step,
        "gfx": gfx,
        "log": log,
        "group": group,
        "shots": list(group.shots),
        "labels": group.all_labels(),
        "settings": settings,
    }


def load_flow(path: Path, group: GroupRef) -> Flow:
    """加载并校验 DSL 文件。"""
    path = Path(path)
    if not path.is_file():
        raise DslError("DSL 文件不存在: {}（用 --init-dsl 生成一份）".format(path))
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DslError("读取 DSL 失败 {}: {}".format(path, exc))

    namespace = build_namespace(group)
    try:
        exec(compile(source, str(path), "exec"), namespace)
    except DslError:
        raise
    except SyntaxError as exc:
        raise DslError("DSL 语法错误 {} 第 {} 行：{}".format(path.name, exc.lineno, exc.msg))
    except Exception as exc:
        raise DslError("DSL 执行失败 {}：{}: {}".format(path.name, type(exc).__name__, exc))

    raw_steps = namespace.get("steps")
    if raw_steps is None:
        raise DslError("{} 里没有定义 steps 列表".format(path.name))
    if isinstance(raw_steps, Step):
        raw_steps = [raw_steps]
    if not isinstance(raw_steps, (list, tuple)):
        raise DslError("steps 必须是列表，实际是 {}".format(type(raw_steps).__name__))
    if not raw_steps:
        raise DslError("steps 不能为空")
    for index, item in enumerate(raw_steps, 1):
        if not isinstance(item, Step):
            raise DslError("steps[{}] 不是 step() 的返回值，而是 {}".format(
                index - 1, type(item).__name__))
    hooks = {name: namespace[name] for name in HOOKS if callable(namespace.get(name))}
    name = namespace.get("name") or group.name
    round_timeout = namespace.get("round_timeout")
    entry = _entry_names(namespace.get("entry"), raw_steps)
    return Flow(
        name=str(name),
        steps=tuple(raw_steps),
        round_timeout=None if round_timeout is None else float(round_timeout),
        hooks=hooks,
        namespace=namespace,
        source=path,
        entry=entry,
    )


def _entry_names(entry: Any, raw_steps: Sequence[Step]) -> Tuple[str, ...]:
    """校验 entry 声明：None / "all" / 名称列表。"""
    if entry is None:
        return ()
    if isinstance(entry, str):
        if entry.strip().lower() in ("all", "*"):
            return tuple(step.target for step in raw_steps)
        wanted = [entry.strip()]
    elif isinstance(entry, (list, tuple)):
        wanted = [str(item).strip() for item in entry]
    else:
        raise DslError("entry 只能是 None、\"all\" 或名称列表，实际是 {}".format(
            type(entry).__name__))
    if not wanted:
        return ()
    known = set()
    for item in raw_steps:
        known.update(name for name in (item.target, item.click, item.label) if name)
    unknown = [item for item in wanted if item and item not in known]
    if unknown:
        raise DslError("entry 里的 {} 不是任何 step 的 target / click / label；"
                       "可用：{}".format("、".join(unknown), "、".join(sorted(known))))
    return tuple(item for item in wanted if item)


def load_group_flow(group: GroupRef) -> Flow:
    """载入分组自带的 DSL。"""
    if not group.has_dsl():
        raise DslError(
            "分组「{}」没有 {}。生成一份：python main.py --group {} --init-dsl".format(
                group.name, settings.RUNNER_DSL_FILENAME, group.name))
    return load_flow(group.dsl_path, group)


def scaffold(group: GroupRef) -> str:
    """按现有标注生成一份 DSL 草稿。"""
    lines: List[str] = [
        '"""分组「{}」的执行顺序。'.format(group.name),
        "",
        "本文件由 main.py --init-dsl 生成，按截图采集时间排了个初始顺序，",
        "请照着实际的游戏流程调整 steps 的顺序与超时。",
        "",
        "step(target, click=None, shot=None, timeout=None, interval=None,",
        "     blind_wait=None, settle=None, optional=False, on_match=None, on_timeout=None)",
        "  target     期望出现的界面：标注名 / 截图备注 / 截图 id",
        "  click      命中后点哪个标注，默认与 target 同名",
        "  timeout    这一步最多等多少秒（默认 {:.0f}）".format(settings.RUNNER_STEP_TIMEOUT),
        "  blind_wait 强制盲等秒数，覆盖自适应等待",
        "  optional   True 时等不到就跳过，不算失败",
        '"""',
        "",
        'name = "{}"'.format(group.name),
        "round_timeout = {:.0f}".format(settings.RUNNER_ROUND_TIMEOUT),
        "",
        "steps = [",
    ]
    if not group.shots:
        lines.append("    # 这个分组还没有截图，先去标注采集页捕获并标注")
    for shot in group.shots:
        if not shot.annotations:
            lines.append('    # 截图 {} 没有标注，已跳过'.format(shot.id))
            continue
        primary = shot.annotations[0]
        if len(shot.annotations) == 1:
            lines.append('    step("{}"),  # {}'.format(primary.label or shot.id, shot.id))
        else:
            lines.append('    step("{}", click="{}"),  # {} 有 {} 个标注：{}'.format(
                primary.label or shot.id, primary.label, shot.id,
                len(shot.annotations), ", ".join(shot.labels())))
    lines += [
        "]",
        "",
        "",
        "def on_step_timeout(ctx, st):",
        '    """超时兜底：返回 True 表示已自愈，继续下一步。"""',
        '    ctx.log.warning("步骤 %s 等不到，中止本轮", st.name)',
        "    return False",
        "",
    ]
    return "\n".join(lines)


def write_scaffold(group: GroupRef, overwrite: bool = False) -> Path:
    """把草稿写进分组目录。"""
    path = group.dsl_path
    if path.exists() and not overwrite:
        raise DslError("{} 已存在，加 --force 覆盖".format(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(scaffold(group), encoding="utf-8")
    return path
