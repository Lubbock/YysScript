"""式神碎片「章节入口」模式（--shard-mode chapter）的导航链测试。

剧本（假游戏）：
    挑战界面 --点挑战--> 战斗(30s) --时间到--> 结算界面
    结算 --点结算--> 章节界面(Boss 头像) --点头像--> 入口面板 --点面板--> 列表行
    列表行 --点行--> 挑战界面（回到循环起点）

列表行界面上同时能匹配到「列表行」和「章节 Boss 头像」两个模板（行里含同一个头像），
所以还要验证 detect_first 的 watch 顺序让列表行优先。

不截屏不点击：machine 与 controller 都是假的，时钟是假的。
"""
import pytest

from config import settings
from core.errors import ConfigError, FlowAbortedError
from core.timing import CycleTimer
from flows.shard.shard_flow import MODE_CHAPTER, MODE_SIMPLE, ShardFlow
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

    #: 每个界面上能匹配到的状态（列表行界面故意同时含 Boss 头像）
    SCREENS = {
        "challenge": (SHARD_CHALLENGE,),
        "battle": (),
        "end": (SHARD_BATTLE_END,),
        "chapter": (SHARD_CHAPTER_BOSS,),
        "entry": (SHARD_FRAGMENT_ENTRY,),
        "row": (SHARD_FRAGMENT_ROW, SHARD_CHAPTER_BOSS),
    }

    def __init__(self, clock, battle_seconds: float = 30.0,
                 after_end: str = "chapter") -> None:
        self.clock = clock
        self.battle_seconds = battle_seconds
        self.after_end = after_end
        self.screen = "challenge"
        self.clicks = []
        self._battle_until = None

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
            self.screen = self.after_end
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


def make_flow(game, clock, store, mode, times=2):
    return ShardFlow(
        controller=game,
        machine=game,
        times=times,
        mode=mode,
        timer=CycleTimer(store=store, clock=clock, adaptive=False),
        clock=clock,
        sleeper=clock.sleep,
    )


CH, END = SHARD_CHALLENGE.template, SHARD_BATTLE_END.template
BOSS, ENTRY, ROW = (SHARD_CHAPTER_BOSS.template, SHARD_FRAGMENT_ENTRY.template,
                    SHARD_FRAGMENT_ROW.template)


def test_chapter_mode_navigates_back_to_challenge(clock, store):
    """章节模式：结算后导航 头像->面板->列表行，再接上挑战按钮。"""
    game = FakeShardGame(clock, battle_seconds=30.0, after_end="chapter")
    flow = make_flow(game, clock, store, MODE_CHAPTER, times=2)

    flow.run()

    assert game.clicks == [CH, END, BOSS, ENTRY, ROW, CH, END]
    assert store.samples("shard:round"), "两轮都应记账"
    assert len(store.samples("shard:round")) == 2


def test_chapter_mode_starts_from_chapter_screen(clock, store):
    """开局就停在章节界面（例如上次被中断）也应能自己导航进去。"""
    game = FakeShardGame(clock, after_end="chapter")
    game.screen = "chapter"
    flow = make_flow(game, clock, store, MODE_CHAPTER, times=1)

    flow.run()

    assert game.clicks == [BOSS, ENTRY, ROW, CH, END]


def test_simple_mode_unchanged_when_settlement_returns_to_challenge(clock, store):
    """simple 模式：结算后直接回挑战界面，不碰任何导航模板。"""
    game = FakeShardGame(clock, after_end="challenge")
    flow = make_flow(game, clock, store, MODE_SIMPLE, times=2)

    flow.run()

    assert game.clicks == [CH, END, CH, END]


def test_simple_mode_does_not_navigate(clock, store):
    """simple 模式停在章节界面上不会乱点：等不到挑战按钮按旧语义中止。"""
    game = FakeShardGame(clock, after_end="chapter")
    flow = make_flow(game, clock, store, MODE_SIMPLE, times=2)

    with pytest.raises(FlowAbortedError):
        flow.run()
    assert game.clicks == [CH, END], "simple 模式不该点导航链上的任何东西"


def test_row_screen_prefers_row_over_boss_portrait(clock, store):
    """列表行界面上两个模板都命中时，detect_first 必须取列表行（watch 顺序）。"""
    game = FakeShardGame(clock)
    game.screen = "row"
    flow = make_flow(game, clock, store, MODE_CHAPTER, times=1)
    engine = flow.create_engine()
    from flows.shard.shard_flow import ShardChapterNav
    ShardChapterNav(engine).attach()

    detection = engine.observe()
    assert detection is not None
    assert detection.state is SHARD_FRAGMENT_ROW


def test_unknown_mode_is_rejected(clock, store):
    game = FakeShardGame(clock)
    with pytest.raises(ConfigError):
        ShardFlow(controller=game, machine=game, mode="nope")


def test_chapter_mode_round_timeout_covers_navigation(clock, store):
    """导航卡住（界面一直不变）时，挑战阶段预算兜底中止，而不是无限点头像。"""
    game = FakeShardGame(clock, after_end="chapter")
    # 点头像不再切换界面 -> 导航永远走不完
    game.click = lambda target, **kw: (game.clicks.append(getattr(target, "template", None)), None)[1]
    game.screen = "chapter"
    flow = make_flow(game, clock, store, MODE_CHAPTER, times=1)

    with pytest.raises(FlowAbortedError):
        flow.run()
    # 挑战预算 120 秒内每拍都点一次头像，但不会超过预算太多
    assert clock.now <= flow.CHALLENGE_TIMEOUT + settings.DEFAULT_WAIT_INTERVAL * 2
