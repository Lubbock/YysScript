# AGENTS.md — YysScript 目录职责与开发约定

本文件是**目录契约**：每个顶层文件夹负责什么、可以依赖谁、改动应该落在哪里。
修改代码前先读这份文件，改完如果发现职责边界需要调整，同步更新本文件。

---

## 1. 项目是什么

《阴阳师》PC 客户端自动化脚本。不读游戏内存、不调游戏接口，纯视觉方案：

```
截屏 -> 图像识别（模板匹配 / 颜色轮廓） -> 判断当前界面状态 -> 换算坐标 -> 拟人化点击
```

运行平台：Windows + Python 3.8+。非 Windows 只能跑单测和 `--check` 的模板校验部分。

> ⚠️ 合规提醒：自动化脚本违反《阴阳师》用户协议，存在封号风险。本项目仅作图像识别与
> 自动化的技术学习用途。

---

## 2. 顶层目录职责表

| 目录 | 职责（一句话） | 允许依赖 | 禁止 |
|---|---|---|---|
| `config/` | 全局参数 + **唯一**的坐标表 | 无（纯配置） | 依赖任何业务层 |
| `core/` | 日志、异常、计时/耗时预测 | `config`、`storage` | 依赖 vision/states/actions/flows |
| `vision/` | **图像识别**：截屏、模板匹配、颜色轮廓检测 | `config`、`core` | 点击、坐标换算、业务判断 |
| `storage/` | **存储**：sqlite 持久化（动作耗时样本等） | `config`、`core` | 依赖 vision/states/actions/flows |
| `states/` | **状态机**：一个状态一个文件，全部定义成常量 | `config`、`core`、`vision.types` | 点击操作、业务流程 |
| `actions/` | **操作**：找游戏窗口、坐标换算、拟人化点击 | `config`、`core`、`vision` | 业务流程判断 |
| `flows/` | **功能编排**：一个大功能一个子文件夹 | 以上全部 | 被下层反向依赖 |
| `assets/` | 模板图片资源（`assets/templates/*.png`） | — | 放代码 |
| `tests/` | 单元测试（不依赖游戏、不依赖 cv2/pyautogui） | 被测模块 | 真实截屏/点击 |
| `tools/` | 维护工具（模板图片管理 Web 界面）+ 周边归档（语音、远控、Flask demo、安卓实验等） | 可 import 主包 | 被主流程 import |
| `var/` | 运行时产物（日志、sqlite 数据库），不进版本库 | — | 手写文件 |
| `main.py` | 命令行入口 | `flows`、`actions`、`core`、`config` | 写业务逻辑 |

### 依赖方向（只能从上往下）

```
main.py
  └── flows/          功能编排：御魂、探索、结界突破…
        ├── states/   我在哪个界面？（状态常量 + 状态机）
        ├── actions/  点哪里、怎么点（窗口 + 坐标换算 + 拟人化）
        │     └── vision/   屏幕上有什么、在哪里
        ├── storage/  历史耗时样本
        ├── core/     日志 / 异常 / 计时
        └── config/   参数与坐标表
```

**反向依赖一律禁止**（例如 `vision` 里 import `flows`）。`states` 只在类型标注里
用 `TYPE_CHECKING` 引用 `vision.types`，运行时不引入 cv2/pyautogui，因此可独立单测。

---

## 3. 目录详解

### `config/` — 配置与坐标（改数值来这里）
- `settings.py`：路径、基准分辨率、匹配阈值、超时、拟人化参数。
  路径支持环境变量覆盖：`YYS_TEMPLATE_DIR` / `YYS_LOG_DIR` / `YYS_DB_PATH` / `YYS_VAR_DIR`。
  （旧代码把 `E:/github/YysScript/...` 写死在源码里，已彻底移除。）
- `coordinates.py`：**全项目唯一允许出现界面坐标的文件**。
  - `Point(x, y)` 是「基准客户区坐标」，基准 = `settings.BASE_CLIENT_SIZE` = 1024×768。
  - 按功能分段注释（探索 / 御魂 / 觉醒 / 妖气封印 / 结界突破 / 御心道场 / 狗粮）。
  - 带步长的坐标用函数表达：`bottom_menu(i)`、`awake_dungeon(i)`、`breakthrough_cell(i)`。

### `core/` — 通用能力
- `logger.py`：`get_logger(name)`，全局只配置一次 handler（修掉旧代码重复 addHandler 导致的日志重复）。日志落 `var/logs/yys_script.log`，按 5MB 轮转。
- `errors.py`：`YysError` 及子类 `ConfigError` / `WindowNotFoundError` / `StateTimeoutError` / `StaminaExhaustedError` / `FlowAbortedError`。**不要再用 `exit(300)`**，抛异常，由 `main.py` 转退出码。
- `stopwatch.py`：`Stopwatch` 计时、`WaitPredictor` 用历史均值预测等待时长。

### `vision/` — 图像识别（职责 1）
- `types.py`：`Frame`（截图 + 原点 + 尺寸）、`Box`、`Match`。**这里所有坐标都是屏幕绝对坐标。**
- `capture.py`：`ScreenCapture`，可注入 `region_provider` 只截游戏窗口区域（更快、且不会被桌面其它窗口/弹窗干扰）。
- `template_matcher.py`：`TemplateMatcher`，对应旧 `utils/MapCv.py`。模板带缓存、结果做非极大值抑制、模板缺失抛 `ConfigError`。
- `color_detector.py`：`MonsterDetector`，对应旧 `utils/Monster.py`。HSV 阈值 + 腐蚀膨胀 + `findContours` 定位会移动的怪物，比模板匹配快；兼容 OpenCV 3/4 的 `findContours` 返回值差异。
  画面分区过滤（`MIN_Y_RATIO` / `EXP_MAX_Y_RATIO`）按比例表达，避开顶部 HUD 与底部操作栏；`debug=True`（即 `--debug`）时把识别框标注图存到 `var/debug/`，便于调 HSV 阈值。

### `storage/` — 存储（职责 2 的持久化部分）
- `schema.sql` + `database.py`：自动建表，表名沿用旧的 `GAMETIME_RECORD`，老 `gray_scan.db` 可直接复用。
- `duration_store.py`：`DurationStore`（record / average / samples / trim / clear），对应旧 `utils/grayscaness.py`。已全部参数化查询；修掉旧 `clear_kw(500)` 少传参数的必然 TypeError 和「超限直接 return 丢数据」的逻辑。

### `states/` — 状态机（职责 2 的主体）
- `base.py`：`State`（frozen dataclass）、`StateKind`、全局 `REGISTRY`、`get_state()` / `all_states()`。
- `machine.py`：`StateMachine` —— `is_active` / `locate` / `locate_all` / `detect`（取最高分） / `detect_first`（按优先级） / `wait_for` / `wait_gone` / `wait_any` / `expect`（超时抛异常）。
- **其余每个文件 = 一个状态**，文件名 = 状态 key 的小写形式，文件内只有一个大写常量：

```python
"""游戏首页（主城）。"""
from states.base import State

HOME = State(
    key="HOME",
    label="游戏首页",
    templates=("首页.png",),
    description="登录后的主城界面，大部分流程的起点与回归点",
)
```

- 两类状态：
  - `StateKind.SCREEN`（默认）：**我在哪个界面**，如 `HOME`、`EXPLORE_MAP`、`BATTLE_PREPARE`。
  - `StateKind.MARKER`：**某个按钮/图标在哪**，如 `MARKER_BOSS_REWARD`、`MARKER_FULL_LEVEL`、`MONSTER_XIAOSONGMARU`。
- `states/__init__.py` 会自动扫描并导入所有状态文件完成注册，提供 `REGISTRY` / `SCREEN_STATES` / `MARKER_STATES`。
  业务代码请直接 `from states.home import HOME`，可读性更好。

### `actions/` — 操作（职责 3，解决"坐标写死"的关键层）
- `window.py`：`GameWindow` + `Win32WindowFinder`（按标题/类名找窗口，取**客户区**矩形，声明 DPI 感知）+ `FullScreenFinder`（找不到窗口或非 Windows 时把整屏当客户区）。找不到窗口时按 `settings.FALLBACK_TO_FULLSCREEN` 决定回退还是抛 `WindowNotFoundError`。
- `viewport.py`：`Viewport`，纯计算。`to_screen(Point)` 逻辑坐标 → 屏幕坐标（按窗口位置平移 + 按窗口尺寸缩放 + 校准偏移 + 越界裁剪），`to_logical(screen)` 反向。**这一层让换分辨率、窗口不在原点都不再致命。**
- `mouse.py`：`HumanMouse`，只认屏幕坐标。落点随机抖动、动作间随机停顿（对应旧 `personal_pause`）、拖动分步 + 缓动。
- `controller.py`：`GameController` 门面，flows 唯一入口。`resolve()` 统一处理三种点击目标：
  - `Point` → 逻辑坐标，按窗口换算；
  - `Match` / `Box` → vision 的识别结果，取中心点（已是屏幕坐标）；
  - `(x, y)` → 屏幕绝对坐标，原样使用。

  同时把截屏区域绑定到游戏窗口，`matcher` / `detector` 已装配好。

### `flows/` — 功能编排（职责 4，一个功能一个子文件夹）
| 子目录 | 命令行名 | 对应旧文件 |
|---|---|---|
| `explore/` | `explore` | `scripts/adventure.py` |
| `soul/` | `soul` | `scripts/soul.py` |
| `awake/` | `awake` | `scripts/awake.py` |
| `breakthrough/` | `breakthrough` | `scripts/fight.py` |
| `seal/` | `seal` | `scripts/dogger.py` |
| `heart_dojo/` | `heart` | `scripts/heart.py` |
| `events/` | `event-aband3t` / `event-aj8fer` | `scripts/abnd3t.py`、`scripts/aj8fer.py` |

- `base.py`：`Flow` 基类（`click` / `drag` / `scroll` / `is_active` / `locate` / `wait` / `expect` / `wait_gone` / `wait_any` / `click_state` / `prepare` / `run` / `execute`）与 `RetryGuard`。
- `registry.py`：命令行名 → Flow 类的惰性映射，`main.py` 靠它加载。
- `explore/` 额外拆了 `map_navigator.py`（翻页、选章节）与 `dog_food.py`（满级式神替换）。
- 新增功能：建子目录 → 写 `XxxFlow(Flow)` 实现 `run()` → 在 `registry.py` 的 `FLOW_SPECS` 注册 → 需要新界面就在 `states/` 加状态文件、需要新坐标就在 `config/coordinates.py` 加常量。

### `tools/` — 维护工具与周边归档（都不参与主流程）

分两类：

**A. 项目维护工具（有测试覆盖，可放心用）**
- `asset_manager/`：**模板图片管理 Web 界面**，解决「游戏更新 UI 后要重新截图换模板」这个最常见的维护动作。
  ```bash
  python tools/asset_manager/app.py          # 默认 http://127.0.0.1:8899（端口占用自动顺延）
  ```
  功能：状态卡片网格（缩略图 + 阈值 + 被哪些流程引用）、缺失/未引用高亮、拖拽上传替换、
  **截屏 → 框选 → 存成新模板**、替换前自动备份 + 一键回滚、probe 单步识别测试（看分数与匹配框）。
  - 状态清单直接读 `states.REGISTRY`，新增状态文件后无需改这个工具；
  - 流程清单以 `flows/registry.py` 为准，所以不引用状态的流程（如 `soul`）也会列出；
  - 截屏 / probe 依赖 pyautogui + cv2，缺失时前端自动禁用对应按钮并显示原因；
  - **只绑 127.0.0.1**：该服务能覆盖 `assets/templates/`，远程访问请用 SSH 隧道；
  - 备份落在 `var/backups/templates/<时间戳>/`（不入版本库，长期历史靠 git）；
  - 契约测试见 `tests/test_asset_manager_api.py`。

**B. 归档的旧工具（原样搬迁，质量不做保证）**
`desktop/`（鼠标坐标打印、Win10 语音控制）、`remote/`（TeamViewer 保活 + 邮件指令）、
`file_server/`、`web/`（Flask demo）、`pyqt/`（GUI 骨架）、`android/`（uiautomator2 实验）、
`ml/`（TF1 CNN demo）、`audio/`、`tomato.sh`。
只修了指向已删除 `utils/` 的 import。**别从主流程 import 它们**（依赖方向：tools → 主包，单向）。

---

## 4. 两套坐标语义（最容易搞错的地方）

| 类型 | 定义 | 出现在 | 谁负责转换 |
|---|---|---|---|
| **逻辑坐标** `Point(x, y)` | 基准客户区 1024×768 下的坐标 | `config/coordinates.py`、flows | `Viewport.to_screen()` |
| **屏幕绝对坐标** | 显示器真实像素坐标 | `vision` 的 `Frame/Box/Match`、`actions/mouse.py` | — |

规则：
1. flows 里写坐标只用 `config/coordinates.py` 的常量，**不要出现裸数字**。
2. 需要把识别结果和逻辑阈值比较时（例如狗粮分区判断），先 `controller.to_logical(match.center)`。
3. `controller.click()` 能接受两种坐标，但语义不同：`Point` 会被换算，`tuple` 被当屏幕坐标直接用。

---

## 5. 常见任务落点

| 想做什么 | 改哪里 |
|---|---|
| 某个按钮点不准 | `config/coordinates.py` 对应常量 |
| 换分辨率后整体偏移 | `config/settings.py` 的 `BASE_CLIENT_SIZE` / `CALIBRATION_OFFSET` |
| 识别不到某个界面（阈值） | `states/<该状态>.py` 的 `threshold`，或 `settings.DEFAULT_THRESHOLD` |
| 游戏更新导致模板图失效 | 跑 `python tools/asset_manager/app.py`，截屏 → 框选 → 存成新模板（自动备份可回滚） |
| 不确定某张模板还认不认得出来 | 模板管理界面的 probe：显示匹配分数、命中框和标注图 |
| 新增一个界面判断 | `states/` 新建一个文件，定义一个 `State` 常量 |
| 新增一个玩法流程 | `flows/<功能>/` 新建子目录 + `registry.py` 注册 |
| 点击太快 / 太规律 | `settings.py` 的 `HUMAN_JITTER` / `HUMAN_PAUSE_RANGE` / `HUMAN_DRAG_STEPS` |
| 日志、数据库位置 | 环境变量 `YYS_LOG_DIR` / `YYS_DB_PATH`，或 `settings.py` |
| 等待时间太长/太短 | 各 Flow 的 `*_TIMEOUT` / `BATTLE_DURATION` 类常量 |

---

## 6. 运行与自检

```bash
pip install -r requirements.txt

python main.py --list            # 列出全部功能
python main.py --states          # 列出全部状态常量、模板、阈值
python main.py --check           # 自检：模板是否齐全 + 能否定位游戏窗口 + 缩放比例
python main.py explore --times 10 --exp-only
python main.py soul --times 30
python main.py awake --dungeon 4 --times 20
python main.py breakthrough --times 3      # 不传 --times 则无限循环
python main.py seal --times 50
python main.py heart --times 10
python main.py event-aband3t --times 20
python main.py event-aj8fer --times 100

# 调试开关
python main.py soul --fullscreen       # 不找窗口，整屏当客户区
python main.py soul --align-window     # 启动前把窗口挪到屏幕左上角
python main.py soul --no-humanize      # 关闭随机抖动/停顿
python main.py soul --debug            # DEBUG 日志 + 识别框标注图存到 var/debug/
```

退出码：`0` 正常 / `1` 流程异常 / `2` 参数缺失 / `130` 用户中断 / `300` 体力耗尽。

---

## 7. 测试

```bash
python -m pytest tests -q
```

测试**不需要** cv2、pyautogui、pywin32，也不截屏不点击：
- `test_viewport.py`：坐标换算、缩放、偏移、越界裁剪、九宫格索引（回归旧代码算错行的 bug）。
- `test_coordinates.py`：迁移后的坐标值与旧脚本逐项对齐、全部坐标落在基准分辨率内。
- `test_states_registry.py`：一状态一文件、常量名=key=文件名、注册表无重复、**模板图片真实存在**、模板无遗漏未引用。
- `test_state_machine.py`：用假 matcher 驱动状态机的等待/消失/多候选/超时/回调。
- `test_duration_store.py`：sqlite 读写、均值、裁剪、SQL 注入防护。
- `test_asset_manager_api.py`：模板管理工具的 API 契约（前端 app.js 读的每个字段）、替换/备份/回滚、裁剪、路径穿越拦截、无 pyautogui/cv2 时的降级。

新增状态或流程时，至少保证 `test_states_registry.py` 通过（它会检查模板文件是否存在）。

---

## 8. 已知限制

1. **坐标未重新标定**：`config/coordinates.py` 的数值从旧脚本原样迁移，基准按 1024×768 客户区假设。
   若你的客户端尺寸不同，`Viewport` 会等比缩放，但个别按钮仍可能需要微调；先用 `--check` 看缩放比例。
2. **模板图片与客户端版本强绑定**：游戏更新 UI 后需要重新截图。
3. **等待时间仍有经验值**：战斗时长按固定秒数等待（各 Flow 的 `BATTLE_*` 常量），只有 `event-aj8fer` 用了历史耗时预测。
4. **无端到端测试**：涉及真实截图与点击的路径只能人工验证。
5. `tools/` 下的归档工具未做质量修复（部分依赖 TensorFlow 1.x、PyAudio、pywin32）。
