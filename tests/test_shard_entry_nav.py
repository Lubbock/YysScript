"""式神碎片「两种入口同时监听」的行为测试。

**为什么要同时监听**：重新挑战的入口有两种 ——
1. 结算后直接回到挑战按钮界面；
2. 结算后被踢回探索章节界面，要导航一圈（Boss 头像 -> 入口面板 -> 列表行）才回到挑战界面。

这两种**跑着跑着会交替出现，不是开局能选定的**，所以没有模式开关：引擎一次性 watch
两种入口涉及的全部界面，屏幕上实际出现什么就走什么。

剧本（假游戏）：
    挑战界面 --点挑战--> 战斗(30s) --时间到--> 结算界面
    结算 --点结算--> 按 script 决定回「挑战界面」还是「章节界面」
    章节界面 --点头像--> 入口面板 --点面板--> 列表行 --点行--> 挑战界面

两处模板误命中也在假游戏里复现（都是真机实测到的）：
- 挑战界面上「碎片列表行」也会命中（实测 0.791 > 阈值 0.7）；
- 列表行界面上「章节 Boss 头像」也会命中（行里含同一个头像）。
watch 顺序必须让更确定的模板赢：挑战按钮 > 列表行 > 入口面板 > Boss 头像。

不截屏不点击：machine 与 controller 都是假的，时钟也是假的。
"""
import pytest

from config import settings
from core.errors import FlowAbortedError
from core.timing import CycleTimer
from flows.shard.shard_flow import NAV_STUCK_RETRY, ShardEntryNav, ShardFlow
from states.machine import Detection
from states.shard_battle_end import SHARD_BATTLE_END
from states.shard_chapter_boss import SHARD_CHAPTER_BOSS
from states.shard_challenge import SHARD_CHALLENGE
from states.shard_fragment_entry import SHARD_FRAGMENT_ENTRY
from states.shard_fragment_row import SHARD_FRAGMENT_ROW
from storage.database import Database
from storage.duration_store import DurationStore
from vision.types import Box, Match


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += max(0.0, seconds)


def make_match(state) -> Match:
    return Match(box=Box(0, 0, 10, 10), score=0.9, template=state.template)


class FakeShardGame:
    """假游戏：识别看 self.screen，点击按模板切换界面。"""

    #: 每个界面上能匹配到的状态。两处误命中是故意留下的（见模块 docstring）
    SCREENS = {
        "challenge": (SHARD_CHALLENGE, SHARD_FRAGMENT_ROW),   # 列表行模板误命中 0.791
        "battle": (),
        "end": (SHARD_BATTLE_END,),
        "chapter": (SHARD_CHAPTER_BOSS,),
        "entry": (SHARD_FRAGMENT_ENTRY,),
        "row": (SHARD_FRAGMENT_ROW, SHARD_CHAPTER_BOSS),      # 行里含同一个头像
    }

    def __init__(self, clock, battle_seconds: float = 30.0,
                 script=("challenge",)) -> None:
        """script：每次点完结算之后去的界面，按顺序消费，用完了就一直用最后一个。"""
        self.clock = clock
        self.battle_seconds = battle_seconds
        self.script = list(script)
        self.screen = "challenge"
        self.clicks = []
        self._battle_until = None
        self._settle_index = 0

    def next_screen_after_end(self) -> str:
        index = min(self._settle_index, len(self.script) - 1)
        self._settle_index += 1
        return self.script[index]

    # ------------------------------------------------------------ machine
    def detect_first(self, candidates):
        if self._battle_until is not None:
            if self.clock() < self._battle_until:
                return None
            self._battle_until = None
            self.screen = "end"
        present = self.SCREENS[self.screen]
        for candidate in candidates:          # 顺序即优先级
            if candidate in present:
                return Detection(state=candidate, match=make_match(candidate))
        return None

    # ---------------------------------------------------------- controller
    def click(self, target, **kwargs):
        template = getattr(target, "template", None)
        self.clicks.append(template)
        if template == SHARD_CHALLENGE.template:
            self.screen = "battle"
            self._battle_until = self.clock() + self.battle_seconds
        elif template == SHARD_BATTLE_END.template:
            self.screen = self.next_screen_after_end()
        elif template == SHARD_CHAPTER_BOSS.template:
            self.screen = "entry"
        elif template == SHARD_FRAGMENT_ENTRY.template:
            self.screen = "row"
        elif template == SHARD_FRAGMENT_ROW.template:
            self.screen = "challenge"
        return getattr(target, "center", None)


@pytest.fixture()
def clock():
    return FakeClock()


@pytest.fixture()
def store(tmp_path):
    return DurationStore(database=Database(tmp_path / "shard.db"))


def make_flow(game, clock, store, times=2):
    return ShardFlow(
        controller=game,
        machine=game,
        times=times,
        timer=CycleTimer(store=store, clock=clock, adaptive=False),
        clock=clock,
        sleeper=clock.sleep,
    )


CH, END = SHARD_CHALLENGE.template, SHARD_BATTLE_END.template
BOSS, ENTRY, ROW = (SHARD_CHAPTER_BOSS.template, SHARD_FRAGMENT_ENTRY.template,
                    SHARD_FRAGMENT_ROW.template)
NAV = (BOSS, ENTRY, ROW)


# --------------------------------------------------------------------------- #
# 核心：两种入口在同一次运行里交替出现
# --------------------------------------------------------------------------- #
def test_both_entry_types_alternate_in_one_run(clock, store):
    """同一次运行里入口来回变：回章节就导航，回挑战就直接开战，不用重启也不用选模式。"""
    game = FakeShardGame(clock, script=["chapter", "challenge", "chapter"])
    flow = make_flow(game, clock, store, times=4)

    flow.run()

    assert game.clicks == [
        CH, END,                     # 第 1 轮：结算后被踢回章节界面
        BOSS, ENTRY, ROW, CH, END,   # 第 2 轮：导航一圈 -> 结算后直接回挑战界面
        CH, END,                     # 第 3 轮：直接开战 -> 结算后又回章节界面
        BOSS, ENTRY, ROW, CH, END,   # 第 4 轮：再导航一圈
    ]
    assert game.clicks.count(BOSS) == 2, "两种入口各走了两次"
    assert len(store.samples("shard:round")) == 4


def test_settlement_back_to_challenge_needs_no_navigation(clock, store):
    """入口一直是「直接回挑战界面」时，一个导航模板都不该点（与改造前行为一致）。"""
    game = FakeShardGame(clock, script=["challenge"])
    flow = make_flow(game, clock, store, times=3)

    flow.run()

    assert game.clicks == [CH, END, CH, END, CH, END]
    assert not [c for c in game.clicks if c in NAV]


def test_settlement_back_to_chapter_navigates(clock, store):
    """入口一直是「回章节界面」时，每轮开局自己导航进去。"""
    game = FakeShardGame(clock, script=["chapter"])
    flow = make_flow(game, clock, store, times=2)

    flow.run()

    assert game.clicks == [CH, END, BOSS, ENTRY, ROW, CH, END]
    assert len(store.samples("shard:round")) == 2


# --------------------------------------------------------------------------- #
# 无阶段门控：一轮可以从任意界面开始
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("start,expected_prefix", [
    ("chapter", [BOSS, ENTRY, ROW]),
    ("entry", [ENTRY, ROW]),
    ("row", [ROW]),
    ("challenge", []),
])
def test_starts_from_any_screen(clock, store, start, expected_prefix):
    """开局停在哪都能接着走（例如上次被中断）：看到哪个导航界面就点哪个。"""
    game = FakeShardGame(clock, script=["challenge"])
    game.screen = start
    flow = make_flow(game, clock, store, times=1)

    flow.run()

    assert game.clicks == expected_prefix + [CH, END]


# --------------------------------------------------------------------------- #
# watch 顺序：两处已知的模板误命中
# --------------------------------------------------------------------------- #
def test_challenge_screen_prefers_challenge_over_row_false_positive(clock, store):
    """挑战界面上列表行模板也会命中（实测 0.791），必须让挑战按钮赢。

    这条是真机踩过的坑：顺序反了会在挑战界面上去点列表行，整轮走偏。
    """
    game = FakeShardGame(clock)
    game.screen = "challenge"
    engine = make_flow(game, clock, store, times=1).create_engine()
    ShardEntryNav(engine).attach()

    detection = engine.observe()

    assert detection is not None
    assert detection.state is SHARD_CHALLENGE


def test_row_screen_prefers_row_over_boss_portrait(clock, store):
    """列表行界面上两个模板都命中时，必须取更具体的列表行。"""
    game = FakeShardGame(clock)
    game.screen = "row"
    engine = make_flow(game, clock, store, times=1).create_engine()
    ShardEntryNav(engine).attach()

    detection = engine.observe()

    assert detection is not None
    assert detection.state is SHARD_FRAGMENT_ROW


def test_watch_order_is_stable_after_battle_cycle_attaches(clock, store):
    """两个订阅方都 watch 之后，优先级顺序仍然是 挑战 > 列表行 > 面板 > 头像。"""
    game = FakeShardGame(clock)
    game.screen = "challenge"
    flow = make_flow(game, clock, store, times=1)
    engine = flow.create_engine()
    ShardEntryNav(engine).attach()
    keys = [getattr(state, "key", state) for state in engine.watched]

    assert keys.index(SHARD_CHALLENGE.key) < keys.index(SHARD_FRAGMENT_ROW.key)
    assert keys.index(SHARD_FRAGMENT_ROW.key) < keys.index(SHARD_FRAGMENT_ENTRY.key)
    assert keys.index(SHARD_FRAGMENT_ENTRY.key) < keys.index(SHARD_CHAPTER_BOSS.key)
    assert engine.observe().state is SHARD_CHALLENGE


# --------------------------------------------------------------------------- #
# 兜底：点击被吞 / 模式开关已下线
# --------------------------------------------------------------------------- #
def test_stuck_navigation_retries_and_aborts_within_budget(clock, store):
    """界面一直不变（游戏吞点击）：先补点，最后由挑战预算兜底中止，不会无限点下去。"""
    game = FakeShardGame(clock)
    game.screen = "chapter"
    # 点击「送达」但不切换界面 -> 导航永远走不完
    game.click = lambda target, **kw: (
        game.clicks.append(getattr(target, "template", None)),
        getattr(target, "center", None),
    )[1]
    flow = make_flow(game, clock, store, times=1)

    with pytest.raises(FlowAbortedError):
        flow.run()

    boss_clicks = game.clicks.count(BOSS)
    assert boss_clicks >= 2, "卡住后应该补点，而不是只点一次就干等"
    # 补点频率受 NAV_STUCK_RETRY 约束：不会每拍都点
    assert boss_clicks <= flow.CHALLENGE_TIMEOUT / NAV_STUCK_RETRY + 2
    assert clock.now <= flow.CHALLENGE_TIMEOUT + settings.DEFAULT_WAIT_INTERVAL * 2


def test_flow_has_no_mode_switch(clock, store):
    """入口是自动识别的，ShardFlow 不再接受 mode 参数。"""
    game = FakeShardGame(clock)
    with pytest.raises(TypeError):
        ShardFlow(controller=game, machine=game, mode="chapter")


def test_cli_has_no_shard_mode_argument():
    """命令行上也不该再有 --shard-mode（留着会让人以为要开局选定入口）。"""
    from main import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["shard", "--times", "1", "--shard-mode", "chapter"])
