"""逻辑坐标表。

规则：
1. 本文件是**唯一**允许出现游戏界面坐标的地方，其它模块一律引用这里的常量。
2. 所有坐标都是「基准客户区坐标」，基准尺寸见 settings.BASE_CLIENT_SIZE (1024x768)。
   运行时由 actions/viewport.Viewport 按真实窗口大小与位置换算成屏幕坐标，
   所以换分辨率 / 窗口不在屏幕原点都不会失效。
3. 坐标从旧脚本原样迁移，未做重新标定；如果某个按钮点不准，只改这里。
"""
from __future__ import annotations

from typing import NamedTuple, Tuple


class Point(NamedTuple):
    """基准客户区下的一个逻辑坐标。"""

    x: int
    y: int


def shift(point: Point, dx: int = 0, dy: int = 0) -> Point:
    """平移逻辑坐标。"""
    return Point(point.x + dx, point.y + dy)


# --------------------------------------------------------------------------- #
# 底部功能菜单（探索 / 御魂 / 结界突破 / 御灵 ...）
# --------------------------------------------------------------------------- #
BOTTOM_MENU_BASE_X: int = 70
BOTTOM_MENU_STEP_X: int = 98
BOTTOM_MENU_Y: int = 650

#: 1 觉醒材料 | 2 御魂 | 3 结界突破 | 4 御灵 | 5 平安百物语
#: 6 式神委派 | 7 秘闻副本 | 8 地域鬼王 | 9 平安奇缘
MENU_AWAKE_MATERIAL: int = 1
MENU_SOUL: int = 2
MENU_BREAKTHROUGH: int = 3
MENU_SPIRIT: int = 4


def bottom_menu(index: int) -> Point:
    """底部第 index 个功能图标坐标（index 从 1 开始）。"""
    return Point(BOTTOM_MENU_BASE_X + (index - 1) * BOTTOM_MENU_STEP_X, BOTTOM_MENU_Y)


# 觉醒材料副本选择：1 火御魂 | 2 风麒麟 | 3 水麒麟 | 4 雷麒麟
AWAKE_DUNGEON_BASE_X: int = 201
AWAKE_DUNGEON_STEP_X: int = 250
AWAKE_DUNGEON_Y: int = 363


def awake_dungeon(index: int) -> Point:
    """觉醒材料第 index 个副本坐标（index 从 1 开始）。"""
    return Point(AWAKE_DUNGEON_BASE_X + (index - 1) * AWAKE_DUNGEON_STEP_X, AWAKE_DUNGEON_Y)


# --------------------------------------------------------------------------- #
# 探索
# --------------------------------------------------------------------------- #
EXPLORE_ENTRY: Point = Point(1023, 597)      # 右侧「上次探索的副本」入口
EXPLORE_DIFFICULTY: Point = Point(831, 540)  # 进入副本后的难度 / 确认
EXPLORE_START_BATTLE: Point = Point(1048, 558)
EXPLORE_EXIT: Point = Point(558, 533)        # 战斗结算页的退出
EXPLORE_BACK: Point = Point(49, 121)             # 地图左上角返回按钮
EXPLORE_EXIT_OK: Point = Point(686, 419)         # 「是否退出探索」弹窗的确定
EXPLORE_MOVE_RIGHT: Point = Point(674, 590)
EXPLORE_MOVE_LEFT: Point = Point(476, 565)
EXPLORE_MAP_SCROLL: Point = Point(1008, 465)  # 地图滚动条位置

# 翻页拖动：起点 -> 终点
EXPLORE_PAGE_FROM: Point = Point(558, 538)
EXPLORE_PAGE_TO: Point = Point(92, 519)
EXPLORE_PAGE_DURATION: float = 1.0

# --------------------------------------------------------------------------- #
# 狗粮（经验怪 / 满级式神替换）
# --------------------------------------------------------------------------- #
DOG_SLOT: Point = Point(413, 558)         # 队伍中需要替换的槽位（双击打开）
DOG_DRAG_FROM: Point = Point(472, 572)    # 狗粮列表里的拖拽起点
DOG_DRAG_EXTRA_Y: int = 100               # 拖到「满」标记下方一点的位置
DOG_FULL_Y_LIMIT: int = 400               # 只处理 y 小于该值的「满」标记（上半屏）
DOG_BLOCK_LEFT: int = 377                 # 槽位分区左界
DOG_BLOCK_RIGHT: int = 760                # 槽位分区右界
DOG_CHANGE_X_LIMIT: int = 350               # 「满」标记 x 超过此值说明队伍里有满级式神，需要换狗粮
DOG_PAGE_FROM: Point = Point(175, 673)    # 狗粮列表翻页拖动
DOG_PAGE_TO: Point = Point(788, 674)
DOG_PAGE_DURATION: float = 2.0

# --------------------------------------------------------------------------- #
# 御魂
# --------------------------------------------------------------------------- #
SOUL_ENTRY: Point = Point(320, 381)
SOUL_CHALLENGE: Point = Point(840, 502)
SOUL_EXIT: Point = Point(558, 533)

# --------------------------------------------------------------------------- #
# 觉醒
# --------------------------------------------------------------------------- #
AWAKE_CHALLENGE: Point = Point(840, 502)
AWAKE_EXIT: Point = Point(558, 533)
AWAKE_PREPARE: Point = Point(1024, 536)

# --------------------------------------------------------------------------- #
# 妖气封印（组队刷）
# --------------------------------------------------------------------------- #
SEAL_ENTRY: Point = Point(216, 619)
SEAL_TEAMMATE: Point = Point(674, 617)
SEAL_PREPARE: Point = Point(1024, 536)
SEAL_EXIT: Point = Point(217, 452)
SEAL_START_BATTLE: Point = Point(902, 573)

# --------------------------------------------------------------------------- #
# 结界突破：3x3 九宫格
# --------------------------------------------------------------------------- #
BREAKTHROUGH_ENTRY: Point = Point(281, 649)
BREAKTHROUGH_GRID_X: Tuple[int, ...] = (275, 576, 867)
BREAKTHROUGH_GRID_Y: Tuple[int, ...] = (198, 319, 436)
BREAKTHROUGH_CONFIRM: Point = Point(1022, 541)
BREAKTHROUGH_REFRESH: Point = Point(927, 541)
BREAKTHROUGH_REFRESH_CONFIRM: Point = Point(667, 443)


def breakthrough_cell(index: int) -> Point:
    """九宫格第 index 个结界坐标（index 1~9，逐行）。"""
    if not 1 <= index <= 9:
        raise ValueError("结界突破九宫格 index 必须在 1~9，收到 {}".format(index))
    row, col = divmod(index - 1, 3)
    return Point(BREAKTHROUGH_GRID_X[col], BREAKTHROUGH_GRID_Y[row])


# --------------------------------------------------------------------------- #
# 御心道场
# --------------------------------------------------------------------------- #
HEART_ENTRY: Point = Point(384, 367)
HEART_SELECT: Point = Point(817, 203)
HEART_CONFIRM: Point = Point(610, 399)
HEART_PREPARE: Point = Point(975, 531)
HEART_START: Point = Point(1039, 548)

# --------------------------------------------------------------------------- #
# 通用
# --------------------------------------------------------------------------- #
#: 窗口定位后把窗口拖到屏幕左上角的目标位置。
WINDOW_DRAG_TARGET: Point = Point(10, 20)
