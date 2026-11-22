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
| `core/` | 日志、异常、计时/耗时预测、**事件总线**、**自适应等待** | `config`、`storage` | 依赖 vision/states/actions/flows |
| `vision/` | **图像识别**：截屏、模板匹配、颜色轮廓检测 | `config`、`core` | 点击、坐标换算、业务判断 |
| `storage/` | **存储**：sqlite 持久化（动作耗时样本等） | `config`、`core` | 依赖 vision/states/actions/flows |
| `states/` | **状态机**：一个状态一个文件，全部定义成常量 | `config`、`core`、`vision.types` | 点击操作、业务流程 |
| `actions/` | **操作**：找游戏窗口、坐标换算、拟人化点击 | `config`、`core`、`vision` | 业务流程判断 |
| `flows/` | **功能编排**：一个大功能一个子文件夹；含事件驱动的主流程引擎与订阅方 | 以上全部 | 被下层反向依赖 |
| `assets/` | 模板图片资源（`assets/templates/*.png`） | — | 放代码 |
| `tests/` | 单元测试（不依赖游戏、不依赖 cv2/pyautogui） | 被测模块 | 真实截屏/点击 |
| `tools/` | 维护工具（模板图片管理 Web 界面）+ 周边归档（语音、远控、Flask demo、安卓实验等） | 可 import 主包 | 被主流程 import |
| `similarity/` | **另一条识别路线（实验中）**：基于图像相似度；「分组截图 + Web 标注」采集 + 「双图对比」页，对比靠本地 Ollama 多模态模型判定（不用 OpenCV）；数据集在同目录 `dataset/`，按 `groups/<key>/` 目录隔离 | `config`、`core`、`actions`、`vision`（只读复用截屏与窗口定位） | 被 flows/states import；改动模板匹配管线的行为 |
| `var/` | 运行时产物（日志、sqlite 数据库），不进版本库 | — | 手写文件 |
| `.worktrees/` | git worktree 隔离开发区（不入版本库）：改大功能时不影响正在运行的主工作区 | — | 在主工作区里直接改它 |
| `main.py` | 命令行入口 | `flows`、`actions`、`core`、`config` | 写业务逻辑 |

### 依赖方向（只能从上往下）

```
main.py
  └── flows/          功能编排：御魂、探索、结界突破…
        ├── states/   我在哪个界面？（状态常量 + 状态机）
        ├── actions/  点哪里、怎么点（窗口 + 坐标换算 + 拟人化）
        │     └── vision/   屏幕上有什么、在哪里
        ├── storage/  历史耗时样本
        ├── core/     日志 / 异常 / 计时 / 事件总线
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
- `errors.py`：`YysError` 及子类 `ConfigError` / `WindowNotFoundError` / `StateTimeoutError` / `StaminaExhaustedError` / `FlowAbortedError` / `WindowActivationError`。**不要再用 `exit(300)`**，抛异常，由 `main.py` 转退出码；也**不要抛裸 `RuntimeError`**，那会绕过 `main.py` 的异常处理变成 traceback。
- `stopwatch.py`：`Stopwatch` 计时、`WaitPredictor` 用历史均值预测等待时长。
- `bus.py`：`EventBus` —— 进程内**同步**发布/订阅。topic 点分层级，订阅支持 `*`（一段）/ `**`（多段）通配符；
  priority、once、异常隔离（默认吞掉订阅方异常只记日志，`strict=True` 时抛出）、递归深度保护、history 环形缓冲。
  纯标准库实现，不认识任何领域事件，领域 topic 定义在 `flows/signals.py`。
- `timing.py`：`CycleTimer`（实现 `WaitScheduler` 协议）+ `FixedScheduler` + `Estimate` / `WaitPlan` /
  `TimingSample` / `Cycle`。记录每轮 / 每阶段耗时（写 `storage.DurationStore`），并给出「先盲等多久、
  之后隔多久识图」的计划；内置异常值剔除与「连续超限回退重新收敛」。算法细节见本节末尾。

### `vision/` — 图像识别（职责 1）
- `types.py`：`Frame`（截图 + 原点 + 尺寸）、`Box`、`Match`。**这里所有坐标都是屏幕绝对坐标。**
- `capture.py`：`ScreenCapture`，可注入 `region_provider` 只截游戏窗口区域（更快、且不会被桌面其它窗口/弹窗干扰）。
- `template_matcher.py`：`TemplateMatcher`，对应旧 `utils/MapCv.py`。模板带缓存、结果做非极大值抑制、模板缺失抛 `ConfigError`；
  多尺度匹配前先用 `scales.usable_scales()` 筛掉「缩放后小于像素下限」的尺度，第一次筛掉时 warn 一次（提示模板不是按当前窗口比例截的）。
- `scales.py`：**尺度策略纯计算层**（不依赖 cv2，可独立单测）。约束是缩放后的**绝对像素数**而不是比例：
  模板缩到几十像素就没有判别力，会在任意画面上撞出 0.9+ 假命中，脚本照着点就是在乱点（见已知限制 9）。
- `color_detector.py`：`MonsterDetector`，对应旧 `utils/Monster.py`。HSV 阈值 + 腐蚀膨胀 + `findContours` 定位会移动的怪物，比模板匹配快；兼容 OpenCV 3/4 的 `findContours` 返回值差异。
  画面分区过滤（`MIN_Y_RATIO` / `EXP_MAX_Y_RATIO`）按比例表达，避开顶部 HUD 与底部操作栏；`debug=True`（即 `--debug`）时把识别框标注图存到 `var/debug/`，便于调 HSV 阈值。

### `storage/` — 存储（职责 2 的持久化部分）
- `schema.sql` + `database.py`：自动建表，表名沿用旧的 `GAMETIME_RECORD`，老 `gray_scan.db` 可直接复用。
- `duration_store.py`：`DurationStore`（record / average / samples / trim / clear），对应旧 `utils/grayscaness.py`。已全部参数化查询；修掉旧 `clear_kw(500)` 少传参数的必然 TypeError 和「超限直接 return 丢数据」的逻辑。

### `states/` — 状态机（职责 2 的主体）
- `base.py`：`State`（frozen dataclass）、`StateKind`、全局 `REGISTRY`、`get_state()` / `all_states()`。
- `machine.py`：`StateMachine` —— `is_active` / `locate` / `locate_all` / `detect`（取最高分） / `detect_first`（按优先级） / `wait_for` / `wait_gone` / `wait_any` / `expect`（超时抛异常）。
  `wait_*` 都接受可选的 `scheduler` + `timing_key`：给了就先按历史耗时盲等、再细粒度轮询（内部 `_Pacer`）；
  **不给时行为与改造前逐字一致**，所以命令式流程可以逐个 opt-in。
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
- `window.py`：`GameWindow` + `Win32WindowFinder`（按标题/类名找窗口，取**客户区**矩形，声明 DPI 感知）+ `MacWindowFinder`（macOS 按进程名定位窗口，默认「iPhone Mirroring」iOS 镜像窗口，窗口内点击透传到手机）+ `FullScreenFinder`（找不到窗口或其它平台时把整屏当客户区）。找不到窗口时按 `settings.FALLBACK_TO_FULLSCREEN` 决定回退还是抛 `WindowNotFoundError`。
- `viewport.py`：`Viewport`，纯计算。`to_screen(Point)` 逻辑坐标 → 屏幕坐标（按窗口位置平移 + 按窗口尺寸缩放 + 校准偏移 + 越界裁剪），`to_logical(screen)` 反向。**这一层让换分辨率、窗口不在原点都不再致命。**
- `mouse.py`：`HumanMouse`，只认屏幕坐标。落点随机抖动、动作间随机停顿（对应旧 `personal_pause`）、拖动分步 + 缓动。macOS 上 controller 注入目标进程 PID 后启用「礼貌点击」：点击瞬间激活目标窗口 -> 把光标 warp 到目标点**并补发一个 mouseMoved** -> 在同一坐标发 down/up -> 还原光标（同样补发 mouseMoved）与焦点，轮询识别期间完全不碰鼠标。坑：`CGWarpMouseCursorPosition` 只改窗口服务的指针坐标、不产生移动事件，App 侧缓存的光标位置（hover / Mac Catalyst 的指针→触摸桥接）不更新，只按坐标发事件会被静默丢掉，表现为「跑一段时间后点不动，手动晃一下鼠标才恢复」，所以 warp 必须配套补发 `kCGEventMouseMoved`；滚动事件本身不带坐标，也要先落点。
  **激活失败不再终止进程**：`_activate_frontmost()` 按 `ACTIVATE_MAX_ATTEMPTS` 自动重试（用户切窗口 / 刚唤醒 / osascript 超时都是瞬时的）；仍失败就跳过本次操作，`click()` 返回 `None`（`drag` / `scroll` 静默返回），由上层重置状态、下一拍重试；只有连续失败到 `ACTIVATE_MAX_CONSECUTIVE_FAILURES` 才抛 `WindowActivationError`（YysError -> 退出码 1 + 一句话，不是 traceback）。旧行为是抛裸 `RuntimeError`，未被 `main.py` 捕获，整晚挂机白跑。
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
| `shard/` | `shard` | —（式神碎片挑战循环，模板匹配驱动，支持 iOS 镜像；两种入口同时监听，无需选模式） |
| `events/` | `event-aband3t` / `event-aj8fer` | `scripts/abnd3t.py`、`scripts/aj8fer.py` |

- `base.py`：`Flow` 基类（`click` / `drag` / `scroll` / `is_active` / `locate` / `wait` / `expect` / `wait_gone` / `wait_any` / `click_state` / `on` / `publish` / `cycle` / `wait_plan` / `create_engine` / `prepare` / `run` / `execute`）与 `RetryGuard`。
  每个 Flow 自带一条私有 `bus`（`core/bus.py`）和一个 `timer`（`core/timing.py`）；
  `wait*` 系列多了可选的 `adaptive_key`，给了就按历史耗时盲等。
- `registry.py`：命令行名 → Flow 类的惰性映射，`main.py` 靠它加载。
- `explore/` 额外拆了 `map_navigator.py`（翻页、选章节）与 `dog_food.py`（满级式神替换）。
- 新增功能：建子目录 → 写 `XxxFlow(Flow)` 实现 `run()` → 在 `registry.py` 的 `FLOW_SPECS` 注册 → 需要新界面就在 `states/` 加状态文件、需要新坐标就在 `config/coordinates.py` 加常量。
- `engine.py`：**主流程引擎**（事件驱动的推进器）：`watch` / `step` / `observe` / `peek` / `wait_for` /
  `begin_wait` / `click` / `finish_round` / `stop` / `fail` / `run_rounds` / `summary`，本身不含玩法知识。
- `signals.py`：topic 常量 + 事件对象（`FlowEvent` / `RoundEvent` / `PollEvent` / `StateEvent` /
  `TimeoutEvent` / `ActionEvent`）+ `topic_for()`。
- `battle_cycle.py`：`BattleCycle` —— 「挑战 → 战斗 → 结算 → 回挑战」的可复用订阅方，soul / shard 共用。
- `stage_cycle.py`：`StageCycle` —— 「点起始界面 → 自适应等待 → 点结算界面」的两阶段订阅方，
  event-aband3t / event-aj8fer 共用。
- `rules.py`：`ProbeWhileWaiting` —— 通用的「边等边点」订阅方，替代旧的 `on_wait=lambda: click(...)`。
- **9 个流程全部已迁移到事件驱动**：`run()` 只负责组装引擎 + 挂订阅方 + `run_rounds()`。
  流程自己的规则写成同文件里的订阅方类（`AwakeRound` / `SealRound` / `HeartRound` /
  `BreakthroughSweep` / `ExploreSweep` / `ShardEntryNav`），只订阅 topic、只调 engine 的公开方法，不碰 machine / controller。

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

### `similarity/` — 基于图像相似度的另一条路线（隔离实验区）

与模板匹配管线（`vision/template_matcher.py` + `states/` + `flows/`）**完全隔离**：主流程不
import 它，它只**只读复用** `actions/window.py`（定位模拟器 / 镜像窗口）与 `vision/capture.py`
（截屏）。**当前实现数据采集（分组标注）+ 基于本地大模型的双图对比，尚未接入主流程。**

```bash
python similarity/app.py            # http://127.0.0.1:8901，只绑本机
```

两个页面，顶部导航互跳：

- **标注采集（`/`）**：**按分组组织**（如「御魂探索」「麒麟」各一个分组，进去各自采集，
  互不干扰）。分组是**真实目录隔离**不是筛选标签：`dataset/groups.json` 存清单
  （`key` 是自动生成的 ASCII 短 id，`name` 才是中文名，改名不动目录、URL 里不出现中文，
  名字全局唯一），`dataset/groups/<key>/shots/<id>.png` + 同名 `<id>.json` 存截图与标注，
  `thumbs/` 存缩略图缓存。支持新建 / 改名 / 改说明 / 删除（连同组内截图与标注）/
  把单张截图**跨组移动**（标注与备注一起搬）。首次启动自动建 `default`「默认分组」，
  并把改造前的旧 `dataset/shots/`、`dataset/thumbs/` **迁移**进去（只移动不删除，幂等）。
  操作：**捕获截图**（目标窗口 / 整屏）→ 图上**框选或点选标注**（坐标按图片原始像素存，
  与浏览器缩放无关）→ **保存**。PNG 与缩略图不入版本库（见 `similarity/dataset/.gitignore`
  的 `*.png` / `*.jpg`），标注 JSON 与 `groups.json` 入库。
- **图片对比（`/compare`）**：连点两次捕获填入 A / B 两个槽位 → 点「对比」调
  `POST /api/compare` → 显示可信度、是否同一界面、两边识别成什么、差异列表与依据。
  截图落 `dataset/compare/`（只留最近 40 张），**不进标注数据集**。
  **对比算法 = 本地 Ollama 多模态模型判定**（`similarity/llm_judge.py`），默认
  `lfm3-omni:latest`，两张图 base64 一起发 `POST /api/chat`（`format: json`、
  `temperature: 0`），单次实测 1.3~2.8 秒。**不做 OpenCV 像素比对。**
  `score` = 模型的 `similarity`；`matched = same_screen AND score >= 阈值(0.6)`；
  两者矛盾时 `inconsistent=true`，页面弹黄条。换模型 / 阈值走 `--model` /
  `--threshold` 或 `YYS_OLLAMA_MODEL` / `YYS_SIMILARITY_THRESHOLD`。
  ⚠️ 模型必须同时有 `completion` + `vision`：**纯 embedding 模型不行** —— 实测
  `embeddinggemma-2:740m` 虽然 capabilities 带 vision，但 Ollama `/api/embed` 会
  **静默丢弃** `images`（三张不同图返回同一向量，cosine=1.000000，0.02s 无视觉编码），
  且它不支持 generate / chat。`health()` 启动自检会拦住并给出原因。
  ⚠️ 模型 `similarity` 只分得开两档（同屏 0.99 / 不同屏 0.05），中间地带也给 0.99，
  所以它能答「是不是同一界面」，**不能当连续相似度度量**。真机 6 对标定 6/6 正确。
  自检 CLI：`python -m similarity.llm_judge [a.png b.png]`。

细节见 `similarity/README.md`。

### 事件驱动流程与自适应等待（两条横切能力）

**为什么要它**：以前 `run()` 里写死「等 A → 点 A → 等 B → 点 B」，加一条规则就得改流程本体；
而且每一步都按固定间隔反复截屏 —— 一场 45 秒的战斗要截十几次图，绝大多数注定什么都识别不到。

**六个新模块**：

- `core/bus.py` —— 通用同步发布/订阅总线（只用标准库，不认识领域事件）；
- `flows/signals.py` —— 领域词汇表：topic 常量 + frozen 事件对象 + `topic_for()`；
- `flows/engine.py` —— `FlowEngine` 主循环，**不含任何玩法知识**：`watch()` 登记候选状态 →
  `step()` 识图 → 广播事件 → 订阅方决定动作 → `run_rounds()` 推进轮次并计时；
- `flows/battle_cycle.py` —— 「挑战 → 战斗 → 结算 → 回挑战」的可复用订阅方，soul / shard 共用；
- `flows/stage_cycle.py` —— 「点起始界面 → 自适应等待 → 点结算界面」的两阶段订阅方，
  event-aband3t / event-aj8fer 共用（旧的写死 `sleep(120)` / 均值预测都由它接管）；
- `flows/rules.py` —— `ProbeWhileWaiting`，把旧代码里到处出现的
  `wait(X, on_wait=lambda: click(Y))`（边等边点）抽成独立订阅方：
  `unless_state=X` 对应旧的 `wait`，`only_state=X` 对应旧的 `wait_gone`。

**topic 一览**（详见 `flows/signals.py`）：

| topic | 事件对象 | 谁发 | 何时 |
|---|---|---|---|
| `flow.started` / `flow.finished` | `FlowEvent` | 引擎 | 整个流程首尾（`aborted` 标记是否被中止） |
| `round.started` / `round.finished` | `RoundEvent` | 引擎 | 每轮首尾（带 duration / 本轮见过的状态 / timed_out） |
| `round.done` | `RoundEvent` | **订阅方** | 「这一轮我处理完了」，引擎据此进入下一轮 |
| `poll.completed` | `PollEvent` | 引擎 | 每次截屏识图之后（带本次识图耗时） |
| `state.detected` | `StateEvent` | 引擎 | 每次命中（含同一状态重复命中） |
| `state.entered.<KEY>` / `state.exited.<KEY>` | `StateEvent` | 引擎 | 状态**跳变**时；连续命中同一状态不重复触发 |
| `state.unknown` | `PollEvent` | 引擎 | 连续 `UNKNOWN_POLL_LIMIT` 次什么都没识别到 |
| `state.timeout` | `TimeoutEvent` | 引擎 | 整轮超时，或 `engine.wait_for(publish=True)` 超时 |
| `action.performed` | `ActionEvent` | 引擎（代订阅方） | `engine.click()` 之后 |
| `timing.recorded` | `TimingSample` | `CycleTimer` | 一条耗时样本入库时 |

**订阅方控制引擎的四个入口**：`begin_wait(key, interval)`（声明在等什么，决定盲等节奏）、
`finish_round()`（本轮结束）、`stop()`（优雅停止）、`fail(exc)`（中止并抛异常）。
注意异常**不能**在订阅方里直接抛 —— 会被总线的异常隔离吞掉，所以交给 `fail()`，
由引擎在本次投递结束后抛出，`main.py` 的退出码语义因此不变。

**计时 key 约定** `"<flow>:<phase>"`：`soul:round`（整轮，引擎自动记）、
`soul:battle`（点挑战到结算处理完）、`soul:challenge`（回到挑战界面的耗时）、
`soul:probe`（一次截屏+匹配的成本，只在内存滑动平均，不入库）。
样本表沿用 `GAMETIME_RECORD`，**老 `gray_scan.db` 直接可用**，没有 schema 变更。

**自适应等待怎么算**（`CycleTimer.plan()` → `WaitPlan(blind_wait, interval)`）：

1. 可用样本 < `TIMING_WARMUP_SAMPLES`(5) → `blind_wait=0` + 调用方给的 interval，**等于改造前的行为**；
2. 收敛后 → `blind_wait = p10 × TIMING_SAFETY(0.85) − 一次识图成本`，之后按 `TIMING_FINE_INTERVAL`(1s) 细轮询；
3. 硬上限 `min(TIMING_MAX_BLIND_WAIT(90s), timeout − TIMING_FINE_WINDOW(10s))`，估计再离谱也不会长时间瞎等；
4. **防不收敛（两个方向都要防）**：异常阈值 = `max(p50 × TIMING_OUTLIER_FACTOR(2.5), p50 + TIMING_OUTLIER_FLOOR(30s))`，
   超过的样本不计入 min/p10（仍入库审计）；连续 `TIMING_OVERRUN_RESET`(2) 次异常就丢掉内存窗口、
   回到 warm-up 用探测频率重新攒样本，并用更保守的 `TIMING_RESET_SAFETY`(0.5) 重新收敛。
   - *样本过大*：「等太久 → 样本更大 → 盲等更久 → 最小值永远下不来」这个死循环跑不起来；
   - *样本过小*：**可用样本不足 `TIMING_WARMUP_SAMPLES` 时一律不判异常**（没有基线就谈不上异常），
     且阈值带绝对下限 —— 否则一个偶然很小的样本（实测踩到：`soul:challenge` 点完结算瞬间返回，
     只有 0.045 秒）会把阈值压到 0.11 秒，之后每个真实样本都被误判成异常剔除，
     窗口里只剩那个极小值，`usable` 永远攒不够 → **永久不收敛**，还会每轮刷误导性 WARNING。

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
| 不在那个界面上却「命中」了、脚本乱点 | 先看命中框尺寸对不对：`locate()` 返回的 `Box` 若和模板尺寸差很多（例如 41×51 只匹配到 20×26），就是被缩小匹配骗了 —— 尺度策略见 `vision/scales.py`，模板该从实时窗口重截 |
| 新增一个界面判断 | `states/` 新建一个文件，定义一个 `State` 常量 |
| 新增一个玩法流程 | `flows/<功能>/` 新建子目录 + `registry.py` 注册 |
| 点击太快 / 太规律 | `settings.py` 的 `HUMAN_JITTER` / `HUMAN_PAUSE_RANGE` / `HUMAN_DRAG_STEPS` |
| 日志、数据库位置 | 环境变量 `YYS_LOG_DIR` / `YYS_DB_PATH`，或 `settings.py` |
| 等待时间太长/太短 | 各 Flow 的 `*_TIMEOUT` / `BATTLE_DURATION` 类常量 |
| 窗口激活失败（点击没反应但没报错） | `settings.py` 的 `ACTIVATE_*`：重试次数 / 间隔 / 连续失败上限；日志里搜「激活目标窗口失败」 |
| 想给某个流程加一条规则（遇到 X 就点 Y） | 新写一个订阅方 `engine.on("state.entered.X", handler)`，不用改 Flow 本体 |
| 截图太频繁 / 空等太久 | `core/timing.py` 的估计逻辑与 `settings.py` 的 `TIMING_*`（先跑几轮攒样本，之后自动盲等） |
| 想临时关掉自适应等待 | `--no-adaptive-wait` 或环境变量 `YYS_ADAPTIVE_WAIT=0` |
| 想看每轮花了多少时间 | 流程结束时引擎打的「总账」日志；原始样本在 `var/gray_scan.db` 的 `GAMETIME_RECORD` |

---

## 6. 运行与自检

```bash
pip install -r requirements.txt

python main.py --list            # 列出全部功能
python main.py --states          # 列出全部状态常量、模板、阈值
python main.py --check           # 自检：模板是否齐全 + 能否定位游戏窗口 + 缩放比例
python main.py explore --times 10 --exp-only
python main.py soul --times 30
python main.py shard --times 10     # 式神碎片挑战循环（macOS + iOS 镜像可用）
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
python main.py soul --no-adaptive-wait # 关闭自适应等待，始终按固定间隔轮询识图（= YYS_ADAPTIVE_WAIT=0）
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
- `test_bus.py`：事件总线的投递顺序 / priority、`*` 与 `**` 通配符、`state.entered.<KEY>` 精确订阅、退订、once、异常隔离、递归深度保护、history。
- `test_timing.py`：warm-up 退化、收敛后的盲等计算、异常值剔除、**连续超限回退并重新收敛**、盲等硬上限、discard 不入库、样本跨进程复用、窗口裁剪、识图成本滑窗。
- `test_mouse_activation.py`：窗口激活失败时**自动重试**、重试耗尽后跳过操作而不是崩进程、连续失败到上限抛 `WindowActivationError`（YysError）、成功清零连续计数、非礼貌点击路径不受影响。
- `test_engine.py`：用「假游戏」同时充当 matcher 与 controller，跑通 挑战→战斗→结算→回挑战 的完整事件序列、计时入库、收敛后识图次数下降、残留结算清理、两种超时语义、stop / fail / Ctrl-C。
- `test_state_machine_scheduler.py`：wait_* 的 `scheduler` 参数生效；**不传时 sleep 序列与改造前逐字一致**。
- `test_shard_entry_nav.py`：碎片**两种入口同时监听**（跑着跑着会变，不是开局选定）：结算后直接回挑战界面就开战、回章节界面就导航 头像->面板->列表行；**watch 顺序**（`detect_first` 顺序优先不看分数，结算模板必须排第一，否则被入口面板遮蔽 —— 真机卡死过近 4 分钟）；**战斗阶段门控**（导航动作只在等挑战按钮的阶段做）；门控挡下的命中不重置状态、改由门控打开的边沿补触发（否则每拍重复 entered 刷爆日志）；导航界面卡住会补点。假游戏里复现了全部四处误命中（含战斗 / 结算画面上的入口面板误命中）。
- `test_template_scales.py`：尺度可用性的**绝对像素**下限（41×51 @ 0.5 = 20×25 必须不可用，这是真机乱点的根因）；宽模板能扛更小尺度（卡的是短边）；全被筛掉时退回 1.0；默认尺度表不许回到 0.3 那种量级。唯一一个 `importorskip("cv2")` 的用例验证 `_scaled` 用同一个下限。
- `test_similarity_annotator.py`：`similarity/` 采集与对比工具的存储与 API 契约（假 grabber / 假 judge / 假 comparer，**不截屏、不连 Ollama、不需要 cv2**）：截图落盘 PNG + JSON、前端依赖字段齐全、列表按时间倒序、框 / 点标注保存与回读、越界与非法 kind 被拒、非法 shot id 与路径穿越拦截、删除清理三个文件、缩略图端点、页面与静态资源可访问；**分组**：首次启动自动建 `default` 组、旧 `shots/`+`thumbs/` 迁移进默认组且**幂等**、多组数据物理隔离（跨组读图 / 读标注 404）、组名必填与去重、改名 / 改说明（可只传一个字段）、删除组连目录一起删、删到最后一个组自动重建 `default`、跨组移动截图（标注与备注一起搬、同组移动 400、目标组不存在 404）、非法 group key 与路径穿越拦截；**对比页**：两次捕获落 `compare/` 且不污染标注数据集、模型判定结果透传前端字段、否定判定、缺槽位 400、图不存在 404、非法 id 400、注入 comparer 时按传入路径调用、抛异常 / 返回非 dict 转 500、模型不可用转 503 且 `/api/info` 标记 `model.ok=false`；**模型客户端**：JSON 解析 / 代码块围栏 / JSON 前后夹带文字（`raw_decode`）/ 截断输出按字段抢救、数值越界夹到 0~1、`same_screen` 字符串转布尔、阈值与 `inconsistent` 判定、空内容与不可解析输出报错、图片缺失 / 过大报错、`health()` 四种失败态（连不上 / 模型不存在 / 无 vision / 纯 embedding 无 completion）与 omni 模型通过。

新增状态或流程时，至少保证 `test_states_registry.py` 通过（它会检查模板文件是否存在）。

---

## 8. 已知限制

1. **坐标未重新标定**：`config/coordinates.py` 的数值从旧脚本原样迁移，基准按 1024×768 客户区假设。
   若你的客户端尺寸不同，`Viewport` 会等比缩放，但个别按钮仍可能需要微调；先用 `--check` 看缩放比例。
2. **模板图片与客户端版本强绑定**：游戏更新 UI 后需要重新截图。
3. **等待时间全部走自适应，但头几轮仍需攒样本**：9 个流程都用 `core/timing.py` 记住每轮 / 每阶段耗时，
   下次先「盲等」到接近历史 p10 再细粒度识图（`--no-adaptive-wait` 可关）。
   可用样本不足 `TIMING_WARMUP_SAMPLES`(5) 时不盲等，改为沿用各 Flow 里写死的经验值
   （`BATTLE_DURATION` / `SETTLE_WAIT` / `STAGE_WAIT` / `BATTLE_PRE_WAIT` 等），
   所以**头几轮的行为与改造前一致**，之后才逐步收敛。
4. **无端到端测试**：涉及真实截图与点击的路径只能人工验证。
5. `tools/` 下的归档工具未做质量修复（部分依赖 TensorFlow 1.x、PyAudio、pywin32）。
6. **macOS 长时间挂机限制**：显示器休眠或手机锁屏时，合成点击根本送不到目标窗口。脚本会在检测到「主显示器休眠」时告警一次（`_warn_if_display_asleep`），但修不了它 —— 挂机跑之前要么关掉系统自动休眠，要么 `caffeinate -di python main.py ...`。
   窗口**激活**失败（切窗口、刚唤醒、osascript 超时）已经能自愈：自动重试 -> 跳过本次点击 -> 下一拍重来；连续失败到 `ACTIVATE_MAX_CONSECUTIVE_FAILURES` 才以退出码 1 干净退出。
7. **7 个新迁移的流程尚未真机验证**：`awake` / `seal` / `heart` / `breakthrough` / `explore` /
   `event-aband3t` / `event-aj8fer` 都已改成事件驱动，但真机只跑通过 `soul` 与 `shard`。
   装配层面有演练覆盖（引擎组装、watch 列表、订阅数、超时预算），真实界面时序仍需人工验证；
   出问题时先加 `--no-adaptive-wait` 排除自适应等待的影响。
   - `shard` 真机跑通 8 轮 + 15 轮（均值 34.9~36.5s/轮，`shard:battle` 已收敛
     p10=28.3s，0 WARNING / 0 补点），覆盖的都是「结算后直接回挑战界面」这条入口。
     章节入口导航（头像 -> 入口条 -> 选择式神行）已在真机**手动**走通（用户配合逐屏
     确认 + 每步实测分数），但自动跑里它触发的次数仍少，日志里要专门盯。
  - **早先记录的误命中分数全部作废**（入口面板 0.925 / 列表行 0.791 / 战斗画面挑战按钮
    0.713 等）：那些都是在 `TEMPLATE_SCALES` 一直试到 0.3 的条件下量的，实际命中框只有
    20×26、67×25 像素，是**缩小匹配的噪声**，不是真界面上的分数。
    还有一句也错了：当时把「选择式神屏」当成了「挑战界面」（两者都有挑战按钮 0.999），
    导致我误判列表行那一屏不存在。现在的可信矩阵见已知限制 8 的表格。
  - 现在的防线按重要性排序：**尺度下限**（根因，见 `vision/scales.py` 与已知限制 8）
    > watch 顺序（`detect_first` 顺序优先、不看分数：结算第一、列表行第二，见已知限制 8）
    > 战斗阶段门控（导航动作只在 `challenge` 阶段做）> 阈值（`SHARD_CHALLENGE` 0.85 / `SHARD_FRAGMENT_ENTRY` 0.95 / `SHARD_FRAGMENT_ROW` 0.9）。
8. **碎片「章节入口」导航已走通（2026-11-21，四屏三步点击）**：
   章节界面点紫色 Boss 头像（`碎片章节头像.png` 30x30）-> 副本界面点「式神碎片」
   入口条（`碎片入口面板.png` 111x41）-> **选择式神界面**点「头像+等级」那一行
   （`碎片列表行.png` 308x86）-> 挑战界面。第十八章实测就是这四屏，
   少点那一下就会打默认式神而不是要刷的那个。
   头像与入口条两张模板是**探针法**重裁的：拿用户截图上的目标块对实时截屏做
   多尺度匹配定位（头像 0.948@x0.53 -> 客户区 608,202；入口条 1.000@x0.50 -> 76,211），
   再从实时截屏按位置裁 —— 比例天然正确。列表行那张本来就是对的（0.978@x0.5）。
   实测矩阵（同屏多个达标是常态，`detect_first` 顺序优先不看分数）：

   | 界面 | 列表行 | 挑战按钮 | 入口条 | 头像 |
   |---|---|---|---|---|
   | 章节界面 | 0.541 | 0.558 | 0.806 | **0.986** |
   | 副本界面 | 0.511 | 0.749 | **1.000** | 0.436 |
   | 选择式神屏 | **0.978** | 0.999 | 0.928 | 0.504 |
   | 选完式神 | 0.799 | **0.999** | 0.927 | 0.592 |

   所以顺序 = 结算 > 列表行 > 挑战按钮 > 入口条 > 头像，判据另有两条：
   列表行阈值 0.9（0.978 未选 vs 0.799 已选，掉分就是「已选好」）；
   入口条阈值 0.95（真命中 1.000，噪声 0.927~0.928）。
   `ShardFlow(chapter_nav=False)` 可退回「只认挑战界面」。换手机 / 改窗口大小后
   模板会失效，重截工具见 `tools/asset_manager`，方法见本次提交历史。
9. **镜像窗口不能缩得太小，模板采集比例是混的**：`TEMPLATE_SCALES`（macOS）= 1.0~0.4，
   下限 `MIN_SCALED_TEMPLATE_SIDE = 24` 只管**绝对像素**，不管比例。
   为什么必须留到 0.4：老模板不一定按当前窗口比例采集 —— 真机实测
   `挑战_碎片.png`(56x55) 在 x1.0 = 1.00，而 `碎片打完.png`(186x208) 要到 x0.4~x0.5
   才有 0.99（x1.0 只有 0.27）。把尺度收到 1.0~0.8 会**整个废掉结算识别**（真机踩过：
   战斗打完结算点不掉，连续 35 拍啥也没识别到）。真要把窗口拖得很小，要么拉回原大小，
   要么 `YYS_TEMPLATE_SCALES` 显式放宽，要么重截模板。
   根治办法是反过来做：把截屏缩放到基准尺寸再匹配，而不是缩放模板 —— 尚未实现。
10. **`flows/explore/dog_food.py` 调用了不存在的 `Flow.double_click`**：换狗粮时会 `AttributeError`。
   这是迁移前就存在的缺陷（不是本次引入），本次未修 —— 修法是给 `Flow` 加一个转发到
   `controller.double_click` 的方法。
