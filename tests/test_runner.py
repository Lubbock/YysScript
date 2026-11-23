"""runner/ 的契约测试：分组解析、DSL 加载、坐标换算、主循环。

不截屏、不点击、不连 Ollama、不需要 cv2 / pyautogui：
窗口 / 鼠标 / 截屏 / 模型全部用假实现注入，只验证纯逻辑与坐标数学。
"""
import json
import json
from pathlib import Path
import pytest

from actions.window import GameWindow, WindowFinder, WindowRect
from core.timing import CycleTimer
from runner.actor import Actor
from runner.dsl import load_flow, load_or_scaffold, scaffold, step, write_scaffold
from runner.engine import Runner, build_runner
from runner.errors import DslError, GroupError, RunnerError, StepResolveError
from runner.group import load_group
from runner.matcher import ScreenMatcher, Verdict
from runner.session import Session
from storage.database import Database
from storage.duration_store import DurationStore

CAPTURE_REGION = (189, 251, 690, 356)
CHALLENGE_POINT = (598, 306)
FINISH_POINT = (346, 269)
PNG = b"\x89PNG\r\n\x1a\n-fake"


class FakeFinder(WindowFinder):
    """返回固定矩形的窗口查找器。"""

    name = "fake"

    def __init__(self, rect):
        self._rect = rect

    def find(self):
        return self._rect


class FakeMouse:
    """记录点击落点的假鼠标。"""

    def __init__(self, fail_times=0):
        self.clicks = []
        self.pid_provider = None
        self.fail_times = fail_times

    def click(self, point, clicks=1, **kwargs):
        self.clicks.append((tuple(point), clicks))
        if self.fail_times > 0:
            self.fail_times -= 1
            return None
        return tuple(point)


class FakeSession(Session):
    """真 Session，但截屏换成固定字节（避开 cv2）。"""

    def __init__(self, rect, mouse=None):
        window = GameWindow(finder=FakeFinder(rect), allow_fullscreen=False)
        super().__init__(window=window, mouse=mouse or FakeMouse(), capture=object())
        self.grabs = 0

    def grab(self):
        self.grabs += 1
        return PNG, None


def verdict(matched, score=None, reason="测试判定"):
    score = (0.99 if matched else 0.05) if score is None else score
    return {
        "same_screen": matched, "similarity": score, "confidence": 0.9,
        "a_summary": "A", "b_summary": "B", "differences": [],
        "reason": reason, "truncated": False, "elapsed_ms": 1200.0,
        "model": "fake-omni", "done_reason": "stop",
    }


class FakeJudge:
    """按调用顺序返回脚本里的判定结果。"""

    def __init__(self, script=None, threshold=0.6, default_matched=True):
        self.threshold = threshold
        self.script = list(script or [])
        self.default_matched = default_matched
        self.calls = []

    def judge(self, image_a, image_b):
        self.calls.append((image_a, image_b))
        if self.script:
            item = self.script.pop(0)
            return item if isinstance(item, dict) else verdict(bool(item))
        return verdict(self.default_matched)


class TargetJudge:
    """按「目标截图 id」决定命中与否，与轮询次数无关。"""

    def __init__(self, mapping=None, threshold=0.6, default_matched=True):
        self.mapping = dict(mapping or {})
        self.threshold = threshold
        self.default_matched = default_matched
        self.calls = []

    def judge(self, image_a, image_b):
        self.calls.append((image_a, image_b))
        shot_id = Path(image_b).stem
        value = self.mapping.get(shot_id, self.default_matched)
        return verdict(bool(value))


class FirstRoundFailsJudge:
    """第一轮的第一张图判失败，之后全部成功。"""

    def __init__(self, first_shot_id):
        self.threshold = 0.6
        self.first_shot_id = first_shot_id
        self.calls = []
        self.runner = None

    def judge(self, image_a, image_b):
        self.calls.append((image_a, image_b))
        round_index = self.runner.round_index if self.runner else 1
        if Path(image_b).stem == self.first_shot_id and round_index <= 1:
            return verdict(False)
        return verdict(True)


def make_png(width=690, height=356):
    return bytes(PNG) + json.dumps({"w": width, "h": height}).encode()


def build_dataset(tmp_path, shots=None, group_name="御魂十一"):
    """造一个带标注的分组数据集。"""
    root = tmp_path / "dataset"
    (root / "groups" / "default" / "shots").mkdir(parents=True)
    (root / "groups.json").write_text(json.dumps({"groups": [
        {"key": "default", "name": "默认分组", "description": "",
         "created_at": "2026-01-01 00:00:00", "updated_at": "2026-01-01 00:00:00"},
        {"key": "soul11", "name": group_name, "description": "挖土",
         "created_at": "2026-01-01 00:00:00", "updated_at": "2026-01-01 00:00:00"},
    ]}, ensure_ascii=False), encoding="utf-8")

    group_dir = root / "groups" / "soul11"
    (group_dir / "shots").mkdir(parents=True)
    (group_dir / "thumbs").mkdir(parents=True)

    default_shots = shots if shots is not None else [
        {
            "id": "20260101-000001-000001",
            "captured_at": "2026-01-01 00:00:01",
            "width": 690, "height": 356, "source": "window",
            "origin": [189, 251], "region": list(CAPTURE_REGION),
            "window_id": 4242, "process": "Fake Mirroring", "note": "",
            "annotations": [{"id": "a1", "kind": "point", "label": "挑战",
                             "point": {"x": CHALLENGE_POINT[0], "y": CHALLENGE_POINT[1]}}],
        },
        {
            "id": "20260101-000002-000002",
            "captured_at": "2026-01-01 00:00:02",
            "width": 690, "height": 356, "source": "window",
            "origin": [189, 251], "region": list(CAPTURE_REGION),
            "window_id": 4242, "process": "Fake Mirroring", "note": "",
            "annotations": [{"id": "a2", "kind": "point", "label": "完成",
                             "point": {"x": FINISH_POINT[0], "y": FINISH_POINT[1]}}],
        },
    ]
    for record in default_shots:
        shot_id = record["id"]
        (group_dir / "shots" / "{}.png".format(shot_id)).write_bytes(make_png())
        payload = dict(record, image="{}.png".format(shot_id), group="soul11")
        (group_dir / "shots" / "{}.json".format(shot_id)).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return root


def write_dsl(root, text, key="soul11"):
    path = root / "groups" / key / "flow.py"
    path.write_text(text, encoding="utf-8")
    return path


BASIC_DSL = """
name = "御魂十一"
round_timeout = 300

steps = [
    step("挑战", timeout=30),
    step("完成", timeout=60),
]
"""


@pytest.fixture()
def root(tmp_path):
    return build_dataset(tmp_path)


@pytest.fixture()
def group(root):
    return load_group("御魂十一", root)


@pytest.fixture()
def timer(tmp_path):
    store = DurationStore(database=Database(tmp_path / "timing.db"))
    return CycleTimer(store=store, adaptive=False)


def make_runner(root, group, dsl=BASIC_DSL, judge=None, rect=None, timer=None,
                times=1, mouse=None, **kwargs):
    path = write_dsl(root, dsl)
    flow = load_flow(path, group)
    session = FakeSession(rect or WindowRect(*CAPTURE_REGION, wid=1), mouse=mouse)
    active_judge = judge or FakeJudge()
    active_timer = timer or CycleTimer(store=DurationStore(database=Database(
        root.parent / "timing.db")), adaptive=False)
    matcher = ScreenMatcher(session, judge=active_judge, timer=active_timer,
                            probe_key="御魂十一:probe")
    clock = FakeClock()
    actor = Actor(session, settle=0, retry_pause=0, sleep=clock.sleep)
    runner = Runner(group, flow, session, matcher, actor, timer=active_timer,
                    times=times, sleep=clock.sleep, clock=clock, **kwargs)
    return runner, session, active_judge, actor


class FakeClock:
    """只在 sleep 时前进的假时钟（和真实世界一致）。"""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def test_load_group_reads_annotations(group):
    assert group.name == "御魂十一" and group.key == "soul11"
    assert len(group.shots) == 2
    first, second = group.shots
    assert first.captured_at < second.captured_at
    assert first.region == CAPTURE_REGION
    assert first.annotations[0].point == CHALLENGE_POINT
    assert second.annotations[0].point == FINISH_POINT
    assert group.all_labels() == ["挑战", "完成"]
    assert group.by_label("挑战") == [first]
    assert group.timing_prefix() == "御魂十一"


def test_group_lookup_by_name_and_key(root):
    assert load_group("御魂十一", root).key == "soul11"
    assert load_group("soul11", root).name == "御魂十一"


def test_group_not_found_lists_available(root):
    with pytest.raises(GroupError) as excinfo:
        load_group("麒麟", root)
    assert "御魂十一" in str(excinfo.value)


def test_box_annotation_resolves_to_center(tmp_path):
    root = build_dataset(tmp_path, shots=[{
        "id": "20260101-000003-000003", "captured_at": "2026-01-01 00:00:03",
        "width": 690, "height": 356, "source": "window",
        "origin": [0, 0], "region": [0, 0, 690, 356], "note": "",
        "annotations": [{"id": "b1", "kind": "box", "label": "按钮",
                         "box": {"x": 100, "y": 50, "w": 40, "h": 20}}],
    }])
    group = load_group("御魂十一", root)
    assert group.shots[0].annotations[0].point == (120, 60)


def test_dsl_loads_steps_and_name(group, root):
    path = write_dsl(root, BASIC_DSL)
    flow = load_flow(path, group)
    assert flow.name == "御魂十一"
    assert flow.round_timeout == 300
    assert [item.target for item in flow.steps] == ["挑战", "完成"]
    assert flow.steps[0].timeout == 30
    assert flow.hooks == {}


def test_dsl_collects_hooks(group, root):
    path = write_dsl(root, BASIC_DSL + """

def on_step_matched(ctx, st):
    return True


def before_run(ctx):
    ctx.vars["started"] = True
""")
    flow = load_flow(path, group)
    assert sorted(flow.hooks) == ["before_run", "on_step_matched"]


def test_dsl_missing_steps_raises(group, root):
    path = write_dsl(root, "name = '空'\n")
    with pytest.raises(DslError) as excinfo:
        load_flow(path, group)
    assert "steps" in str(excinfo.value)


def test_dsl_empty_steps_raises(group, root):
    path = write_dsl(root, "steps = []\n")
    with pytest.raises(DslError):
        load_flow(path, group)


def test_dsl_syntax_error_reports_line(group, root):
    path = write_dsl(root, "steps = [\n  step('挑战'\n]\n")
    with pytest.raises(DslError) as excinfo:
        load_flow(path, group)
    assert "语法错误" in str(excinfo.value)


def test_dsl_runtime_error_wrapped(group, root):
    path = write_dsl(root, "steps = [step(undefined_name)]\n")
    with pytest.raises(DslError) as excinfo:
        load_flow(path, group)
    assert "DSL 执行失败" in str(excinfo.value)


def test_dsl_rejects_non_step_items(group, root):
    path = write_dsl(root, "steps = ['挑战']\n")
    with pytest.raises(DslError):
        load_flow(path, group)


def test_dsl_namespace_has_helpers(group, root):
    path = write_dsl(root, """
seen_labels = sorted(labels)
shot_count = len(shots)
has_gfx = callable(gfx.brightness)
steps = [step(seen_labels[0])]
""")
    flow = load_flow(path, group)
    assert flow.namespace["seen_labels"] == ["完成", "挑战"]
    assert flow.namespace["shot_count"] == 2
    assert flow.namespace["has_gfx"] is True


def test_missing_dsl_tells_how_to_create(group):
    assert not group.has_dsl()
    with pytest.raises(DslError) as excinfo:
        from runner.dsl import load_group_flow
        load_group_flow(group)
    assert "--init-dsl" in str(excinfo.value)


def test_scaffold_roundtrips(group, root):
    path = write_scaffold(group)
    assert path == group.dsl_path
    flow = load_flow(path, group)
    assert [item.target for item in flow.steps] == ["挑战", "完成"]
    assert flow.name == "御魂十一"
    assert "on_step_timeout" in flow.hooks


def test_scaffold_refuses_overwrite(group):
    write_scaffold(group)
    with pytest.raises(DslError):
        write_scaffold(group)
    write_scaffold(group, overwrite=True)


def test_step_resolves_shot_and_annotation(group, root):
    runner, _, _, _ = make_runner(root, group)
    steps = runner.resolve()
    assert [item.shot.id for item in steps] == [
        "20260101-000001-000001", "20260101-000002-000002"]
    assert [item.annotation.point for item in steps] == [CHALLENGE_POINT, FINISH_POINT]
    assert [item.timeout for item in steps] == [30.0, 60.0]
    assert steps[0].timing_key("御魂十一") == "御魂十一:挑战"


def test_step_can_target_by_shot_id(group, root):
    dsl = """
steps = [
    step("随便什么", shot="20260101-000002-000002", click="完成"),
]
"""
    runner, _, _, _ = make_runner(root, group, dsl=dsl)
    resolved = runner.resolve()
    assert resolved[0].shot.id == "20260101-000002-000002"
    assert resolved[0].annotation.label == "完成"


def test_step_unknown_target_lists_choices(group, root):
    runner, _, _, _ = make_runner(root, group, dsl="steps = [step('不存在')]\n")
    with pytest.raises(StepResolveError) as excinfo:
        runner.resolve()
    message = str(excinfo.value)
    assert "挑战" in message and "完成" in message


def test_step_bad_click_label_raises(group, root):
    dsl = 'steps = [step("挑战", click="没有这个标注")]\n'
    runner, _, _, _ = make_runner(root, group, dsl=dsl)
    with pytest.raises(StepResolveError) as excinfo:
        runner.resolve()
    assert "没有名为" in str(excinfo.value)


def test_ambiguous_label_requires_shot(tmp_path):
    shots = []
    for index in (1, 2):
        shots.append({
            "id": "20260101-00000%d-00000%d" % (index, index),
            "captured_at": "2026-01-01 00:00:0%d" % index,
            "width": 690, "height": 356, "source": "window",
            "origin": [0, 0], "region": [0, 0, 690, 356], "note": "",
            "annotations": [{"id": "a%d" % index, "kind": "point", "label": "挑战",
                             "point": {"x": 10 * index, "y": 20}}],
        })
    root = build_dataset(tmp_path, shots=shots)
    group = load_group("御魂十一", root)
    runner, _, _, _ = make_runner(root, group, dsl='steps = [step("挑战")]\n')
    with pytest.raises(StepResolveError) as excinfo:
        runner.resolve()
    assert "请用 shot= 指明" in str(excinfo.value)

    fixed = 'steps = [step("挑战", shot="20260101-000002-000002")]\n'
    runner2, _, _, _ = make_runner(root, group, dsl=fixed)
    assert runner2.resolve()[0].annotation.point == (20, 20)


def test_multi_annotation_shot_needs_explicit_click(tmp_path):
    root = build_dataset(tmp_path, shots=[{
        "id": "20260101-000009-000009", "captured_at": "2026-01-01 00:00:09",
        "width": 690, "height": 356, "source": "window",
        "origin": [0, 0], "region": [0, 0, 690, 356], "note": "选择界面",
        "annotations": [
            {"id": "x", "kind": "point", "label": "左", "point": {"x": 10, "y": 10}},
            {"id": "y", "kind": "point", "label": "右", "point": {"x": 20, "y": 20}},
        ],
    }])
    group = load_group("御魂十一", root)
    runner, _, _, _ = make_runner(root, group, dsl='steps = [step("选择界面")]\n')
    with pytest.raises(GroupError) as excinfo:
        runner.resolve()
    assert "请在 step(click=...)" in str(excinfo.value)

    runner2, _, _, _ = make_runner(root, group,
                                   dsl='steps = [step("选择界面", click="右")]\n')
    assert runner2.resolve()[0].annotation.point == (20, 20)


def test_shot_without_annotation_only_recognizes(tmp_path):
    root = build_dataset(tmp_path, shots=[{
        "id": "20260101-000010-000010", "captured_at": "2026-01-01 00:00:10",
        "width": 690, "height": 356, "source": "window",
        "origin": [0, 0], "region": [0, 0, 690, 356], "note": "过场",
        "annotations": [],
    }])
    group = load_group("御魂十一", root)
    runner, session, _, _ = make_runner(root, group, dsl='steps = [step("过场")]\n')
    report = runner.run()
    assert report.completed == 1
    assert runner.steps[0].annotation is None
    assert session.mouse.clicks == []


def test_coordinate_mapping_when_window_unchanged(group, root):
    runner, session, _, _ = make_runner(root, group)
    shot = group.shots[0]
    logical, screen = session.resolve(shot, *CHALLENGE_POINT)
    assert (logical.x, logical.y) == (887, 660)
    assert screen == (189 + 598, 251 + 306)


def test_coordinate_mapping_follows_moved_and_resized_window(group, root):
    moved = WindowRect(left=100, top=50, width=1024, height=768, wid=2)
    runner, session, _, _ = make_runner(root, group, rect=moved)
    shot = group.shots[0]
    logical, screen = session.resolve(shot, *CHALLENGE_POINT)
    assert (logical.x, logical.y) == (887, 660)
    assert screen == (100 + 887, 50 + 660)


def test_click_goes_through_viewport_and_mouse(group, root):
    moved = WindowRect(left=100, top=50, width=1024, height=768, wid=2)
    mouse = FakeMouse()
    runner, session, _, _ = make_runner(root, group, rect=moved, mouse=mouse, times=1)
    report = runner.run()

    assert report.completed == 1 and report.failed == 0
    assert [point for point, _ in mouse.clicks] == [(987, 710), (613, 630)]
    assert report.clicks == 2


def test_each_step_compares_only_its_own_target(group, root):
    judge = FakeJudge(script=[True, True])
    runner, session, _, _ = make_runner(root, group, judge=judge, times=1)
    runner.run()

    targets = [call[1] for call in judge.calls]
    expected = [group.shots[0].image_path, group.shots[1].image_path]
    assert targets == expected
    assert all(call[0] == PNG for call in judge.calls)
    assert len(judge.calls) == 2


def test_main_loop_repeats_steps_per_round(group, root):
    judge = FakeJudge(script=[True] * 6)
    runner, session, _, _ = make_runner(root, group, judge=judge, times=3)
    report = runner.run()

    assert report.completed == 3 and len(report.rounds) == 3
    targets = [call[1].name for call in judge.calls]
    assert targets == [
        "20260101-000001-000001.png", "20260101-000002-000002.png",
    ] * 3
    assert report.clicks == 6
    assert report.steps_per_round == 2


def test_probe_retries_until_match(group, root):
    judge = FakeJudge(script=[False, False, True, True])
    runner, session, _, _ = make_runner(root, group, judge=judge, times=1)
    report = runner.run()

    assert report.completed == 1
    assert report.rounds[0].steps[0].probes == 3
    assert report.rounds[0].steps[1].probes == 1
    assert report.rounds[0].steps[0].matched is True


def test_step_timeout_fails_round_and_stops(group, root):
    judge = FakeJudge(default_matched=False)
    runner, session, _, _ = make_runner(root, group, judge=judge, times=3)
    report = runner.run()

    assert report.completed == 0 and report.failed == 1
    assert len(report.rounds) == 1
    first = report.rounds[0].steps[0]
    assert first.matched is False and "超时" in first.error
    assert session.mouse.clicks == []


def test_continue_on_error_keeps_going(group, root):
    judge = FirstRoundFailsJudge("20260101-000001-000001")
    runner, _, _, _ = make_runner(root, group, judge=judge, times=3,
                                  continue_on_error=True)
    judge.runner = runner
    report = runner.run()
    assert len(report.rounds) == 3
    assert report.completed == 2 and report.failed == 1


def test_optional_step_is_skipped(group, root):
    dsl = """
steps = [
    step("挑战", timeout=5, optional=True),
    step("完成", timeout=5),
]
"""
    judge = TargetJudge({"20260101-000001-000001": False})
    runner, session, _, _ = make_runner(root, group, dsl=dsl, judge=judge, times=1)
    report = runner.run()

    assert report.completed == 1
    steps = report.rounds[0].steps
    assert steps[0].skipped is True and steps[0].matched is False
    assert steps[1].matched is True and steps[1].clicked is True


def test_on_step_timeout_hook_can_recover(group, root):
    dsl = """
calls = []

steps = [
    step("挑战", timeout=5),
    step("完成", timeout=5),
]


def on_step_timeout(ctx, st):
    calls.append(st.name)
    ctx.vars["recovered"] = True
    return True
"""
    judge = TargetJudge({"20260101-000001-000001": False})
    runner, _, _, _ = make_runner(root, group, dsl=dsl, judge=judge, times=1)
    report = runner.run()

    assert report.completed == 1
    assert runner.flow.namespace["calls"] == ["挑战"]
    assert runner.context.vars["recovered"] is True
    assert report.rounds[0].steps[0].skipped is True


def test_on_step_matched_false_skips_click(group, root):
    dsl = """
steps = [
    step("挑战", timeout=5),
    step("完成", timeout=5),
]


def on_step_matched(ctx, st):
    return st.name != "挑战"
"""
    judge = FakeJudge(script=[True, True])
    runner, session, _, _ = make_runner(root, group, dsl=dsl, judge=judge, times=1)
    report = runner.run()

    assert report.completed == 1
    assert len(session.mouse.clicks) == 1
    steps = report.rounds[0].steps
    assert steps[0].matched is True and steps[0].clicked is False
    assert steps[1].clicked is True


def test_per_step_on_match_hook(group, root):
    dsl = """
def skip(ctx, st):
    return False


steps = [
    step("挑战", timeout=5, on_match=skip),
    step("完成", timeout=5),
]
"""
    judge = FakeJudge(script=[True, True])
    runner, session, _, _ = make_runner(root, group, dsl=dsl, judge=judge, times=1)
    report = runner.run()
    assert report.completed == 1
    assert len(session.mouse.clicks) == 1


def test_hook_exception_becomes_runner_error(group, root):
    dsl = """
steps = [step("挑战", timeout=5)]


def on_step_matched(ctx, st):
    raise ValueError("钩子里的 bug")
"""
    judge = FakeJudge(script=[True])
    runner, _, _, _ = make_runner(root, group, dsl=dsl, judge=judge, times=1)
    report = runner.run()
    assert report.failed == 1
    assert "钩子 on_step_matched" in report.rounds[0].error


def test_lifecycle_hooks_fire_in_order(group, root):
    dsl = """
order = []

steps = [step("挑战", timeout=5)]


def before_run(ctx):
    order.append("before_run")


def on_round_started(ctx):
    order.append("round_started:%d" % ctx.round_index)


def on_round_finished(ctx, report):
    order.append("round_finished:%s" % report.ok)


def after_run(ctx, report):
    order.append("after_run:%d" % report.completed)
"""
    judge = FakeJudge(script=[True, True])
    runner, _, _, _ = make_runner(root, group, dsl=dsl, judge=judge, times=2)
    runner.run()
    assert runner.flow.namespace["order"] == [
        "before_run", "round_started:1", "round_finished:True",
        "round_started:2", "round_finished:True", "after_run:2",
    ]


def test_ctx_stop_ends_loop(group, root):
    dsl = """
steps = [step("挑战", timeout=5)]


def on_round_finished(ctx, report):
    ctx.stop("够了")
"""
    judge = FakeJudge(script=[True, True, True])
    runner, _, _, _ = make_runner(root, group, dsl=dsl, judge=judge, times=5)
    report = runner.run()
    assert report.stopped is True and report.stop_reason == "够了"
    assert len(report.rounds) == 1


def test_ctx_helpers_available_in_hooks(group, root):
    dsl = """
seen = {}

steps = [step("挑战", timeout=5)]


def on_step_matched(ctx, st):
    shot = ctx.shot("完成")
    seen["shot_id"] = shot.id
    seen["labels"] = sorted(ctx.group.all_labels())
    seen["round"] = ctx.round_index
    seen["times"] = ctx.times
    seen["has_gfx"] = callable(ctx.gfx.brightness)
    seen["matches"] = ctx.matches("完成").matched
    return False
"""
    judge = FakeJudge(script=[True, True])
    runner, _, _, _ = make_runner(root, group, dsl=dsl, judge=judge, times=1)
    runner.run()
    seen = runner.flow.namespace["seen"]
    assert seen["shot_id"] == "20260101-000002-000002"
    assert seen["labels"] == ["完成", "挑战"]
    assert seen["round"] == 1 and seen["times"] == 1
    assert seen["has_gfx"] is True
    assert seen["matches"] is True


def test_dry_run_does_not_touch_screen(group, root):
    judge = FakeJudge(script=[True])
    runner, session, _, _ = make_runner(root, group, judge=judge, times=2, dry_run=True)
    report = runner.run()
    assert session.grabs == 0
    assert judge.calls == []
    assert session.mouse.clicks == []
    assert report.rounds == []
    assert len(runner.resolve()) == 2


def test_round_timeout_marks_round(group, root):
    dsl = """
steps = [
    step("挑战", timeout=30, optional=True),
    step("完成", timeout=60),
]
"""
    judge = TargetJudge(default_matched=False)
    runner, _, _, _ = make_runner(root, group, dsl=dsl, judge=judge, times=2,
                                  round_timeout=20)
    report = runner.run()
    first = report.rounds[0]
    assert first.steps[0].skipped is True
    assert first.timed_out is True
    assert "整轮超时" in first.error
    assert first.ok is False


def test_blind_wait_from_dsl_is_applied(group, root):
    dsl = 'steps = [step("挑战", timeout=60, blind_wait=7.5)]\n'
    judge = FakeJudge(script=[True])
    runner, _, _, _ = make_runner(root, group, dsl=dsl, judge=judge, times=1)
    runner.run()
    assert 7.5 in runner.clock.slept


def test_adaptive_wait_uses_history(tmp_path, group, root):
    store = DurationStore(database=Database(tmp_path / "timing.db"))
    timer = CycleTimer(store=store, adaptive=True)
    key = "御魂十一:挑战"
    for _ in range(8):
        timer.commit(timer.begin(key), 40.0)
    plan = timer.plan(key, timeout=120, interval=1.0, probe_key="御魂十一:probe")
    assert plan.blind_wait > 0
    assert plan.interval > 0


def test_step_samples_are_recorded(group, root, tmp_path):
    store = DurationStore(database=Database(tmp_path / "timing.db"))
    timer = CycleTimer(store=store, adaptive=False)
    judge = FakeJudge(script=[True, True, True, True])
    runner, _, _, _ = make_runner(root, group, judge=judge, times=2, timer=timer)
    runner.run()
    assert timer.estimate("御魂十一:挑战").samples == 2
    assert timer.estimate("御魂十一:完成").samples == 2
    assert timer.estimate("御魂十一:round").samples == 2


def test_probe_cost_recorded_for_blind_wait(group, root, tmp_path):
    store = DurationStore(database=Database(tmp_path / "timing.db"))
    timer = CycleTimer(store=store, adaptive=False)
    judge = FakeJudge(script=[True, True])
    runner, _, _, _ = make_runner(root, group, judge=judge, times=1, timer=timer)
    runner.run()
    assert timer.probe_cost("御魂十一:probe") > 0


def test_click_retries_on_activation_failure(group, root):
    mouse = FakeMouse(fail_times=1)
    judge = FakeJudge(script=[True, True])
    runner, session, _, _ = make_runner(root, group, judge=judge, times=1, mouse=mouse)
    report = runner.run()
    assert report.completed == 1
    assert len(mouse.clicks) == 3
    assert report.rounds[0].steps[0].clicked is True


def test_matcher_wraps_judge_failure(group, root):
    class BrokenJudge:
        threshold = 0.6

        def judge(self, a, b):
            from similarity.llm_judge import JudgeError
            raise JudgeError("连不上 Ollama")

    session = FakeSession(WindowRect(*CAPTURE_REGION, wid=1))
    matcher = ScreenMatcher(session, judge=BrokenJudge())
    with pytest.raises(RunnerError) as excinfo:
        matcher.matches(group.shots[0])
    assert "连不上 Ollama" in str(excinfo.value)


def test_matcher_threshold_decides_match(group, root):
    session = FakeSession(WindowRect(*CAPTURE_REGION, wid=1))
    lenient = ScreenMatcher(session, judge=FakeJudge(script=[verdict(True, 0.62)]))
    assert lenient.matches(group.shots[0]).matched is True

    strict = ScreenMatcher(session, judge=FakeJudge(script=[verdict(True, 0.62)],
                                                  threshold=0.8))
    assert strict.matches(group.shots[0]).matched is False


def test_verdict_describe(group, root):
    text = Verdict(matched=True, score=0.99, same_screen=True, elapsed=1.0,
                   shot_id="x", detail={"reason": "元素一致"}).describe()
    assert "命中" in text and "0.99" in text and "元素一致" in text


def test_report_summary_mentions_key_numbers(group, root):
    judge = FakeJudge(script=[True, True])
    runner, _, _, _ = make_runner(root, group, judge=judge, times=1)
    report = runner.run()
    text = report.summary()
    assert "御魂十一" in text
    assert "完成 1" in text
    assert "点击" in text


def test_build_runner_wires_defaults(group, root, monkeypatch):
    monkeypatch.setattr("runner.engine.Session", lambda *a, **k: FakeSession(
        WindowRect(*CAPTURE_REGION, wid=1)))
    path = write_dsl(root, BASIC_DSL)
    flow = load_flow(path, group)
    judge = FakeJudge(script=[True, True])
    runner = build_runner(group, flow, judge=judge, times=1, dry_run=True,
                          sleep=lambda s: None)
    assert runner.times == 1 and runner.dry_run is True
    assert isinstance(runner.matcher, ScreenMatcher)
    assert isinstance(runner.actor, Actor)
    assert runner.round_timeout == 300


def test_gfx_helpers_work_on_real_png(tmp_path):
    pytest.importorskip("cv2", reason="gfx 需要 cv2")
    from PIL import Image

    from runner import gfx

    path_a = tmp_path / "a.png"
    path_b = tmp_path / "b.png"
    Image.new("RGB", (40, 30), (10, 200, 30)).save(path_a)
    Image.new("RGB", (40, 30), (10, 200, 30)).save(path_b)

    assert gfx.size(path_a) == (40, 30)
    assert gfx.histogram_similarity(path_a, path_b) > 0.999
    assert gfx.mean_pixel_diff(path_a, path_b) < 0.01
    assert gfx.changed_ratio(path_a, path_b) == 0.0
    assert gfx.center_of((10, 20, 30, 40)) == (25, 40)
    assert gfx.scale_point((10, 10), (100, 100), (50, 200)) == (5, 20)
    assert gfx.crop(path_a, (0, 0, 10, 10)).shape == (10, 10, 3)
    assert isinstance(gfx.encode_png(gfx.decode(path_a)), bytes)

    different = tmp_path / "c.png"
    Image.new("RGB", (40, 30), (250, 5, 250)).save(different)
    assert gfx.histogram_similarity(path_a, different) < 0.9
    assert gfx.changed_ratio(path_a, different) > 0.9



# --------------------------------------------------------------------------- #
# entry：每轮开头先探测当前处于序列的哪一格，从那一步起跑
# --------------------------------------------------------------------------- #
CHALLENGE_SHOT = "20260101-000001-000001"
FINISH_SHOT = "20260101-000002-000002"


def test_entry_starts_from_matched_step(root, group):
    """当前画面是第 2 格：跳过第 1 格，只跑第 2 格。"""
    dsl = BASIC_DSL + '\nentry = ["完成", "挑战"]\n'
    judge = TargetJudge({FINISH_SHOT: True, CHALLENGE_SHOT: False})
    runner, session, _, _ = make_runner(root, group, dsl=dsl, judge=judge)
    report = runner.run()
    steps = report.rounds[0].steps

    assert report.completed == 1
    assert [item.index for item in steps] == [1]
    assert steps[0].clicked is True
    assert len(session.mouse.clicks) == 1


def test_entry_reuses_probe_without_second_judgement(root, group):
    """入口探测命中的那张图不再重复判定。"""
    dsl = BASIC_DSL + '\nentry = ["挑战", "完成"]\n'
    judge = TargetJudge({CHALLENGE_SHOT: True, FINISH_SHOT: True})
    runner, session, _, _ = make_runner(root, group, dsl=dsl, judge=judge)
    report = runner.run()

    assert report.probes == 2
    assert [Path(target).stem for _, target in judge.calls] == [
        CHALLENGE_SHOT, FINISH_SHOT]
    assert len(session.mouse.clicks) == 2


def test_entry_all_unmatched_falls_back_to_first_step(root, group):
    """候选都不是当前画面：回到第 1 步正常等，行为与不写 entry 一致。"""
    dsl = BASIC_DSL + '\nentry = ["完成"]\n'
    judge = FakeJudge(script=[False, True, True])
    runner, session, _, _ = make_runner(root, group, dsl=dsl, judge=judge)
    report = runner.run()
    steps = report.rounds[0].steps

    assert report.completed == 1
    assert [item.index for item in steps] == [0, 1]
    assert steps[0].probes == 1


def test_entry_dry_run_does_not_probe(root, group):
    """--dry-run 不截屏，入口探测整段跳过。"""
    dsl = BASIC_DSL + '\nentry = ["挑战", "完成"]\n'
    judge = FakeJudge()
    runner, session, _, _ = make_runner(root, group, dsl=dsl, judge=judge,
                                        dry_run=True)
    runner.run()

    assert judge.calls == []
    assert session.mouse.clicks == []


def test_entry_maps_target_and_label(root, group):
    """entry 认 target / click / label 三种名字，并保留声明顺序。"""
    dsl = BASIC_DSL + '\nentry = ["完成", "挑战"]\n'
    runner, _, _, _ = make_runner(root, group, dsl=dsl)
    runner.resolve()

    assert runner.entry_indexes == [1, 0]


def test_entry_all_covers_every_step(root, group):
    """entry = "all" 按 steps 声明顺序探测。"""
    dsl = BASIC_DSL + '\nentry = "all"\n'
    runner, _, _, _ = make_runner(root, group, dsl=dsl)
    runner.resolve()

    assert runner.entry_indexes == [0, 1]


def test_entry_absent_keeps_old_behaviour(root, group):
    """不写 entry：整段探测跳过，每轮从第 1 步开始。"""
    judge = TargetJudge({CHALLENGE_SHOT: True, FINISH_SHOT: True})
    runner, session, _, _ = make_runner(root, group, judge=judge)
    report = runner.run()

    assert runner.flow.entry == ()
    assert report.probes == 2
    assert len(session.mouse.clicks) == 2


def test_entry_rejects_unknown_step(root, group):
    """entry 写了不存在的步骤名：加载期就报错。"""
    dsl = BASIC_DSL + '\nentry = ["不存在的界面"]\n'

    with pytest.raises(DslError, match="不存在的界面"):
        load_flow(write_dsl(root, dsl), group)


NAV_LABELS = ["碎片副本选中", "式神选中", "挑战", "完成"]
NAV_IDS = ["20260101-00000%d-00000%d" % (i, i) for i in range(1, 5)]
NAV_DSL = '''
name = "御魂十一"
round_timeout = 600
steps = [
    step("碎片副本选中", timeout=30),
    step("式神选中", timeout=30),
    step("挑战", timeout=90),
    step("完成", timeout=300),
]
entry = ["挑战", "完成", "碎片副本选中", "式神选中"]
'''


def nav_shots():
    return [{"id": sid, "captured_at": sid[:13], "width": 690, "height": 356,
             "source": "window", "origin": [189, 251], "region": list(CAPTURE_REGION),
             "window_id": 4242, "process": "Fake", "note": "",
             "annotations": [{"id": "a%d" % index, "kind": "point", "label": label,
                              "point": {"x": 300, "y": 300}}]}
            for index, (sid, label) in enumerate(zip(NAV_IDS, NAV_LABELS))]


class GameJudge:
    """假游戏：只有当前那一屏判 True；每点一次推进一格，点完「完成」回到「挑战」。"""

    threshold = 0.6

    def __init__(self, start=0):
        self.at = start
        self.seen = []

    def judge(self, image_a, image_b):
        shot_id = Path(image_b).stem
        self.seen.append(shot_id)
        return verdict(shot_id == NAV_IDS[self.at])


def make_game(tmp_path, start):
    root = build_dataset(tmp_path, shots=nav_shots())
    group = load_group("御魂十一", root)
    judge = GameJudge(start)
    mouse = FakeMouse()
    runner, session, _, _ = make_runner(root, group, dsl=NAV_DSL, judge=judge,
                                        mouse=mouse)
    original = mouse.click

    def advance(point, clicks=1, **kwargs):
        landed = original(point, clicks=clicks, **kwargs)
        judge.at = 2 if judge.at == 3 else min(judge.at + 1, 3)
        return landed

    mouse.click = advance
    return runner, judge, session


def test_entry_lands_on_whichever_screen_is_current(tmp_path):
    """停在第几格，本轮就从第几格起跑。"""
    expected = {0: NAV_LABELS, 1: NAV_LABELS[1:], 2: NAV_LABELS[2:], 3: NAV_LABELS[3:]}
    for start, want in expected.items():
        runner, judge, session = make_game(tmp_path / str(start), start)
        report = runner.run()

        assert report.completed == 1, start
        assert [item.name for item in report.rounds[0].steps] == want, start
        assert len(session.mouse.clicks) == len(want), start


def test_entry_probe_reuses_the_matching_verdict(tmp_path):
    """入口探测命中「挑战」后，那一步不再判第二次：整轮只判 2 次。"""
    runner, judge, session = make_game(tmp_path / "reuse", 2)
    report = runner.run()

    assert report.probes == 2
    assert judge.seen == [NAV_IDS[2], NAV_IDS[3]]
    assert len(session.mouse.clicks) == 2


class FakeFrame:
    image = object()
    origin = (0, 0)
    size = (10, 10)


class StubCapture:
    """只回一个假 Frame 的截屏器。"""

    def __init__(self):
        self.calls = 0

    def grab(self, region=None):
        self.calls += 1
        return FakeFrame()


def _session_with_pid(pid):
    import runner.session as session_module

    finder = FakeFinder(WindowRect(*CAPTURE_REGION, wid=1))
    if pid is not None:
        finder.pid = pid
    capture = StubCapture()
    session = session_module.Session(
        window=GameWindow(finder=finder, allow_fullscreen=False),
        mouse=FakeMouse(), capture=capture)
    return session_module, session, capture


def test_grab_brings_target_window_frontmost(monkeypatch):
    """区域截屏会拍到遮挡窗口，所以截屏前先把目标窗口置前。"""
    seen = []
    monkeypatch.setattr("actions.mouse.ensure_frontmost",
                        lambda pid, region=None: seen.append((pid, region)) or True)
    session_module, session, capture = _session_with_pid(4242)
    monkeypatch.setattr(session_module, "encode_png", lambda image: b"png")

    png, _frame = session.grab()

    assert seen == [(4242, CAPTURE_REGION)]
    assert capture.calls == 1
    assert png == b"png"


def test_grab_without_pid_still_captures(monkeypatch):
    """拿不到目标进程 PID（非 macOS）时不置前，照常截屏。"""
    seen = []
    monkeypatch.setattr("actions.mouse.ensure_frontmost",
                        lambda pid, region=None: seen.append((pid, region)) or True)
    session_module, session, capture = _session_with_pid(None)
    monkeypatch.setattr(session_module, "encode_png", lambda image: b"png")

    session.grab()

    assert seen == [(None, CAPTURE_REGION)]
    assert capture.calls == 1


# --------------------------------------------------------------------------- #
# 没有 flow.py 时按标注自动生成链式流程
# --------------------------------------------------------------------------- #
def test_load_or_scaffold_creates_chained_flow(root, group):
    """分组没有 flow.py：按截图采集顺序生成链式 steps 并落盘。"""
    assert not group.has_dsl()

    flow, created = load_or_scaffold(group)

    assert created is True
    assert group.dsl_path.is_file()
    assert [item.target for item in flow.steps] == ["挑战", "完成"]
    assert flow.name == "御魂十一"
    assert "on_step_timeout" in flow.hooks


def test_load_or_scaffold_keeps_existing_file(root, group):
    """已有 flow.py 时原样加载，不覆盖用户改过的内容。"""
    write_dsl(root, BASIC_DSL + '\nentry = ["完成"]\n')
    before = group.dsl_path.read_text(encoding="utf-8")

    flow, created = load_or_scaffold(group)

    assert created is False
    assert group.dsl_path.read_text(encoding="utf-8") == before
    assert flow.entry == ("完成",)


def test_load_or_scaffold_without_write_leaves_no_file(root, group):
    """write=False：只在内存构建，不落盘。"""
    flow, created = load_or_scaffold(group, write=False)

    assert created is True
    assert not group.dsl_path.exists()
    assert [item.target for item in flow.steps] == ["挑战", "完成"]


def test_load_or_scaffold_requires_some_annotation(tmp_path):
    """一张标注都没有：生成不出流程，报错指向标注页。"""
    root = build_dataset(tmp_path, shots=[{
        "id": "20260101-000009-000009", "captured_at": "2026-01-01 00:00:09",
        "width": 690, "height": 356, "source": "window", "origin": [189, 251],
        "region": list(CAPTURE_REGION), "window_id": 4242, "process": "Fake",
        "note": "", "annotations": [],
    }])
    group = load_group("御魂十一", root)

    with pytest.raises(DslError, match="没有标注"):
        load_or_scaffold(group)


def test_main_runs_group_without_flow_file(tmp_path):
    """按分组名直接跑：没有 flow.py 也能起来（--dry-run 不截屏不点击）。"""
    import main as main_mod

    root = build_dataset(tmp_path)
    code = main_mod.main(["--group", "御魂十一", "--dry-run", "--data-dir", str(root)])

    assert code == 0
    assert (root / "groups" / "soul11" / "flow.py").is_file()
