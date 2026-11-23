"""坐标换算测试：验证换分辨率 / 窗口不在原点时坐标仍然正确。"""
import pytest

from actions.viewport import Viewport
from config import settings
from config.coordinates import Point


def test_same_size_window_maps_one_to_one():
    """窗口尺寸等于基准尺寸时，逻辑坐标 + 窗口原点 = 屏幕坐标。"""
    vp = Viewport(origin=(300, 200), size=settings.BASE_CLIENT_SIZE)
    assert vp.to_screen(Point(100, 50)) == (400, 250)


def test_double_size_window_scales_coordinates():
    """窗口放大 2 倍时，坐标也放大 2 倍。"""
    base_w, base_h = settings.BASE_CLIENT_SIZE
    vp = Viewport(origin=(0, 0), size=(base_w * 2, base_h * 2))
    assert vp.scale_x == 2.0
    assert vp.scale_y == 2.0
    assert vp.to_screen(Point(100, 50)) == (200, 100)


def test_non_uniform_scaling():
    """宽高缩放比例不同也能分别处理。"""
    vp = Viewport(origin=(0, 0), size=(2048, 768), base_size=(1024, 768))
    assert vp.to_screen(Point(512, 384)) == (1024, 384)


def test_round_trip_conversion():
    """逻辑 -> 屏幕 -> 逻辑 应该回到原点（允许 1 像素取整误差）。"""
    vp = Viewport(origin=(123, 456), size=(1366, 768))
    for point in [Point(0, 0), Point(1023, 767), Point(512, 384), Point(7, 759)]:
        back = vp.to_logical(vp.to_screen(point))
        assert abs(back.x - point.x) <= 1
        assert abs(back.y - point.y) <= 1


def test_calibration_offset_applied():
    """校准偏移量应该叠加到最终屏幕坐标上。"""
    vp = Viewport(origin=(0, 0), size=settings.BASE_CLIENT_SIZE, offset=(5, -3))
    assert vp.to_screen(Point(10, 10)) == (15, 7)


def test_clamp_keeps_point_inside_window():
    """越界坐标会被拉回窗口内，避免点到窗口外。"""
    vp = Viewport(origin=(100, 100), size=(200, 200), base_size=(100, 100))
    assert vp.to_screen(Point(500, 500)) == (299, 299)
    assert vp.to_screen(Point(-50, -50)) == (100, 100)
    # 关掉 clamp 就保留真实计算结果
    assert vp.to_screen(Point(500, 500), clamp=False) == (1100, 1100)


def test_region_matches_window_rect():
    vp = Viewport(origin=(10, 20), size=(1024, 768))
    assert vp.region == (10, 20, 1024, 768)


def test_scale_size():
    vp = Viewport(origin=(0, 0), size=(2048, 1536))
    assert vp.scale_size(100, 50) == (200, 100)


def test_invalid_viewport_size():
    with pytest.raises(ValueError):
        Viewport(origin=(0, 0), size=(0, 100))
