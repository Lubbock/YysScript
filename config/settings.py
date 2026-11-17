"""全局配置。

所有可调参数集中在本文件，禁止在其他模块写死路径 / 分辨率 / 阈值。
路径类配置支持环境变量覆盖，方便在不同机器上部署（旧代码把 E:\\github 写死在源码里）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent


def _path(env_key: str, default: Path) -> Path:
    """读取环境变量指定的路径，未设置时使用默认值。"""
    raw = os.environ.get(env_key)
    return Path(raw).expanduser() if raw else default


ASSETS_DIR: Path = _path("YYS_ASSETS_DIR", PROJECT_ROOT / "assets")
TEMPLATE_DIR: Path = _path("YYS_TEMPLATE_DIR", ASSETS_DIR / "templates")
VAR_DIR: Path = _path("YYS_VAR_DIR", PROJECT_ROOT / "var")
LOG_DIR: Path = _path("YYS_LOG_DIR", VAR_DIR / "logs")
LOG_FILE: Path = LOG_DIR / "yys_script.log"
DB_PATH: Path = _path("YYS_DB_PATH", VAR_DIR / "gray_scan.db")

#: 历史耗时样本上限，超过后按 keep 数量裁剪
DURATION_SAMPLE_LIMIT: int = 1000
DURATION_SAMPLE_KEEP: int = 500


def ensure_dirs() -> None:
    """确保运行时目录存在（日志、数据库）。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    VAR_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# 分辨率与窗口
# --------------------------------------------------------------------------- #
#: 基准客户区分辨率。config/coordinates.py 里的所有逻辑坐标都基于这个尺寸，
#: 运行时由 actions/viewport.py 换算到真实窗口。
BASE_CLIENT_SIZE: Tuple[int, int] = (1024, 768)

#: 旧脚本做颜色检测时的截屏基准分辨率（Monster 里 resize(640,400) 后再 *2 的来源）。
BASE_SCREEN_SIZE: Tuple[int, int] = (1280, 800)

#: 颜色检测时的缩放尺寸。缩小后处理，速度显著快于全图模板匹配。
DETECT_SIZE: Tuple[int, int] = (640, 400)

#: Windows 上游戏窗口的标题 / 类名，用于定位窗口。
GAME_WINDOW_TITLE: str = "阴阳师-网易游戏"
GAME_WINDOW_CLASS: str = "Win32Window"

#: 找不到游戏窗口时的行为：True = 退化为「整个屏幕就是客户区」（兼容模拟器 / mac）。
FALLBACK_TO_FULLSCREEN: bool = True

#: 人工校准偏移量 (dx, dy)。换算后的屏幕坐标会再加上它，
#: 用于修正客户端边框、DPI 缩放等造成的整体偏差。
CALIBRATION_OFFSET: Tuple[int, int] = (0, 0)


# --------------------------------------------------------------------------- #
# 图像识别
# --------------------------------------------------------------------------- #
#: 模板匹配默认阈值（TM_CCOEFF_NORMED）
DEFAULT_THRESHOLD: float = 0.70
#: 需要高精度定位时使用的阈值（例如章节图标）
STRICT_THRESHOLD: float = 0.90
#: 一次匹配最多返回多少个结果，防止满屏噪点
MAX_MATCHES: int = 32
#: 匹配结果非极大值抑制的合并距离（像素），去掉同一个按钮的重复命中
MATCH_MERGE_DISTANCE: int = 12


# --------------------------------------------------------------------------- #
# 状态机 / 流程
# --------------------------------------------------------------------------- #
#: 等待某个状态出现的默认超时（秒）与轮询间隔（秒）
DEFAULT_WAIT_TIMEOUT: float = 30.0
DEFAULT_WAIT_INTERVAL: float = 2.0
#: 一次探索最多拖动地图的次数
EXPLORE_MAX_PAGE: int = 4
#: 单页地图连续多少次找不到怪才翻页
EXPLORE_LOST_LIMIT: int = 2
#: 体力耗尽时的退出码（沿用旧脚本约定）
EXIT_CODE_ABORT: int = 300


# --------------------------------------------------------------------------- #
# 拟人化操作
# --------------------------------------------------------------------------- #
#: pyautogui 全局设置
PYAUTOGUI_PAUSE: float = 0.2
PYAUTOGUI_FAILSAFE: bool = False

#: 每次点击前后附加的随机停顿区间（秒），旧代码 personal_pause() 的行为
HUMAN_PAUSE_RANGE: Tuple[float, float] = (0.0, 1.0)
#: 点击落点的随机抖动半径（逻辑像素）
HUMAN_JITTER: int = 3
#: 拖动时插值步数，越大轨迹越像人手
HUMAN_DRAG_STEPS: int = 12
