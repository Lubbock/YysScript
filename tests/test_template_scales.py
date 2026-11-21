"""模板匹配尺度下限的策略测试（vision/scales.py，纯计算，不需要 cv2）。

**两个真机锚点**（2026-11-21，iPhone Mirroring 窗口 690x356，同一画面逐尺度量出来的）：

| 模板 | 尺寸 | 尺度 | 缩放后 | 分数 | 结论 |
|---|---|---|---|---|---|
| 碎片章节头像 | 41×51 | x0.5 | 20×25 | 0.96 | **噪声**，在探索章节界面上乱指，必须挡掉 |
| 碎片入口面板 | 222×82 | x0.3 | 67×25 | 0.85~0.93 | **噪声**，真机照着点了右上角，必须挡掉 |
| 碎片打完（结算） | 186×208 | x0.4 | 74×83 | 0.99 | **真命中**，这张老模板按约 2.5 倍比例截的，必须放过 |

所以约束是「缩放后的**绝对像素数**」，下限卡在 24 这一带：既要放过 74×83，
又要挡住 20×25；67×25 那条是靠尺度表只到 0.4 挡掉的。

**这里也留着一个我自己踩过的坑**：上一版把尺度表收到 1.0~0.8，理由是「模板都该按当前
窗口比例截」—— 真机上把结算识别整个废掉（战斗打完结算点不掉，连续 35 拍啥也没识别到）。
`test_battle_end_template_still_usable` 就是那条错误的回归测试。
"""
import os

import pytest

from config import settings
from vision.scales import scale_allowed, usable_scales

#: Windows 上尺度表只有 (1.0,)，这些跟多尺度有关的断言不适用
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="Windows 只跑尺度 1.0")


# --------------------------------------------------------------------------- #
# scale_allowed：单个尺度可不可信（对齐上表锚点）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("width,height,scale,expected,why", [
    (41, 51, 1.0, True, "章节头像原尺寸"),
    (41, 51, 0.6, True, "25x31：刚好过下限"),
    (41, 51, 0.5, False, "20x25：真机撞出 0.96 的那个噪声"),
    (41, 51, 0.3, False, "12x15：更不用说"),
    (186, 208, 1.0, True, "原尺寸"),
    (186, 208, 0.4, True, "74x83：结算画面的真命中 0.99，必须放过"),
    (222, 82, 0.8, True, "178x66"),
    (222, 82, 0.5, True, "111x41：短边仍在下限之上（这条噪声得靠阈值挡）"),
    (222, 82, 0.3, True, "67x25：短边 25 刚好过 24 的下限，它靠**尺度表不含 0.3** 被排除，"
                         "不是靠下限；0.4 = 89x33 那条噪声再由 0.85 阈值挡掉"),
    (56, 55, 0.5, True, "28x28：挑战按钮缩小一半仍在下限之上"),
    (56, 55, 0.4, False, "22x22：再小就不行了"),
])
def test_scale_allowed_by_absolute_pixels(width, height, scale, expected, why):
    assert scale_allowed(width, height, scale) is expected, why


def test_zero_and_negative_scales_rejected():
    assert scale_allowed(100, 100, 0) is False
    assert scale_allowed(100, 100, -1) is False


def test_min_side_can_be_overridden():
    assert scale_allowed(41, 51, 0.5, min_side=20) is True
    assert scale_allowed(41, 51, 1.0, min_side=64) is False


def test_floor_sits_between_the_noise_and_the_real_hit():
    """下限必须同时满足：挡掉 20×25 的噪声、放过 74×83 的结算真命中。"""
    floor = settings.MIN_SCALED_TEMPLATE_SIDE
    assert floor > 20, "否则 41x51@0.5 = 20x25 的噪声挡不住"
    assert floor <= 74, "否则 186x208@0.4 = 74x83 的结算真命中会被一起废掉"


# --------------------------------------------------------------------------- #
# usable_scales：整组尺度怎么筛
# --------------------------------------------------------------------------- #
def test_usable_scales_drops_scales_below_the_floor():
    kept = usable_scales(41, 51, (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.3))
    assert kept == (1.0, 0.9, 0.8, 0.7, 0.6)


def test_usable_scales_falls_back_to_1_0_when_nothing_left():
    """全都低于下限时退回 1.0：宁可识别不到走「未识别」，也不要乱点。"""
    assert usable_scales(20, 24, (0.9, 0.5, 0.3)) == (1.0,)


def test_empty_scale_tuple_falls_back_to_1_0():
    assert usable_scales(300, 300, ()) == (1.0,)


@POSIX_ONLY
def test_small_templates_only_get_the_upper_part_of_the_table():
    """小模板（41×51）在默认尺度表下只剩 1.0~0.6。"""
    assert usable_scales(41, 51) == (1.0, 0.9, 0.8, 0.7, 0.6)


# --------------------------------------------------------------------------- #
# 默认尺度表本身：两端都要卡住
# --------------------------------------------------------------------------- #
@POSIX_ONLY
def test_battle_end_template_still_usable():
    """结算模板（186×208）必须仍能走 x0.4 / x0.5。

    回归：上一版把尺度收到 1.0~0.8，以为所有模板都是当前窗口比例，
    真机上战斗打完点不掉结算 —— 这张老模板其实是按约 2.5 倍比例截的。
    """
    kept = usable_scales(186, 208)
    assert 0.4 in kept and 0.5 in kept, "结算画面的真命中就在这两个尺度上"


@POSIX_ONLY
def test_default_scales_exclude_the_0_3_noise():
    """默认尺度表：不要 0.3（入口面板 67×25 噪声），但要留到 0.4（结算 74×83 真命中）。"""
    scales = settings.TEMPLATE_SCALES
    assert 0.3 not in scales, "0.3 会把模板压到 67x25 这种量级，纯噪声"
    assert min(scales) == 0.4, "再小会废掉按 2.5 倍比例截的老模板"
    assert 1.0 in scales, "按当前窗口比例截的模板要能在 1.0 上命中"
    assert settings.MIN_SCALED_TEMPLATE_SIDE == 24


# --------------------------------------------------------------------------- #
# 与 TemplateMatcher 的接线
# --------------------------------------------------------------------------- #
def test_template_matcher_applies_the_floor():
    """TemplateMatcher._scaled 用的是同一个下限。

    这是本目录唯一需要 cv2 的测试（template_matcher 依赖它），缺 cv2 时跳过，
    仍然保住「测试整体不需要 cv2 / 不截屏 / 不点击」的约定。
    """
    pytest.importorskip("cv2")
    import numpy as np

    from vision import template_matcher as tm

    def gray(w, h):
        return np.zeros((h, w), dtype=np.uint8)

    # 20x25（41x51 @ 0.5）必须被拒：真机 0.96 噪声就是它
    assert tm.TemplateMatcher._scaled(gray(41, 51), 0.5) is None
    # 74x83（186x208 @ 0.4）必须放过：结算画面的真命中
    assert tm.TemplateMatcher._scaled(gray(186, 208), 0.4) is not None
    tpl = gray(41, 51)
    assert tm.TemplateMatcher._scaled(tpl, 1.0) is tpl, "尺度 1.0 直接用原模板"


def test_usable_helper_warns_once_per_template():
    """尺度被筛掉时要 warn（模板裁错比例是配置问题），但每张模板只喊一次。"""
    pytest.importorskip("cv2")
    import numpy as np

    from vision.template_matcher import TemplateMatcher

    matcher = TemplateMatcher.__new__(TemplateMatcher)   # 不建 capture，只测 _usable
    matcher._warned = set()
    small = np.zeros((51, 41), dtype=np.uint8)           # 41 宽 x 51 高

    kept = matcher._usable("碎片章节头像.png", small, (1.0, 0.9, 0.8, 0.5, 0.3))
    assert kept == (1.0, 0.9, 0.8)
    assert "碎片章节头像.png" in matcher._warned, "第一次筛掉必须喊出来"

    before = set(matcher._warned)
    matcher._usable("碎片章节头像.png", small, (1.0, 0.5))
    assert matcher._warned == before, "同一张模板不能每次识图都刷一条 warning"
