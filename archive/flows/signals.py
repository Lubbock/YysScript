"""流程事件定义：topic 常量 + 事件对象。

这是「识别到状态 -> 推事件 -> 订阅方决定动作」这条链路的**词汇表**：
- `core/bus.py` 只提供通用的发布订阅，不认识任何领域概念；
- 本模块定义流程领域的事件类型与 topic 命名；
- `flows/engine.py` 是唯一的生产者（除 `action.performed` / `round.done`
  由订阅方发出），`flows/battle_cycle.py` 与各 flow 是消费者。

topic 命名规则（点分层级，配合 EventBus 的通配符订阅）：

    flow.started / flow.finished          整个流程的首尾
    round.started / round.finished        一轮（一次御魂 / 一场战斗）的首尾
    round.done                            订阅方 -> 引擎：这一轮我处理完了
    poll.completed                        每次截屏识图之后
    state.detected                        每次命中状态（含重复命中）
    state.entered.<KEY>                   状态发生跳变、进入 <KEY>
    state.exited.<KEY>                    状态发生跳变、离开 <KEY>
    state.unknown                         连续多次什么都没识别到
    state.timeout                         等待超时
    action.performed                      订阅方 -> 引擎：我点了什么
    timing.recorded                       一条计时样本入库

订阅示例：

    bus.subscribe("state.entered.SOUL_CHALLENGE", on_challenge)   # 只关心一个界面
    bus.subscribe("state.entered.*", on_any_entry)                # 关心所有跳变
    bus.subscribe("*", audit)                                     # 全量审计

新增一条业务规则 = 新增一个订阅方，**不用改 flow 本体**，这是本次解耦的目的。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Tuple

from core.timing import TimingSample

if TYPE_CHECKING:  # 仅类型标注：flows 层不在运行时额外拖入依赖
    from states.base import State
    from vision.types import Match

# --------------------------------------------------------------------------- #
# topic 常量
# --------------------------------------------------------------------------- #
TOPIC_FLOW_STARTED = "flow.started"
TOPIC_FLOW_FINISHED = "flow.finished"
TOPIC_ROUND_STARTED = "round.started"
TOPIC_ROUND_FINISHED = "round.finished"
TOPIC_ROUND_DONE = "round.done"
TOPIC_POLL_COMPLETED = "poll.completed"
TOPIC_STATE_DETECTED = "state.detected"
TOPIC_STATE_UNKNOWN = "state.unknown"
TOPIC_STATE_TIMEOUT = "state.timeout"
TOPIC_ACTION_PERFORMED = "action.performed"
#: 计时样本入库；事件类型是 core.timing.TimingSample（core 层不能反向依赖 flows）
TOPIC_TIMING_RECORDED = "timing.recorded"

#: 状态跳变 topic 的前缀，完整形式见 topic_for()
PREFIX_STATE_ENTERED = "state.entered"
PREFIX_STATE_EXITED = "state.exited"

#: 计时样本事件别名，方便订阅方从一个地方 import 全部事件类型
TimingEvent = TimingSample


def topic_for(prefix: str, state: Any) -> str:
    """拼出带状态 key 的 topic，例如 topic_for("state.entered", SOUL_CHALLENGE)
    -> "state.entered.SOUL_CHALLENGE"。

    state 可以是 State 对象，也可以直接是 key 字符串。
    """
    key = getattr(state, "key", state)
    return "{}.{}".format(prefix, key)


def state_key_of(event: Any) -> str:
    """从任意事件里取状态 key，取不到返回空串（订阅方写通用逻辑时用）。"""
    state = getattr(event, "state", None)
    if state is not None:
        return getattr(state, "key", str(state))
    return getattr(event, "state_key", "") or ""


# --------------------------------------------------------------------------- #
# 事件对象（全部 frozen：事件是事实，不该被订阅方改）
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FlowEvent:
    """流程级别的事件（开始 / 结束）。"""

    name: str
    rounds: int = 0
    total_seconds: float = 0.0
    aborted: bool = False
    reason: str = ""


@dataclass(frozen=True)
class RoundEvent:
    """一轮循环的事件。

    index   : 第几轮，从 1 开始
    duration: 本轮耗时（秒），仅 round.finished 有意义
    states  : 本轮依次识别到过的状态 key
    timed_out: 本轮是否因超时结束
    """

    index: int
    duration: float = 0.0
    states: Tuple[str, ...] = ()
    timed_out: bool = False
    reason: str = ""


@dataclass(frozen=True)
class PollEvent:
    """一次截屏识图的结果。

    index        : 本轮第几次识图
    cost         : 本次「截屏 + 模板匹配」耗时（秒）
    hit          : 是否命中
    unknown_streak: 连续未命中次数
    """

    index: int
    cost: float = 0.0
    hit: bool = False
    state_key: str = ""
    round_index: int = 0
    unknown_streak: int = 0


@dataclass(frozen=True)
class StateEvent:
    """状态命中 / 跳变。

    state   : states.base.State 对象
    match   : vision 的命中结果（屏幕绝对坐标），可能为 None
    score   : 匹配置信度
    waited  : 从本轮开始到命中经过的秒数
    previous: 跳变前的状态 key（仅 entered / exited 事件）
    """

    state: "State"
    match: Optional["Match"] = None
    score: float = 0.0
    round_index: int = 0
    waited: float = 0.0
    previous: str = ""

    @property
    def key(self) -> str:
        return getattr(self.state, "key", str(self.state))

    @property
    def center(self) -> Optional[Tuple[int, int]]:
        return self.match.center if self.match is not None else None


@dataclass(frozen=True)
class TimeoutEvent:
    """等待超时。key 是计时 key 或状态 key，便于订阅方区分是哪个阶段超时。"""

    key: str
    waited: float
    timeout: float
    round_index: int = 0
    states: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionEvent:
    """订阅方执行了一个动作（目前只有点击，预留 drag / scroll）。"""

    kind: str
    target: Any = None
    state_key: str = ""
    round_index: int = 0
    detail: str = ""
