"""macOS 礼貌点击的「窗口激活失败 -> 自动重试 -> 不崩进程」测试。

真机踩到的问题：激活目标窗口失败时 `_polite_session.__enter__` 抛裸 RuntimeError，
它不是 YysError，一路穿到 main.py 变成未捕获 traceback，整晚挂机白跑。
现在的行为：自动重试若干次；仍失败就**跳过这一次操作**（返回 None）让流程下一拍重试；
只有连续失败到上限才抛 WindowActivationError（YysError -> 退出码 1 + 一句话）。

全部用打桩替代真实的 osascript / Quartz / AppKit，不会真的动用户的光标和焦点。
"""
import sys

import pytest

pytest.importorskip("pyautogui", reason="actions.mouse 在模块级 import pyautogui")

import actions.mouse as mouse_mod                      # noqa: E402
from actions.mouse import HumanMouse, _polite_session   # noqa: E402
from config import settings                             # noqa: E402
from core.errors import WindowActivationError, YysError  # noqa: E402

PID = 4242
OTHER_PID = 999


# --------------------------------------------------------------------------- #
# 打桩工具
# --------------------------------------------------------------------------- #
class ActivationStub:
    """替身：记录 _set_frontmost / _wait_frontmost 的调用，按脚本决定第几次成功。"""

    def __init__(self, succeed_on=1, err="osascript 超时"):
        self.succeed_on = succeed_on          # 第几次尝试开始成功（0 = 永不成功）
        self.err = err
        self.set_calls = 0
        self.wait_calls = 0
        self.slept = []

    def set_frontmost(self, pid):
        self.set_calls += 1
        return "" if self._ok(self.set_calls) else self.err

    def wait_frontmost(self, pid, timeout=None):
        self.wait_calls += 1
        return self._ok(self.wait_calls)

    def _ok(self, attempt):
        return self.succeed_on != 0 and attempt >= self.succeed_on

    def sleep(self, seconds):
        self.slept.append(seconds)

    def install(self, monkeypatch):
        monkeypatch.setattr(mouse_mod, "_set_frontmost", self.set_frontmost)
        monkeypatch.setattr(mouse_mod, "_wait_frontmost", self.wait_frontmost)
        monkeypatch.setattr(mouse_mod.time, "sleep", self.sleep)
        return self


@pytest.fixture()
def no_side_effects(monkeypatch):
    """屏蔽真实的光标 / 前台 / 休眠查询，测试不碰用户的桌面。"""
    monkeypatch.setattr(mouse_mod, "_capture_cursor_position", lambda: (10.0, 20.0))
    monkeypatch.setattr(mouse_mod, "_frontmost_pid", lambda: OTHER_PID)
    monkeypatch.setattr(mouse_mod, "_warn_if_display_asleep", lambda: None)
    monkeypatch.setattr(mouse_mod, "_warp_to", lambda *a, **k: None)
    return monkeypatch


def polite_mouse(monkeypatch, clicks=None):
    """构造一个走礼貌点击路径的 HumanMouse（不依赖真实平台 / Quartz）。"""
    mouse = HumanMouse(humanize=False)
    monkeypatch.setattr(mouse, "_target_pid", lambda: PID)
    recorded = clicks if clicks is not None else []
    monkeypatch.setattr(mouse_mod, "_session_click", lambda point: recorded.append(point))
    monkeypatch.setattr(mouse_mod, "_session_drag", lambda *a, **k: recorded.append(a))
    monkeypatch.setattr(mouse_mod, "_session_scroll", lambda *a, **k: recorded.append(a))
    return mouse, recorded


# --------------------------------------------------------------------------- #
# _activate_frontmost：重试逻辑
# --------------------------------------------------------------------------- #
def test_first_attempt_success_does_not_retry(monkeypatch):
    stub = ActivationStub(succeed_on=1).install(monkeypatch)
    ok, err = mouse_mod._activate_frontmost(PID)

    assert (ok, err) == (True, "")
    assert stub.set_calls == 1
    assert stub.slept == [], "一次就成功不该有任何重试间隔"


def test_retries_until_success(monkeypatch):
    stub = ActivationStub(succeed_on=3).install(monkeypatch)
    ok, err = mouse_mod._activate_frontmost(PID, attempts=5, pause=0.5)

    assert ok is True
    assert stub.set_calls == 3
    assert stub.slept == [0.5, 0.5], "两次失败后各歇一次，成功后不再歇"


def test_gives_up_after_all_attempts(monkeypatch):
    stub = ActivationStub(succeed_on=0).install(monkeypatch)
    ok, err = mouse_mod._activate_frontmost(PID, attempts=3, pause=0.0)

    assert ok is False
    assert err == "osascript 超时"
    assert stub.set_calls == 3


def test_attempts_default_comes_from_settings(monkeypatch):
    stub = ActivationStub(succeed_on=0).install(monkeypatch)
    monkeypatch.setattr(settings, "ACTIVATE_MAX_ATTEMPTS", 4)
    ok, _ = mouse_mod._activate_frontmost(PID, pause=0.0)

    assert ok is False
    assert stub.set_calls == 4


def test_attempts_is_at_least_one(monkeypatch):
    stub = ActivationStub(succeed_on=0).install(monkeypatch)
    mouse_mod._activate_frontmost(PID, attempts=0, pause=0.0)
    assert stub.set_calls == 1


def test_set_frontmost_raising_is_not_fatal(monkeypatch):
    """osascript 直接抛异常时（_set_frontmost 内部已兜底）仍应走完重试并返回失败。"""
    stub = ActivationStub(succeed_on=2, err="").install(monkeypatch)
    ok, _ = mouse_mod._activate_frontmost(PID, attempts=3, pause=0.0)
    assert ok is True and stub.set_calls == 2


# --------------------------------------------------------------------------- #
# _polite_session：激活失败抛 WindowActivationError（而不是 RuntimeError）
# --------------------------------------------------------------------------- #
def test_session_raises_yyserror_when_activation_fails(no_side_effects):
    ActivationStub(succeed_on=0).install(no_side_effects)

    with pytest.raises(WindowActivationError) as exc_info:
        with _polite_session(PID):
            pass  # pragma: no cover - 不该进来
    assert isinstance(exc_info.value, YysError)
    assert "无法激活目标窗口" in str(exc_info.value)
    assert "自动化" in str(exc_info.value)


def test_session_succeeds_after_retry(no_side_effects):
    stub = ActivationStub(succeed_on=2).install(no_side_effects)

    with _polite_session(PID) as session:
        assert session.activated is True
    assert stub.set_calls == 2


def test_session_skips_activation_when_already_frontmost(no_side_effects):
    no_side_effects.setattr(mouse_mod, "_frontmost_pid", lambda: PID)
    stub = ActivationStub(succeed_on=0).install(no_side_effects)

    with _polite_session(PID) as session:
        assert session.activated is False, "本来就是前台，不需要抢焦点"
    assert stub.set_calls == 0


def test_capture_cursor_position_tolerates_missing_appkit(monkeypatch):
    """AppKit 不可用时返回 None —— 还原光标只是礼貌，不是点击成功的前提。"""
    monkeypatch.setitem(sys.modules, "AppKit", None)
    assert mouse_mod._capture_cursor_position() is None


def test_session_still_clicks_without_cursor_position(no_side_effects):
    """读不到用户光标位置只是「点完不还原」，不该让整次点击失败。"""
    no_side_effects.setattr(mouse_mod, "_capture_cursor_position", lambda: None)
    ActivationStub(succeed_on=1).install(no_side_effects)

    with _polite_session(PID) as session:
        assert session.old_xy is None
        assert session.activated is True, "拿不到光标位置也必须照常点击"


# --------------------------------------------------------------------------- #
# HumanMouse：失败时跳过操作而不是崩掉
# --------------------------------------------------------------------------- #
def test_click_returns_none_when_activation_fails(no_side_effects):
    monkeypatch = no_side_effects
    ActivationStub(succeed_on=0).install(monkeypatch)
    mouse, clicks = polite_mouse(monkeypatch)

    assert mouse.click((100, 200)) is None, "点击没送达应返回 None，而不是抛异常"
    assert clicks == [], "没激活成功就绝不能真的点下去"
    assert mouse.activation_failures == 1
    assert mouse._consecutive_activation_failures == 1


def test_click_delivered_when_activation_succeeds(no_side_effects):
    monkeypatch = no_side_effects
    ActivationStub(succeed_on=1).install(monkeypatch)
    mouse, clicks = polite_mouse(monkeypatch)

    assert mouse.click((100, 200)) == (100, 200)
    assert clicks == [(100, 200)]
    assert mouse.activation_failures == 0


def test_success_resets_consecutive_counter(no_side_effects):
    monkeypatch = no_side_effects
    stub = ActivationStub(succeed_on=0).install(monkeypatch)
    mouse, _ = polite_mouse(monkeypatch)

    mouse.click((1, 1))
    mouse.click((2, 2))
    assert mouse._consecutive_activation_failures == 2

    stub.succeed_on = 1                      # 恢复了
    assert mouse.click((3, 3)) == (3, 3)
    assert mouse._consecutive_activation_failures == 0
    assert mouse.activation_failures == 2, "累计次数不清零，便于事后排查"


def test_drag_and_scroll_skip_silently(no_side_effects):
    monkeypatch = no_side_effects
    ActivationStub(succeed_on=0).install(monkeypatch)
    mouse, calls = polite_mouse(monkeypatch)

    assert mouse.drag((0, 0), (10, 10)) is None
    assert mouse.scroll(3, point=(5, 5)) is None
    assert calls == []
    assert mouse.activation_failures == 2


def test_persistent_failure_eventually_aborts_cleanly(no_side_effects):
    """连续失败到上限就中止 —— 但抛的是 YysError，main.py 能转成退出码 1。"""
    monkeypatch = no_side_effects
    ActivationStub(succeed_on=0).install(monkeypatch)
    monkeypatch.setattr(settings, "ACTIVATE_MAX_CONSECUTIVE_FAILURES", 3)
    mouse, _ = polite_mouse(monkeypatch)

    mouse.click((1, 1))
    mouse.click((2, 2))
    with pytest.raises(WindowActivationError) as exc_info:
        mouse.click((3, 3))
    assert isinstance(exc_info.value, YysError)
    assert "连续 3 次无法激活" in str(exc_info.value)


def test_limit_zero_never_aborts(no_side_effects):
    monkeypatch = no_side_effects
    ActivationStub(succeed_on=0).install(monkeypatch)
    monkeypatch.setattr(settings, "ACTIVATE_MAX_CONSECUTIVE_FAILURES", 0)
    mouse, _ = polite_mouse(monkeypatch)

    for index in range(25):
        assert mouse.click((index, index)) is None
    assert mouse.activation_failures == 25


def test_non_polite_path_is_untouched(no_side_effects, monkeypatch):
    """没注入 pid（Windows 客户端 / 全屏模式）时完全走原来的 pyautogui 路径。"""
    mouse = HumanMouse(humanize=False)
    monkeypatch.setattr(mouse, "_target_pid", lambda: None)
    calls = []
    monkeypatch.setattr(mouse_mod.pyautogui, "moveTo", lambda *a, **k: None)
    monkeypatch.setattr(mouse_mod.pyautogui, "click",
                        lambda **kwargs: calls.append(kwargs))

    assert mouse.click((7, 8)) == (7, 8)
    assert calls and calls[0]["x"] == 7 and calls[0]["y"] == 8
    assert mouse.activation_failures == 0
