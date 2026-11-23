"""式神碎片「两种入口同时监听」的行为测试。

**为什么要同时监听**：重新挑战的入口有两种 ——
1. 结算后直接回到挑战按钮界面；
2. 结算后被踢回探索章节界面，要导航一圈（Boss 头像 -> 入口面板 -> 列表行）才回到挑战界面。

这两种**跑着跑着会交替出现，不是开局能选定的**，所以没有模式开关：引擎一次性 watch
两种入口涉及的全部界面，屏幕上实际出现什么就走什么。

剧本（假游戏）：
    挑战界面 --点挑战--> 战斗(30s) --时间到--> 结算界面
    结算 --点结算--> 按 script 决定回「挑战界面」还是「章节界面」

完整链条是**四屏**（第十八章真机量的，2026-11-21）：
    章节界面 --点紫色Boss头像--> 副本界面 --点「式神碎片」入口条--> 选择式神界面
    --点「头像+等级」那一行--> 挑战界面 --点菱形挑战按钮--> 战斗 --> 结算

难点在于**同屏多个模板同时达标**，而 `detect_first` 是顺序优先、不看分数：
- 选择式神屏：列表行 0.978 / 挑战按钮 0.999 / 入口条 0.928 三者都达标 ——
  必须让列表行赢，否则跳过选式神直接打默认式神（用户报的「没串起来」）；
- 真挑战界面：列表行掉到 0.799、入口条 0.927，都低于各自阈值，只剩挑战按钮达标；
- 结算画面：入口条也命中 —— 结算模板不排第一就会被永久遮蔽（真机卡死近 4 分钟）；
- 战斗画面：入口条也命中（真机照着点到了右上角），靠**阶段门控**兜住。

所以 watch 顺序 = 结算画面 > 列表行 > 挑战按钮 > 入口条 > Boss 头像，
再叠加「选中后列表行分数会掉」这个阈值判据（0.9）和战斗阶段门控。

不截屏不点击：machine 与 controller 都是假的，时钟也是假的。
"""
import pytest

from config import settings
from core.errors import FlowAbortedError
from core.timing import CycleTimer
from flows.battle_cycle import PHASE_BATTLE, PHASE_CHALLENGE
from flows.signals import PREFIX_STATE_ENTERED, topic_for
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

    #: 每个界面上**过了自己阈值**的状态。三处跨界面命中是故意留下的（见模块 docstring）
    SCREENS = {
        # 真挑战界面：式神已选中，列表行掉到 0.799 < 阈值 0.9、入口条 0.927 < 阈值 0.95，
        # 所以这里只有挑战按钮达标
        "challenge": (SHARD_CHALLENGE,),
        # 战斗画面：入口条仍会命中（旧模板实测 0.845~0.895；新模板未量，但门控与阈值
        # 无关，这一屏必须继续测）
        "battle": (SHARD_FRAGMENT_ENTRY,),
        # 结算画面：入口条也命中 —— 排序不对就会永久遮蔽结算识别
        "end": (SHARD_BATTLE_END, SHARD_FRAGMENT_ENTRY),
        # 探索章节界面：只有紫色 Boss 头像达标
        "chapter": (SHARD_CHAPTER_BOSS,),
        # 副本界面（点完头像）：只有入口条达标
        "dungeon": (SHARD_FRAGMENT_ENTRY,),
        # 选择式神屏（点完入口条）：列表行 / 挑战按钮 / 入口条 **三者同时达标**
        # （真机实测 0.978 / 0.999 / 0.928）—— 必须先选式神，所以列表行要赢
        "select": (SHARD_FRAGMENT_ROW, SHARD_CHALLENGE, SHARD_FRAGMENT_ENTRY),
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
        # 战斗进行中也要按「战斗画面」去识别：真机上导航模板在战斗画面上会误命中
        # （入口面板 0.845~0.895）。早先这里直接 return None，等于把那个误命中完全
        # 模拟掉了 —— 门控看着有测试覆盖，其实是假通过。
        if self._battle_until is not None:
            if self.clock() < self._battle_until:
                screen = "battle"
            else:
                self._battle_until = None
                self.screen = "end"
                screen = "end"
        else:
            screen = self.screen
        present = self.SCREENS[screen]
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
            self.screen = "dungeon"
        elif template == SHARD_FRAGMENT_ENTRY.template:
            self.screen = "select"
        elif template == SHARD_FRAGMENT_ROW.template:
            self.screen = "challenge"
        return getattr(target, "center", None)


@pytest.fixture()
def clock():
    return FakeClock()


@pytest.fixture()
def store(tmp_path):
    return DurationStore(database=Database(tmp_path / "shard.db"))


def make_flow(game, clock, store, times=2, chapter_nav=True):
    """默认开着章节入口导航，好测导航链的行为。

    真实运行时 ShardFlow 的 chapter_nav 默认 True（模板已重裁、真机走通）；
    这里显式传参以便两条路径都能测。
    """
    return ShardFlow(
        controller=game,
        machine=game,
        times=times,
        chapter_nav=chapter_nav,
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
    ("dungeon", [ENTRY, ROW]),
    ("select", [ROW]),
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
# watch 顺序：同屏多个模板达标时该点谁
# --------------------------------------------------------------------------- #
def test_select_screen_prefers_row_over_challenge_button(clock, store):
    """选择式神屏上列表行 / 挑战按钮 / 入口条同时达标，必须取列表行。

    真机实测 0.978 / 0.999 / 0.928。`detect_first` 是顺序优先不看分数的，
    所以哪怕挑战按钮分数更高，也必须让列表行排前面 —— 否则脚本会跳过选式神，
    直接打默认式神（用户报的「执行着执行着没串起来」就是这个）。
    """
    game = FakeShardGame(clock)
    game.screen = "select"
    engine = make_flow(game, clock, store, times=1).create_engine()
    ShardEntryNav(engine).attach()

    detection = engine.observe()

    assert detection is not None
    assert detection.state is SHARD_FRAGMENT_ROW


def test_challenge_screen_after_selected_only_matches_challenge(clock, store):
    """选中式神之后的真挑战界面上只有挑战按钮达标，可以直接开战。

    列表行选中后掉到 0.799（阈值 0.9）、入口条 0.927（阈值 0.95），
    所以「列表行排在挑战按钮前」不会反过来卡住正常挑战。
    """
    game = FakeShardGame(clock)
    game.screen = "challenge"
    engine = make_flow(game, clock, store, times=1).create_engine()
    ShardEntryNav(engine).attach()

    detection = engine.observe()

    assert detection is not None
    assert detection.state is SHARD_CHALLENGE


def test_watch_order_is_stable_after_battle_cycle_attaches(clock, store):
    """两个订阅方都 watch 之后，优先级顺序仍是 结算 > 列表行 > 挑战按钮 > 入口条 > 头像。"""
    game = FakeShardGame(clock)
    game.screen = "challenge"
    flow = make_flow(game, clock, store, times=1)
    engine = flow.create_engine()
    ShardEntryNav(engine).attach()
    keys = [getattr(state, "key", state) for state in engine.watched]

    order = [SHARD_BATTLE_END, SHARD_FRAGMENT_ROW, SHARD_CHALLENGE,
             SHARD_FRAGMENT_ENTRY, SHARD_CHAPTER_BOSS]
    assert keys == [state.key for state in order], keys
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


# --------------------------------------------------------------------------- #
# 战斗阶段门控：真机跑出来的坑
# --------------------------------------------------------------------------- #
class FakeCycle:
    """只暴露 phase 的假 BattleCycle，用来单测门控。"""

    def __init__(self, phase: str) -> None:
        self.phase = phase


def test_no_navigation_clicks_during_battle(clock, store):
    """战斗画面上入口面板误命中（实测 0.845）时，绝不能点它。

    真机复现过：点挑战进战斗后，导航订阅方把误命中的「式神碎片」入口面板点在了
    (653, 141)（右上角），卡住补点又点了两次，一场战斗被点乱、结算画面也没识别到。
    """
    game = FakeShardGame(clock, script=["challenge"])
    flow = make_flow(game, clock, store, times=2)

    flow.run()

    assert game.clicks == [CH, END, CH, END]
    assert not [c for c in game.clicks if c in NAV], "战斗期间点到了导航模板"


def test_gate_blocks_navigation_outside_challenge_phase(clock, store):
    """门控本身：phase != challenge 时不点击，但保留当前状态。"""
    game = FakeShardGame(clock)
    game.screen = "chapter"
    engine = make_flow(game, clock, store, times=1).create_engine()
    nav = ShardEntryNav(engine, cycle=FakeCycle(PHASE_BATTLE)).attach()

    engine.observe()          # 识别到 Boss 头像 -> entered -> 被门控挡下

    assert game.clicks == [], "战斗阶段不该产生任何点击"
    assert nav._last_click_key == ""
    # 被挡下的命中**不该**重置：重置会让每一拍都重新触发 entered，把日志刷爆
    # （真机 4 分钟刷了 50 多条）。补触发交给 _sync_gate() 抓门控打开的边沿。
    assert engine.current is not None
    assert engine.current.state is SHARD_CHAPTER_BOSS
    assert nav._gate_open is False


def test_gate_opening_retriggers_navigation(clock, store):
    """门控放开后，同一个界面还能点 —— 这正是 _sync_gate() 补触发的意义。"""
    game = FakeShardGame(clock)
    game.screen = "chapter"
    engine = make_flow(game, clock, store, times=1).create_engine()
    cycle = FakeCycle(PHASE_BATTLE)
    ShardEntryNav(engine, cycle=cycle).attach()

    engine.observe()
    assert game.clicks == []

    cycle.phase = PHASE_CHALLENGE
    engine.observe()          # _current 已被重置，同一界面会再触发一次 entered

    assert game.clicks == [BOSS]


def test_nav_without_cycle_is_not_gated(clock, store):
    """不传 cycle（单测里单独挂 nav）时不门控，保持原行为。"""
    game = FakeShardGame(clock)
    game.screen = "chapter"
    engine = make_flow(game, clock, store, times=1).create_engine()
    ShardEntryNav(engine).attach()

    engine.observe()

    assert game.clicks == [BOSS]


# --------------------------------------------------------------------------- #
# 顺序优先（不是分数优先）：真机卡死 4 分钟的那个坑
# --------------------------------------------------------------------------- #
def test_settlement_not_shadowed_by_entry_false_positive(clock, store):
    """结算画面上入口面板也误命中（实测 0.85）时，结算模板必须赢。

    真机事故：`SHARD_FRAGMENT_ENTRY` 排在 `SHARD_BATTLE_END` 前面，而 detect_first
    是顺序优先、不看分数 —— 结算画面被永久遮蔽，脚本卡了近 4 分钟点不掉结算，
    最后只能人工中断。
    """
    game = FakeShardGame(clock)
    game.screen = "end"
    engine = make_flow(game, clock, store, times=1).create_engine()
    ShardEntryNav(engine).attach()

    detection = engine.observe()

    assert detection is not None
    assert detection.state is SHARD_BATTLE_END


def test_battle_false_positive_fires_entered_once_not_every_poll(clock, store):
    """门控挡下的命中不该每拍重复触发 entered（真机 4 分钟刷了 50 多条日志）。"""
    game = FakeShardGame(clock, script=["challenge"])
    flow = make_flow(game, clock, store, times=2)
    seen = []
    flow.on(topic_for(PREFIX_STATE_ENTERED, SHARD_FRAGMENT_ENTRY), seen.append)

    flow.run()

    # 两场战斗 = 两次 entered；改之前每一拍（3 秒）都会重来一次
    assert len(seen) == 2


def test_thresholds_match_the_measured_matrix():
    """阈值卡在真机实测矩阵的噪声与真命中之间（尺度 1.0~0.4、下限 24px）。

    模板用探针法按当前窗口比例从实时截屏重裁（章节头像 30x30 / 入口条 111x41）；
    列表行 308x86 本来就是对的，只是我先前误判「这屏不存在」。
    同一屏点击式神行前后各量一次，才拿到「选中」这个判据：
      选择式神屏：列表行 0.978 / 挑战按钮 0.999 / 入口条 0.928 / 头像 0.504
      点完行之后：列表行 0.799 / 挑战按钮 0.999 / 入口条 0.927 / 头像 0.592
      章节界面：  头像 0.986 / 入口条 0.806 / 列表行 0.541 / 挑战按钮 0.558
      副本界面：  入口条 1.000 / 挑战按钮 0.749 / 列表行 0.511
    注：更早记录的 0.925 / 0.845 / 0.721 那批是旧尺度表试到 0.3 的缩小匹配噪声
    （命中框 20×26、67×25 像素），尺度收紧后不再复现，别拿它们当依据。
    """
    assert SHARD_CHALLENGE.threshold < 0.999, "挑战按钮真命中，别抬到识别不到"
    assert SHARD_CHALLENGE.threshold > 0.749, "副本界面上挑战按钮的实测噪声 0.749"
    # 列表行：未选中 0.978 要达标、已选中 0.799 不能达标 —— 这就是「该选式神」的判据
    assert SHARD_FRAGMENT_ROW.threshold > 0.799, "选中式神后不该再被认成「还要选」"
    assert SHARD_FRAGMENT_ROW.threshold < 0.978, "未选中时必须达标"
    # 入口条：真命中 1.000，挑战/选择屏上 0.927~0.928 不能达标
    assert SHARD_FRAGMENT_ENTRY.threshold > 0.928, "挑战界面上入口条的实测噪声"
    assert SHARD_FRAGMENT_ENTRY.threshold < 1.000
    assert 0.592 < SHARD_CHAPTER_BOSS.threshold < 0.986, "头像：副本后 0.592 / 章节 0.986"


# --------------------------------------------------------------------------- #
# 章节入口导航：模板重裁后默认开启，可关
# --------------------------------------------------------------------------- #
def test_chapter_nav_defaults_to_true():
    """2026-11-21 用探针法重裁「章节头像」「入口条」后，导航链真机走通，默认开启。"""
    assert ShardFlow(controller=object(), machine=object()).chapter_nav is True


def test_chapter_nav_can_be_disabled(clock, store):
    """显式关掉导航时：停在章节界面上一个导航模板都不点，按挑战预算超时中止。

    （旧行为：三张模板比例不对时默认关闭，防止照缩小噪声乱点浪费挑战券。
    重裁后默认打开，但关闭路径的行为仍要可预期 —— 别的章节若模板失效就用它兜底。）
    """
    game = FakeShardGame(clock, script=["chapter"])
    game.screen = "chapter"
    flow = make_flow(game, clock, store, times=1, chapter_nav=False)

    with pytest.raises(FlowAbortedError):
        flow.run()

    assert game.clicks == [], "导航关闭时不该有任何点击"


def test_default_run_watches_only_challenge_and_end(clock, store):
    """导航关闭时只登记挑战按钮与结算画面，且结算排在挑战按钮前面。"""
    game = FakeShardGame(clock)
    flow = make_flow(game, clock, store, times=1, chapter_nav=False)
    engine = flow.create_engine()
    from flows.battle_cycle import BattleCycle
    BattleCycle(engine, challenge=SHARD_CHALLENGE, end_states=flow.END_STATES,
                watch_end_first=True).attach()

    keys = [getattr(state, "key", state) for state in engine.watched]
    assert keys == [SHARD_BATTLE_END.key, SHARD_CHALLENGE.key]


def test_watch_deduplicates_across_subscribers(clock, store):
    """两个订阅方都要结算画面时，登记顺序只由第一次决定，列表里不留重复项。"""
    game = FakeShardGame(clock)
    flow = make_flow(game, clock, store, times=1)
    engine = flow.create_engine()
    ShardEntryNav(engine).attach()
    from flows.battle_cycle import BattleCycle
    BattleCycle(engine, challenge=SHARD_CHALLENGE, end_states=flow.END_STATES).attach()

    keys = [getattr(state, "key", state) for state in engine.watched]
    assert len(keys) == len(set(keys)), "重复登记应该被忽略：{}".format(keys)
    assert keys[0] == SHARD_BATTLE_END.key, "结算画面仍是第一优先级"


def test_main_does_not_pass_chapter_nav():
    """命令行不传 chapter_nav，真实运行走 ShardFlow 的默认值（现为 True）。"""
    from main import build_parser

    parser = build_parser()
    args = parser.parse_args(["shard", "--times", "50"])
    assert not hasattr(args, "shard_chapter_nav")
