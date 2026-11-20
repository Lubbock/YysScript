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

#: macOS 下默认按进程名定位的窗口：系统自带「iPhone Mirroring」（iPhone 镜像）窗口，
#: 窗口内容即连到 Mac 的 iOS 设备屏幕，窗口内的点击会直接透传到手机。
#: 可用环境变量 YYS_MAC_WINDOW_PROCESS 覆盖。
MAC_WINDOW_PROCESS: str = os.environ.get("YYS_MAC_WINDOW_PROCESS", "iPhone Mirroring")

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

#: 模板匹配尺度候选。运行截屏与模板采集尺度不一致时（例如 macOS 上截 iOS 镜像窗口），
#: 逐个尺度缩放模板尝试匹配，取置信度最高的命中。
#: 可用环境变量 YYS_TEMPLATE_SCALES 覆盖，例如 "1.0,0.8,0.6"。
TEMPLATE_SCALES: Tuple[float, ...] = (
    (1.0,) if os.name == "nt" else (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3)
)
_ENV_SCALES = os.environ.get("YYS_TEMPLATE_SCALES")
if _ENV_SCALES:
    TEMPLATE_SCALES = tuple(float(item) for item in _ENV_SCALES.split(",") if item.strip())


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
# 循环计时 / 自适应等待（core/timing.py）
# --------------------------------------------------------------------------- #
#: 总开关。关掉后 CycleTimer.plan() 永远返回「不盲等 + 调用方给的间隔」，
#: 也就是改造前的行为。环境变量 YYS_ADAPTIVE_WAIT=0 可临时关闭，
#: 命令行 --no-adaptive-wait 与之等价。
ADAPTIVE_WAIT: bool = os.environ.get("YYS_ADAPTIVE_WAIT", "1").strip().lower() not in (
    "0", "false", "no", "off")

#: 参与统计的最近样本数（滑动窗口）
TIMING_WINDOW: int = 20
#: 攒够多少个「可用样本」才算收敛、可以开始盲等；不足时行为与改造前完全一致
TIMING_WARMUP_SAMPLES: int = 5
#: 异常值判据：样本 > p50 * 该倍数就不计入 min / p10（仍然入库供审计）
TIMING_OUTLIER_FACTOR: float = 2.5
#: 异常判据的**绝对下限**（秒）：阈值 = max(p50 × 倍数, p50 + 下限)。
#: 只用相对倍数时，p50 很小（例如「点完结算瞬间就回到挑战界面」的 0.04 秒）会把阈值
#: 压到近 0，之后每个真实样本都被判成异常剔除 -> usable 永远攒不够 -> 永久不收敛。
#: 对 p50 较大的阶段（战斗几十秒）相对倍数仍占主导，判据不会变松。
TIMING_OUTLIER_FLOOR: float = 30.0
#: 连续多少次异常样本就丢掉历史窗口、回到探测频率重新收敛。
#: 这是「等太久导致最小值永远收敛不下来」的兜底。
TIMING_OVERRUN_RESET: int = 2
#: 盲等时长 = p10 * 安全系数 - 一次识图成本。小于 1 表示宁可早点开始轮询，
#: 也不要在界面已经变了的时候还在瞎等。
TIMING_SAFETY: float = 0.85
#: 触发过回退后临时使用的安全系数（更保守），攒够下面这么多样本后恢复
TIMING_RESET_SAFETY: float = 0.5
TIMING_RESET_RECOVER_SAMPLES: int = 10
#: 盲等硬上限（秒）：估计再离谱也不会长时间瞎等
TIMING_MAX_BLIND_WAIT: float = 90.0
#: 收敛后轮询识图的间隔（秒）。比 DEFAULT_WAIT_INTERVAL 更细，命中更及时，
#: 因为大头已经由盲等省掉了。
TIMING_FINE_INTERVAL: float = 1.0
#: 盲等最多吃掉 timeout 减去这个值，剩下的留给细粒度轮询
TIMING_FINE_WINDOW: float = 10.0
#: 「一次截屏 + 模板匹配」成本的滑动窗口长度（只在内存，不入库）
TIMING_PROBE_WINDOW: int = 10
#: 流程引擎连续多少次什么都没识别到，就广播一次 state.unknown
UNKNOWN_POLL_LIMIT: int = 5


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
