"""全局配置。

所有可调参数集中在本文件，禁止在其他模块写死路径 / 分辨率 / 阈值。
路径类配置支持环境变量覆盖，方便在不同机器上部署。
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
#: 基准客户区分辨率。逻辑坐标 `config.coordinates.Point` 基于这个尺寸，
#: 运行时由 actions/viewport.py 换算到真实窗口。
BASE_CLIENT_SIZE: Tuple[int, int] = (1024, 768)


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

#: 激活目标窗口的最大尝试次数（含首次）。macOS 礼貌点击必须先把镜像 / 游戏窗口
#: 置前，而单次激活失败很常见 —— 用户正好在切窗口、系统刚从休眠唤醒、
#: osascript 偶发超时，这些都是瞬时的，所以自动重试。
ACTIVATE_MAX_ATTEMPTS: int = 3
#: 每次激活后等待「真的成为前台」的超时（秒）
ACTIVATE_WAIT_TIMEOUT: float = 1.5
#: 两次激活尝试之间的间隔（秒）
ACTIVATE_RETRY_PAUSE: float = 0.5
#: 连续多少次操作都因激活失败被跳过，就中止流程（0 = 永不中止，一直跳过重试）。
#: 设这个上限是为了避免「自动化权限被收回后，脚本空跑一整晚什么都没做」。
ACTIVATE_MAX_CONSECUTIVE_FAILURES: int = 10



# --------------------------------------------------------------------------- #
# runner / 流程引擎
# --------------------------------------------------------------------------- #
#: 轮询识图的默认间隔（秒），样本不足时的兜底节奏
DEFAULT_WAIT_INTERVAL: float = 2.0
#: 体力耗尽时的退出码
EXIT_CODE_ABORT: int = 300

# --------------------------------------------------------------------------- #
# 循环计时 / 自适应等待（core/timing.py）
# --------------------------------------------------------------------------- #
#: 关掉后 CycleTimer.plan() 永远返回「不盲等 + 调用方给的间隔」。
#: 环境变量 YYS_ADAPTIVE_WAIT=0 与命令行 --no-adaptive-wait 等价。
ADAPTIVE_WAIT: bool = os.environ.get("YYS_ADAPTIVE_WAIT", "1").strip().lower() not in (
    "0", "false", "no", "off")

#: 参与统计的最近样本数（滑动窗口）
TIMING_WINDOW: int = 20
#: 攒够多少个「可用样本」才算收敛、可以开始盲等；不足时按调用方间隔轮询
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
#: 收敛后轮询识图的间隔（秒），比 DEFAULT_WAIT_INTERVAL 更细，命中更及时。
#: 因为大头已经由盲等省掉了。
TIMING_FINE_INTERVAL: float = 1.0
#: 盲等最多吃掉 timeout 减去这个值，剩下的留给细粒度轮询
TIMING_FINE_WINDOW: float = 10.0
#: 「一次截屏 + 模型判定」成本的滑动窗口长度（只在内存，不入库）
TIMING_PROBE_WINDOW: int = 10


# --------------------------------------------------------------------------- #
# 拟人化操作
# --------------------------------------------------------------------------- #
#: pyautogui 全局设置
PYAUTOGUI_PAUSE: float = 0.2
PYAUTOGUI_FAILSAFE: bool = False

#: 每次点击前后附加的随机停顿区间（秒）
HUMAN_PAUSE_RANGE: Tuple[float, float] = (0.0, 1.0)
#: 点击落点的随机抖动半径（逻辑像素）
HUMAN_JITTER: int = 3
#: 拖动时插值步数，越大轨迹越像人手
HUMAN_DRAG_STEPS: int = 12


# --------------------------------------------------------------------------- #
# similarity/ 图片对比（独立实验区，不参与主流程）
# --------------------------------------------------------------------------- #
#: 多模态模型，必须同时支持 completion + vision。
#: 纯 embedding 模型不行：Ollama 的 /api/embed 会静默丢弃 images 字段。
OLLAMA_HOST: str = os.environ.get("YYS_OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL: str = os.environ.get("YYS_OLLAMA_MODEL", "lfm3-omni:latest")
#: 单次判定超时（秒）。2.4GB 模型双图推理实测 3~6 秒，冷启动更久。
OLLAMA_TIMEOUT: float = float(os.environ.get("YYS_OLLAMA_TIMEOUT", "180"))
#: 模型常驻时间，避免每次对比都重新加载
OLLAMA_KEEP_ALIVE: str = os.environ.get("YYS_OLLAMA_KEEP_ALIVE", "10m")
OLLAMA_NUM_PREDICT: int = 800
#: 判定「同一界面」所需的最低可信度
SIMILARITY_MATCH_THRESHOLD: float = float(
    os.environ.get("YYS_SIMILARITY_THRESHOLD", "0.6"))

# --------------------------------------------------------------------------- #
# runner/ 主流程（DSL 驱动的分组标注执行）
# --------------------------------------------------------------------------- #
#: 分组目录里的 DSL 文件名，主流程发现它就自动加载
RUNNER_DSL_FILENAME: str = os.environ.get("YYS_RUNNER_DSL", "flow.py")
#: 一步（等某张图出现）的默认超时（秒）
RUNNER_STEP_TIMEOUT: float = float(os.environ.get("YYS_RUNNER_STEP_TIMEOUT", "120"))
#: 一整轮（走完全部 steps）的默认超时（秒）
RUNNER_ROUND_TIMEOUT: float = float(os.environ.get("YYS_RUNNER_ROUND_TIMEOUT", "900"))
#: 两次模型判定之间额外睡眠的秒数。
#: 一次判定本身要 1~3 秒，真实轮询周期 = 判定耗时 + 本值。
RUNNER_PROBE_INTERVAL: float = float(os.environ.get("YYS_RUNNER_PROBE_INTERVAL", "1.0"))
#: 命中之后、点击之前的固定停顿（秒），给界面动画留时间
RUNNER_SETTLE_PAUSE: float = float(os.environ.get("YYS_RUNNER_SETTLE_PAUSE", "0.6"))
