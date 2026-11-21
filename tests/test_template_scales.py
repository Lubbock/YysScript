"""模板匹配尺度下限的策略测试（vision/scales.py，纯计算，不需要 cv2）。

**要防的事故**（真机踩过）：尺度候选一直试到 0.3，41×51 的「碎片章节头像」缩到
x0.5 只剩 20×26 像素 —— 这么小的灰度块在任意画面上都能撞上 0.96 分。脚本照着这个
假命中去点击，在探索章节界面上反复点同一个空白处（829,363），近一分钟毫无进展，
永远进不了式神碎片。

所以约束不是「比例」而是**缩放后的绝对像素数**：低于下限的尺度必须直接不可用，
并且全部尺度都被筛掉时也要退回 1.0（匹配不到就走「未识别」，不要乱点）。
"""
import pytest

from config import settings
from vision.scales import scale_allowed, usable_scales


# --------------------------------------------------------------------------- #
# scale_allowed：单个尺度可不可信
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("width,height,scale,expected", [
    (41, 51, 1.0, True),     # 碎片章节头像原尺寸
    (41, 51, 0.8, True),     # 33x41：还在下限之上
    (41, 51, 0.7, False),    # 29x36：短边已低于 32
    (41, 51, 0.5, False),    # 20x25：真机撞出 0.96 的那个尺度
    (41, 51, 0.3, False),
    (222, 82, 1.0, True),    # 碎片入口面板
    (222, 82, 0.8, True),    # 178x66
    (222, 82, 0.3, False),   # 67x25：真机撞出 0.85 的那个尺度
    (56, 55, 0.5, False),    # 挑战按钮缩到一半也不可信
    (308, 86, 0.8, True),    # 列表行 246x69：仍在下限之上
    (308, 86, 0.4, True),    # 123x34：下限卡的是**短边**，宽模板能扛更小的尺度
    (308, 86, 0.35, False),  # 108x30：短边跌破 32，不可信
])
def test_scale_allowed_by_absolute_pixels(width, height, scale, expected):
    assert scale_allowed(width, height, scale) is expected


def test_zero_and_negative_scales_rejected():
    assert scale_allowed(100, 100, 0) is False
    assert scale_allowed(100, 100, -1) is False


def test_min_side_can_be_overridden():
    """下限可调：放宽到 20 时 0.5 尺度可用，收紧到 64 时 1.0 都不够。"""
    assert scale_allowed(41, 51, 0.5, min_side=20) is True
    assert scale_allowed(41, 51, 1.0, min_side=64) is False


# --------------------------------------------------------------------------- #
# usable_scales：整组尺度怎么筛
# --------------------------------------------------------------------------- #
def test_usable_scales_drops_small_scales_in_order():
    kept = usable_scales(41, 51, (1.0, 0.9, 0.8, 0.7, 0.5, 0.3))
    assert kept == (1.0, 0.9, 0.8)


def test_usable_scales_falls_back_to_1_0_when_nothing_left():
    """全都低于下限（模板本身很小）时退回 1.0：宁可识别不到，也不要乱点。"""
    assert usable_scales(20, 24, (0.9, 0.5, 0.3)) == (1.0,)


def test_usable_scales_keeps_large_templates_whole_range():
    """大模板（106x60 骨女 / 316x64 第九章）整组尺度都可用，不受影响。"""
    scales = (1.0, 0.9, 0.8)
    assert usable_scales(106, 60, scales) == scales
    assert usable_scales(316, 64, scales) == scales


def test_empty_scale_tuple_falls_back_to_1_0():
    assert usable_scales(300, 300, ()) == (1.0,)


# --------------------------------------------------------------------------- #
# 配置本身的约束
# --------------------------------------------------------------------------- #
def test_default_scales_never_shrink_below_the_floor():
    """默认尺度候选里最大的那个缩减，也必须让中位尺寸模板待在下限之上。"""
    smallest = min(settings.TEMPLATE_SCALES)
    assert smallest >= 0.8, "尺度下限收到 {:.1f}，不要放回 0.3 那种量级".format(smallest)
    assert settings.MIN_SCALED_TEMPLATE_SIDE >= 32


def test_template_matcher_applies_the_floor():
    """TemplateMatcher._scaled 用的是同一个下限。

    这是本目录唯一需要 cv2 的测试（template_matcher 依赖它），缺 cv2 时跳过，
    仍然保住「测试整体不需要 cv2 / 不截屏 / 不点击」的约定。
    """
    pytest.importorskip("cv2")
    from vision import template_matcher as tm

    class FakeArray:
        """伪装 cv2 数组：只需要 shape。"""

        def __init__(self, w, h):
            self.shape = (h, w, 3)

    # 20x25 的尺度（41x51 @ 0.5）必须被拒
    assert tm.TemplateMatcher._scaled(FakeArray(41, 51), 0.5) is None
    # 原尺寸直接返回自身
    tpl = FakeArray(41, 51)
    assert tm.TemplateMatcher._scaled(tpl, 1.0) is tpl
