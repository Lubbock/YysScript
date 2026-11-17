"""坐标表测试：确认迁移后的常量与旧脚本数值一致。"""
from config import coordinates as coords


def test_bottom_menu_matches_legacy_action_point():
    """旧 ActionPoint.find_logo: x = 70 + (n-1)*98, y = 650。"""
    assert coords.bottom_menu(1) == coords.Point(70, 650)
    assert coords.bottom_menu(2) == coords.Point(168, 650)
    assert coords.bottom_menu(3) == coords.Point(266, 650)
    assert coords.bottom_menu(9) == coords.Point(854, 650)


def test_awake_dungeon_matches_legacy_action_point():
    """旧 ActionPoint.soul_awake: x = 201 + (n-1)*250, y = 363。"""
    assert coords.awake_dungeon(1) == coords.Point(201, 363)
    assert coords.awake_dungeon(4) == coords.Point(951, 363)


def test_legacy_coordinates_preserved():
    """抽查几个旧脚本里写死的关键坐标，确认迁移过程没有改数值。"""
    assert coords.EXPLORE_ENTRY == coords.Point(1023, 597)
    assert coords.EXPLORE_DIFFICULTY == coords.Point(831, 540)
    assert coords.EXPLORE_START_BATTLE == coords.Point(1048, 558)
    assert coords.EXPLORE_PAGE_FROM == coords.Point(558, 538)
    assert coords.EXPLORE_PAGE_TO == coords.Point(92, 519)
    assert coords.SOUL_ENTRY == coords.Point(320, 381)
    assert coords.SOUL_CHALLENGE == coords.Point(840, 502)
    assert coords.SEAL_PREPARE == coords.Point(1024, 536)
    assert coords.HEART_START == coords.Point(1039, 548)
    assert coords.DOG_SLOT == coords.Point(413, 558)


def test_all_points_inside_base_resolution():
    """所有逻辑坐标都应落在基准客户区内（超出说明写错了或基准分辨率要调）。"""
    from config import settings

    base_w, base_h = settings.BASE_CLIENT_SIZE
    checked = 0
    for name in dir(coords):
        value = getattr(coords, name)
        if isinstance(value, coords.Point):
            assert 0 <= value.x <= base_w + 40, "{} x 超出基准范围".format(name)
            assert 0 <= value.y <= base_h, "{} y 超出基准范围".format(name)
            checked += 1
    assert checked > 20, "坐标常量数量异常，检查是否漏迁移"


def test_shift_helper():
    assert coords.shift(coords.Point(10, 20), dx=5, dy=-3) == coords.Point(15, 17)
