# AGENTS.md — YysScript 目录职责与开发约定

本文件是**目录契约**：每个顶层文件夹负责什么、可以依赖谁、改动应该落在哪里。
修改代码前先读这份文件，改完如果发现职责边界需要调整，同步更新本文件。

---

## 1. 项目是什么

《阴阳师》客户端自动化脚本。不读游戏内存、不调游戏接口，纯视觉方案：

```
截屏 -> 图像识别 -> 判断当前界面 -> 换算坐标 -> 拟人化点击
```

**当前主线是 `runner/`**：识别交给本地多模态大模型，只判定「当前画面是不是这一张
标注截图」；界面流转顺序由分组自带的 DSL（`flow.py`）声明，跑完一步自动进下一步，
循环次数由命令行控制。

**旧的模板匹配管线（`states/` + `flows/` + `vision` 的匹配器与颜色检测）已整体归档到
`archive/`**，不再演进、不参与测试，只作参考。`actions/` `core/` `config/` `storage/`
是两条路线共用的基础设施，留在原地。

运行平台：Windows / macOS + Python 3.8+。macOS 通过「iPhone Mirroring」镜像窗口
操作 iOS 客户端。非真机环境只能跑单测与 `--dry-run`。

> ⚠️ 合规提醒：自动化脚本违反《阴阳师》用户协议，存在封号风险。本项目仅作图像识别与
> 自动化的技术学习用途。

---

## 2. 顶层目录职责表

| 目录 | 职责（一句话） | 允许依赖 | 禁止 |
|---|---|---|---|
| `config/` | 全局参数 + `Point` 坐标类型 + runner 的超时/间隔常量 | 无（纯配置） | 依赖任何业务层 |
| `core/` | 日志、异常、计时/耗时预测、事件总线、**自适应等待** | `config`、`storage` | 依赖上层业务 |
| `storage/` | **存储**：sqlite 持久化（耗时样本，表 `GAMETIME_RECORD`） | `config`、`core` | 依赖上层业务 |
| `actions/` | **操作**：找游戏窗口、`Viewport` 坐标换算、`HumanMouse` 拟人化点击 | `config`、`core`、`vision` | 业务流程判断 |
| `vision/` | **截屏**：`Frame` / `ScreenCapture`（模板匹配、颜色检测与其结果类型已归档/删除） | `config`、`core` | 点击、坐标换算、业务判断 |
| `runner/` | **当前主线**：读分组 -> 加载 DSL -> 主循环 -> 单图模型判定 -> 换算坐标并点击 | `config`、`core`、`storage`、`actions`、`vision`、`similarity` | 依赖 `archive/`；在代码里写死界面顺序（顺序属于 DSL） |
| `similarity/` | **数据采集与判定**：分组标注 Web 界面、双图对比页、Ollama 多模态判定；数据集在同目录 `dataset/groups/<key>/`，每个分组自带一份 `flow.py`（DSL） | `config`、`core`、`actions`、`vision` | 被 `runner` 以外的层 import；反向依赖 `runner` |
| `archive/` | **归档的模板匹配管线**（旧 `states/` `flows/` `main.py` `tools/asset_manager/` 及对应测试），`conftest.py` 已排除收集 | — | 被任何在用代码 import；改它 |
| `tests/` | 单元测试（不依赖游戏、不依赖 cv2/pyautogui、不连模型） | 被测模块 | 真实截屏/点击/联网 |
| `var/` | 运行时产物（日志、sqlite 数据库、调试图），不进版本库 | — | 手写文件 |
| `.worktrees/` | git worktree 隔离开发区（不入版本库） | — | 在主工作区里直接改它 |
| `main.py` | 命令行入口：列分组、生成/查看 DSL、跑轮次、dry-run | `runner`、`actions`、`core`、`config` | 写业务逻辑 |

### 依赖方向（只能从上往下）

```
main.py
  └── runner/          当前主线：分组 + DSL + 主循环
        ├── similarity/  数据集（分组/截图/标注）+ Ollama 多模态判定
        ├── actions/     点哪里、怎么点（窗口 + Viewport 换算 + HumanMouse）
        │     └── vision/  截屏（Frame / ScreenCapture）
        ├── storage/     历史耗时样本（喂自适应等待）
        ├── core/        日志 / 异常 / CycleTimer
        └── config/      参数与坐标类型

archive/               旧模板匹配管线，独立一棵树，不被上面任何一层 import
```

**反向依赖一律禁止**。两条附加约定：

1. `runner` 只**读** `similarity` 的数据集与判定能力，不改它的行为；`similarity` 不知道
   `runner` 存在，单独跑 `python similarity/app.py` 仍然完整可用。
2. `runner` 不 import `archive/` 里的任何东西。要复用旧逻辑就搬到 `core/` `actions/`
   这些共用层，再从 `archive/` 删掉引用它的意图。

---

## 3. 目录详解

### `config/` — 配置与坐标（改数值来这里）
- `settings.py`：路径、基准分辨率、超时、拟人化参数、runner 与自适应等待的参数。
  路径支持环境变量覆盖：`YYS_LOG_DIR` / `YYS_DB_PATH` / `YYS_VAR_DIR`。
  （旧代码把 `E:/github/YysScript/...` 写死在源码里，已彻底移除。）
  runner 相关：`RUNNER_DSL_FILENAME`（分组里的 DSL 文件名，默认 `flow.py`）、
  `RUNNER_STEP_TIMEOUT`(120s) / `RUNNER_ROUND_TIMEOUT`(900s) / `RUNNER_PROBE_INTERVAL`(1s) /
  `RUNNER_SETTLE_PAUSE`(0.6s)。模型与阈值走 `YYS_OLLAMA_MODEL` / `YYS_SIMILARITY_THRESHOLD`(0.6)。
  `JUDGE_MASK_TOP_PIXELS`(60，环境变量 `YYS_JUDGE_MASK_TOP_PIXELS`)：判定前把**两张图**顶部
  这么多像素涂黑，去掉镜像窗口标题栏透出的桌面壁纸；不涂黑会让同一界面被判成
  0.45 / `same_screen=false`（见已知限制 1）。图片尺寸不变，标注坐标不受影响。
- `coordinates.py`：只剩一个类型 `Point(x, y)` = 基准客户区（`BASE_CLIENT_SIZE` = 1024×768）下的
  逻辑坐标，供 `Viewport` 使用。**旧的界面坐标常量表已随模板匹配管线删除。**
  ⚠️ runner 的点击坐标不来自这个文件，而来自分组标注的像素坐标经 `Session.resolve()` 换算。
  runner 点不准就去标注页重标，不要来这里加常量。

### `core/` — 通用能力
- `logger.py`：`get_logger(name)`，全局只配置一次 handler（修掉旧代码重复 addHandler 导致的日志重复）。日志落 `var/logs/yys_script.log`，按 5MB 轮转。
- `errors.py`：`YysError` 及子类 `ConfigError` / `WindowNotFoundError` / `StateTimeoutError` / `StaminaExhaustedError` / `FlowAbortedError` / `WindowActivationError`。**不要再用 `exit(300)`**，抛异常，由 `main.py` 转退出码；也**不要抛裸 `RuntimeError`**，那会绕过 `main.py` 的异常处理变成 traceback。
- `bus.py`：`EventBus` —— 进程内**同步**发布/订阅。topic 点分层级，订阅支持 `*`（一段）/ `**`（多段）通配符；
  priority、once、异常隔离（默认吞掉订阅方异常只记日志，`strict=True` 时抛出）、递归深度保护、history 环形缓冲。
  纯标准库实现，不认识任何领域事件；领域 topic 定义在 `archive/flows/signals.py`。**runner 目前不用总线** —— 界面顺序由 DSL 声明，不需要事件驱动。
- `timing.py`：`CycleTimer`（实现 `WaitScheduler` 协议）+ `FixedScheduler` + `Estimate` / `WaitPlan` /
  `TimingSample` / `Cycle`。记录每轮 / 每阶段耗时（写 `storage.DurationStore`），并给出「先盲等多久、
  之后隔多久识图」的计划；内置异常值剔除与「连续超限回退重新收敛」。算法细节见本节末尾。

### `vision/` — 截屏（职责 1）
- `types.py`：`Frame`（截图 + 原点 + 尺寸），坐标是**屏幕绝对坐标**。（`Box` / `Match` 是模板匹配
  的命中结果类型，随旧管线一起删除。）
- `capture.py`：`ScreenCapture`，注入 `region_provider` 只截游戏窗口那块区域。`runner/` 与 `similarity/` 都靠它取图。
  按窗口编号抓内容的通道（Quartz `CGWindowListCreateImage`）**已删除**：macOS 15+ 上该 API 被 Apple 移除，
  调用会**先阻塞约 30 秒再返回 NULL**，每一拍都变成「白等 30s + 真正干活 0.1s」。
  实测（macOS 26.5）：`grab()` 30.1s → **0.13s**，单拍判定 33s → **3.3s**。
  ⚠️ 区域截屏拍的是屏幕上那块矩形，**压在上面的窗口会被一起拍进来**。因此调用方在截屏前调
  `actions.mouse.ensure_frontmost(pid, region)` 把目标窗口提到最前：只有存在「排在目标窗口之前、
  又与该区域相交」的窗口时才真置前（实测 0.36s），否则走约 4ms 的快路径，不会反复抢焦点。
- **已归档**：`template_matcher.py`（多尺度模板匹配 + NMS）、`scales.py`（尺度策略）、
  `color_detector.py`（HSV 颜色轮廓）移到 `archive/vision/`。理由见 `archive/README.md`：
  模板与客户端版本、采集比例强绑定，缩小匹配会撞出 0.9+ 假命中，脚本照着点就是在乱点。

### `storage/` — 存储（职责 2 的持久化部分）
- `schema.sql` + `database.py`：自动建表，表名沿用旧的 `GAMETIME_RECORD`，老 `gray_scan.db` 可直接复用。
- `duration_store.py`：`DurationStore`（record / average / samples / trim / clear），对应旧 `utils/grayscaness.py`。已全部参数化查询；修掉旧 `clear_kw(500)` 少传参数的必然 TypeError 和「超限直接 return 丢数据」的逻辑。

### `states/` — 已归档
整个目录移到 `archive/states/`（43 个状态常量文件 + `base.py` 注册表 + `machine.py` 状态机）。
runner 不需要状态注册表：「我在哪个界面」由模型对**一张**标注截图判定，
界面清单就是分组的截图清单，先后顺序由分组 DSL 声明。

### `actions/` — 操作（职责 3，解决"坐标写死"的关键层）
- `window.py`：`GameWindow` + `Win32WindowFinder`（按标题/类名找窗口，取**客户区**矩形，声明 DPI 感知）+ `MacWindowFinder`（macOS 按进程名定位窗口，默认「iPhone Mirroring」iOS 镜像窗口，窗口内点击透传到手机）+ `FullScreenFinder`（找不到窗口或其它平台时把整屏当客户区）。找不到窗口时按 `settings.FALLBACK_TO_FULLSCREEN` 决定回退还是抛 `WindowNotFoundError`。
- `viewport.py`：`Viewport`，纯计算。`to_screen(Point)` 逻辑坐标 → 屏幕坐标（按窗口位置平移 + 按窗口尺寸缩放 + 校准偏移 + 越界裁剪），`to_logical(screen)` 反向。**这一层让换分辨率、窗口不在原点都不再致命。**
- `mouse.py`：`HumanMouse`，只认屏幕坐标。落点随机抖动、动作间随机停顿（对应旧 `personal_pause`）、拖动分步 + 缓动。macOS 上 controller 注入目标进程 PID 后启用「礼貌点击」：点击瞬间激活目标窗口 -> 把光标 warp 到目标点**并补发一个 mouseMoved** -> 在同一坐标发 down/up -> 还原光标（同样补发 mouseMoved）与焦点，轮询识别期间完全不碰鼠标。坑：`CGWarpMouseCursorPosition` 只改窗口服务的指针坐标、不产生移动事件，App 侧缓存的光标位置（hover / Mac Catalyst 的指针→触摸桥接）不更新，只按坐标发事件会被静默丢掉，表现为「跑一段时间后点不动，手动晃一下鼠标才恢复」，所以 warp 必须配套补发 `kCGEventMouseMoved`；滚动事件本身不带坐标，也要先落点。
  **激活失败不再终止进程**：`_activate_frontmost()` 按 `ACTIVATE_MAX_ATTEMPTS` 自动重试（用户切窗口 / 刚唤醒 / osascript 超时都是瞬时的）；仍失败就跳过本次操作，`click()` 返回 `None`（`drag` / `scroll` 静默返回），由上层重置状态、下一拍重试；只有连续失败到 `ACTIVATE_MAX_CONSECUTIVE_FAILURES` 才抛 `WindowActivationError`（YysError -> 退出码 1 + 一句话，不是 traceback）。旧行为是抛裸 `RuntimeError`，未被 `main.py` 捕获，整晚挂机白跑。
  另有模块级 `ensure_frontmost(pid, region)`：**截屏前**把目标窗口提到最前（区域截屏会把压在上面的窗口一起拍进来）。判据是「窗口列表里排在目标窗口之前、又与该区域相交的窗口是否存在」，所以别的 App 窗口在屏幕其它位置时不会误触发；没被遮挡走约 4ms 快路径，被遮挡才发 osascript（实测 0.36s）。`runner/session.grab()` 与 `similarity/capture.grab()` 都调它。
- **已归档**：`controller.py`（`GameController` 门面，旧 flows 的唯一入口，`resolve()` 统一处理
  `Point` / `Match` / `Box` / `tuple` 四种点击目标）移到 `archive/actions/`。
  runner 用 `runner/session.py`（环境装配 + 坐标换算）与 `runner/actor.py`（点击）承担同样职责。

### `flows/` — 已归档
整个目录移到 `archive/flows/`：9 个玩法流程（soul / explore / shard / awake / breakthrough /
seal / heart / event-aband3t / event-aj8fer）+ 事件驱动引擎（`engine.py` / `signals.py`）+
三个可复用订阅方（`battle_cycle.py` / `stage_cycle.py` / `rules.py`）。

保留价值是**经验不是代码**：各流程的时序常量、`shard` 真机跑出来的误命中矩阵、
「watch 顺序比阈值更重要」这类结论（见已知限制末尾的归档小节）。写分组 DSL 时可以回来对照。
**不要从 runner import 它。**

### `tools/` — 已删除
原先的周边归档（鼠标坐标打印、Win10 语音控制、TeamViewer 远控、Flask demo、PyQt 骨架、
uiautomator2 实验、TF1 CNN 示例、录音脚本、番茄钟）与主流程**零关联**，已整体删除。
其中唯一引用主包的 `remote/remote_control.py` import 的是早已归档的
`vision.template_matcher`，本身就已经是坏的。
「游戏更新后重新截图 / 重标注」由 `similarity/` 标注采集页承担（截屏 → 框选/点选标注 →
存进分组，顺手就能改同组的 DSL）；旧模板图片管理界面在 `archive/tools/asset_manager/`。

---

### `similarity/` — 数据采集与模型判定（runner 的上游）

与 `archive/` 的模板匹配管线**完全隔离**：只**只读复用** `actions/window.py`（定位模拟器 /
镜像窗口）与 `vision/capture.py`（截屏）。它负责两件事：**产出数据集**（分组截图 + 标注）
与**提供判定能力**（Ollama 多模态双图对比）。`runner/` 读它的数据集、调它的判定；
它自己不知道 runner 存在，`python similarity/app.py` 单独跑仍然完整可用。

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
  （窗口标题栏透出的桌面会让它多给一档 0.45；runner 侧靠涂黑顶部解决，见已知限制 1。）
  自检 CLI：`python -m similarity.llm_judge [a.png b.png]`。

- **分组 DSL（`dataset/groups/<key>/flow.py`）**：每个分组自带一份 Python 文件，声明这组截图的
  界面流转顺序，runner 发现它就自动加载。**没有这个文件时，按分组名直接跑会自动生成一份链式草稿**
  （按截图采集顺序一步接一步）并落盘；也可 `--init-dsl` 显式生成（`--force` 覆盖）。
  截图 PNG 不入版本库，但 `flow.py` **入库** —— 它是逻辑不是数据。语法见下面 `runner/` 一节。

细节见 `similarity/README.md` 与 `runner/README.md`。

### `runner/` — 当前主线：分组 + DSL + 主循环

一句话：**一个分组 = 一套界面截图 + 标注 + 一份 DSL**。runner 按 DSL 声明的顺序，
逐步「等这张图出现 → 点这个标注」，跑完最后一步回到第一步，循环 N 次。

| 文件 | 职责 |
|---|---|
| `group.py` | 只读打开 `similarity/dataset/`：`GroupRef` / `ShotRef` / `AnnotationRef`；按**标注名 / 截图备注 / 截图 id** 解析到具体截图与标注 |
| `dsl.py` | 加载分组里的 `flow.py`：注入命名空间 -> 执行 -> 校验 `steps` -> 收集钩子；`load_or_scaffold()` 在没有 `flow.py` 时按标注顺序自动生成链式草稿 |
| `session.py` | 一次运行的环境：找窗口 -> `Viewport` -> `ScreenCapture`（区域绑定窗口）-> `HumanMouse`。`resolve(shot, x, y)` 把标注像素换算成逻辑坐标与屏幕坐标。**cv2 / pyautogui 懒加载**，import 本包不需要它们 |
| `matcher.py` | `ScreenMatcher.matches(shot)`：**只比对当前这一步的那一张图**；送模型前把两张图顶部 `JUDGE_MASK_TOP_PIXELS` 像素涂黑（去掉镜像窗口标题栏透出的桌面）；返回 `Verdict(matched, score, same_screen, elapsed, detail)`，并把判定耗时记进自适应等待 |
| `actor.py` | 点击：逻辑坐标 -> `Viewport.to_screen` -> `HumanMouse.click`；`dry_run` 时只记日志不动鼠标 |
| `engine.py` | `Runner.run()` 主循环 + `Context`（钩子里能用的截屏/比对/点击/变量）+ `RunReport` / `RoundReport` |
| `gfx.py` | **图形算法库**，已注入 DSL 命名空间，DSL 里直接写 `gfx.brightness(png)`；要加自己的算法就在这个文件加一个函数 |
| `errors.py` | `RunnerError` 及子类 `DslError` / `GroupError` / `StepTimeoutError` / `RoundTimeoutError`，都继承 `YysError`，由 `main.py` 转退出码 |

**DSL 长什么样**（`similarity/dataset/groups/<key>/flow.py`，文件里**不需要任何 import**）：

```python
name = "御魂十一"
round_timeout = 600

steps = [
    step("挑战", timeout=90),      # 等到「挑战」这张图 -> 点它的标注
    step("完成", timeout=300),     # 战斗打完 -> 点结算
]

def on_step_timeout(ctx, st):
    """超时兜底：返回 True 表示已自愈，继续下一步。"""
    ctx.log.warning("步骤 %s 等不到", st.name)
    return False
```

加载时注入 DSL 的名字：`step` / `Step` / `gfx` / `log` / `group` / `shots` / `labels` / `settings`。

- `step(target, click=None, shot=None, label=None, timeout=None, interval=None, blind_wait=None,`
  `settle=None, optional=False, on_match=None, on_timeout=None)`。
  `target` 用**标注名 / 截图备注 / 截图 id** 指认界面；`click` 是命中后点哪个标注，默认与 `target` 同名；
  同组标注名有歧义时用 `shot=` 显式指定截图。
- 模块变量 `entry`（可选）：**入口对齐**。每轮开头按声明顺序逐个探测候选图，
  命中第 N 步就从第 N 步起跑，命中的那次判定直接复用、不再重复判定。
  用于一轮的合法起点不固定在 `steps[0]` 的情况（例如手机可能停在「碎片副本选中」）。
  `entry = "all"` 按声明顺序探测全部步骤；名字同样认 `target` / `click` / `label`；
  不写 = 每轮从第 1 步开始。把最常见的放第一个，正常回环探测 1 次就命中。

- 钩子（函数名固定，全部可选）：`before_run` / `after_run` / `on_round_started` /
  `on_round_finished` / `on_step_matched`（命中后、点击前，返回 `False` 跳过本次点击）/
  `on_step_timeout`（返回 `True` 表示已自愈，继续下一步）。
- `ctx`（`runner/engine.Context`）能做的：`grab()` 截屏拿 PNG 字节、`matches(name)` 比一张图、
  `compare(a, b)` 比任意两图、`click_label(name)` 点某个标注、`click_logical(Point)` /
  `click_screen((x, y))`、`wait(s)`、`stop(reason)` 优雅停止、`fail(msg)` 中止并抛异常、
  `ctx.vars` 读写跨轮变量、`ctx.log` / `ctx.gfx`、`ctx.round_index` / `ctx.times` / `ctx.shots`。
  **复杂处理写钩子，不用改 runner 本体。**
- ⚠️ **不要在 DSL 里写 `blind_wait`**：它会永久覆盖自适应等待算出来的值，等于把智能等待关掉。

**为什么每步只比一张图**：DSL 已经把界面顺序声明出来了，第 N 步只可能出现在第 N 张图上，
不必拿分组里所有图轮一遍。单次判定 1.3~2.8 秒，省下来的每一拍都是秒级收益。

**坐标怎么换算**（两套 Viewport，最容易搞错，详见第 4 节）：标注像素是按**截图当时的窗口**
存的，所以 `Session.resolve()` 要先把它还原成屏幕坐标、再归一到逻辑坐标、再按**当前**窗口放大。
窗口挪过、改过大小都仍然点得准。

### 自适应等待（`core/timing.py`，两条路线共用）

runner 沿用 `CycleTimer`，只是换了计时 key：`"<分组名>:<步骤名>"`（每步）、
`"<分组名>:round"`（整轮，引擎自动记）、`"<分组名>:probe"`（一次截屏 + 判定的成本，
只在内存滑动平均，不入库）。样本表沿用 `GAMETIME_RECORD`，**老 `gray_scan.db` 直接可用**。

`CycleTimer.plan()` → `WaitPlan(blind_wait, interval)`：

1. 可用样本 < `TIMING_WARMUP_SAMPLES`(5) → `blind_wait=0` + 调用方给的 interval；
2. 收敛后 → `blind_wait = p10 × TIMING_SAFETY(0.85) − 一次判定成本`，之后按 `TIMING_FINE_INTERVAL`(1s) 细轮询；
3. 硬上限 `min(TIMING_MAX_BLIND_WAIT(90s), timeout − TIMING_FINE_WINDOW(10s))`，估计再离谱也不会长时间瞎等；
4. **防不收敛（两个方向都要防）**：异常阈值 = `max(p50 × TIMING_OUTLIER_FACTOR(2.5), p50 + TIMING_OUTLIER_FLOOR(30s))`，
   超过的样本不计入 min/p10（仍入库审计）；连续 `TIMING_OVERRUN_RESET`(2) 次异常就丢掉内存窗口、
   回到 warm-up 用探测频率重新攒样本，并用更保守的 `TIMING_RESET_SAFETY`(0.5) 重新收敛。
   - *样本过大*：「等太久 → 样本更大 → 盲等更久 → 最小值永远下不来」这个死循环跑不起来；
   - *样本过小*：**可用样本不足 `TIMING_WARMUP_SAMPLES` 时一律不判异常**（没有基线就谈不上异常），
     且阈值带绝对下限 —— 否则一个偶然很小的样本会把阈值压到 0.11 秒，之后每个真实样本
     都被误判成异常剔除，`usable` 永远攒不够 → **永久不收敛**，还会每轮刷误导性 WARNING。

---

## 4. 两套坐标语义（最容易搞错的地方）

| 类型 | 定义 | 出现在 | 谁负责转换 |
|---|---|---|---|
| **标注像素坐标** | 截图 PNG 自己的像素坐标（图片左上角为原点） | `dataset/.../shots/<id>.json`、DSL 里的 `ctx.click_label` | `Session.resolve()` |
| **逻辑坐标** `Point(x, y)` | 基准客户区 1024×768 下的坐标 | `Viewport`、`ctx.click_logical`（类型定义在 `config/coordinates.py`） | `Viewport.to_screen()` |
| **屏幕绝对坐标** | 显示器真实像素坐标 | `vision` 的 `Frame`、`actions/mouse.py` | — |

runner 的换算链（`Session.resolve(shot, x, y)`，四步、两套 Viewport）：

```
标注像素 + 截图当时的客户区原点/尺寸
  -> 屏幕绝对坐标
  -> to_logical()（按**截图时**的窗口）   -> 逻辑坐标（跨窗口可复用的中间表示）
  -> to_screen()（按**当前**窗口位置尺寸） -> 屏幕绝对坐标 -> HumanMouse.click()
```

规则：
1. **DSL 里不要出现裸坐标**：点击位置一律用标注名指认，坐标存在标注 JSON 里，改位置去标注页重标。
2. 逻辑坐标只是中间表示，不是最终落点；窗口挪过 / 改过大小都仍然点得准。
3. `ctx.click_logical(Point)` 会按当前窗口换算，`ctx.click_screen((x, y))` 原样当屏幕坐标用 —— 语义不同，别混。
4. 截图必须是**当前窗口比例**下采的：模型判定看整张图，比例不对会掉分（点得准但认不出）。

---

## 5. 常见任务落点

| 想做什么 | 改哪里 |
|---|---|
| 某个标注点不准 | 标注采集页（`similarity/app.py`）里重标那张图（`config/coordinates.py` 已无界面坐标常量） |
| 认不出某个界面 | 先 `--debug` 看模型给的 `reason` / `differences`；图不对就重截，阈值不对调 `--threshold` |
| 游戏更新导致界面变了 | 标注采集页重新截屏 + 标注，存进同一个分组（DSL 里的名字不变就不用改 DSL） |
| 改一个玩法的顺序 / 超时 | 该分组的 `flow.py`（`steps` 顺序、`timeout`、`round_timeout`） |
| 加一条「遇到 X 就点 Y」的规则 | 该分组 `flow.py` 里加钩子（`on_step_matched` / `on_step_timeout`），或用 `step(..., optional=True)` |
| 需要新的图形算法 | 加在 `runner/gfx.py`，DSL 里直接 `gfx.你的函数(...)` |
| 新起一个玩法 | 标注页新建分组 -> 截图标注 -> 直接 `python main.py --group <名> --times N`（自动按截图顺序生成链式 `flow.py`）-> 再调 `steps` |
| 换分辨率 / 窗口改大小后整体偏移 | `config/settings.py` 的 `BASE_CLIENT_SIZE` / `CALIBRATION_OFFSET`；多数情况 `Viewport` 会自动缩放，无需改 |
| 点击太快 / 太规律 | `settings.py` 的 `HUMAN_JITTER` / `HUMAN_PAUSE_RANGE` / `HUMAN_DRAG_STEPS`，或 `--no-humanize` 对照 |
| 日志、数据库位置 | 环境变量 `YYS_LOG_DIR` / `YYS_DB_PATH`，或 `settings.py` |
| 等太久 / 判定太频繁 | 分组 `flow.py` 的 `timeout` / `interval`；全局默认在 `settings.py` 的 `RUNNER_*` 与 `TIMING_*` |
| 窗口激活失败（点击没反应但没报错） | `settings.py` 的 `ACTIVATE_*`：重试次数 / 间隔 / 连续失败上限；日志里搜「激活目标窗口失败」 |
| 想临时关掉自适应等待 | `--no-adaptive-wait` 或环境变量 `YYS_ADAPTIVE_WAIT=0` |
| 想看每轮花了多少时间 | 结束时 `RunReport.summary()` 打的总账；原始样本在 `var/gray_scan.db` 的 `GAMETIME_RECORD` |
| 换判定模型 | `--model` 或 `YYS_OLLAMA_MODEL`（必须同时具备 completion + vision） |
| 想复活旧的模板匹配流程 | 见 `archive/README.md` 的「怎么复活某一块」 |

---

## 6. 运行与自检

```bash
pip install -r requirements.txt      # cv2 / pyautogui / numpy；runner 单测不需要它们
ollama pull lfm3-omni:latest         # 判定模型，必须 completion + vision

# 1) 采集：起标注页，新建分组 -> 截屏 -> 框选/点选标注 -> 保存
python similarity/app.py                       # http://127.0.0.1:8901，只绑本机

# 2) DSL：没有 flow.py 时会按截图采集顺序自动生成链式流程，也可显式生成 / 查看
python main.py --list                          # 列出全部分组（含截图数 / 标注数 / 有没有 DSL）
python main.py --group 御魂十一 --init-dsl      # 显式生成 flow.py 草稿（--force 覆盖）
python main.py --group 御魂十一 --show          # 打印解析结果：每步的截图、标注、坐标、超时

# 3) 跑
python main.py --group 御魂十一 --dry-run       # 解析 + 打印，不截屏不点击（不需要真机）
python main.py --group 御魂十一 --times 10      # 跑 10 轮；不给 --times 就无限循环

# 常用开关
python main.py --group 御魂十一 --times 5 --debug              # DEBUG 日志，含每次判定的理由与差异
python main.py --group 御魂十一 --no-adaptive-wait             # 关自适应等待，固定间隔轮询
python main.py --group 御魂十一 --continue-on-error            # 某轮失败也继续下一轮
python main.py --group 御魂十一 --round-timeout 300            # 覆盖整轮超时
python main.py --group 御魂十一 --model qwen2.5vl --threshold 0.7
python main.py --group 御魂十一 --data-dir /path/to/dataset    # 换数据集目录

# 模型自检
python -m similarity.llm_judge [a.png b.png]
```

退出码：`0` 正常 / `1` 运行异常（`YysError`，含截屏与点击失败）/ `2` 参数、分组或 DSL 错误 /
`130` 用户中断 / `300`（`settings.EXIT_CODE_ABORT`）体力耗尽。

---

## 7. 测试

```bash
python -m pytest tests -q
```

测试**不需要** cv2、pyautogui、pywin32、Ollama，也不截屏不点击（假的 grabber / judge /
mouse 注入进去）。`pytest.ini` 的 `testpaths = tests` + `norecursedirs` 把 `archive/` 排除在外，
`archive/conftest.py` 再兜一层 `collect_ignore_glob`。

- `test_runner.py`：**runner 全链路**（63 个用例）。分组解析与按名字找截图/标注、DSL 加载与
  校验（缺 `steps` / 语法错 / 非 `step()` 元素 / 钩子收集 / `--init-dsl` 草稿）、
  **坐标换算的精确像素断言**（标注 (598,306) -> 逻辑 (887,660)；窗口没动 -> 屏幕 (787,557)；
  窗口挪到 (100,50) -> 屏幕 (987,710)）、步骤解析、主循环轮数、**每步只比一张图**、
  步骤/整轮超时、钩子返回值语义（`on_step_matched` 返回 False 跳过点击、`on_step_timeout`
  返回 True 继续）、自适应等待接入、重试、`gfx` 辅助函数、**`entry` 入口对齐**（停在序列任意
  一格都从那格起跑、探测命中的判定直接复用、候选全不中回退第 1 步、`entry = "all"`、
  写了不存在的步骤名加载期报错）、**截屏前置前**（`Session.grab` 传 pid + region）。
- `test_similarity_annotator.py`：`similarity/` 采集与对比工具的存储与 API 契约（假 grabber /
  假 judge / 假 comparer）：截图落盘 PNG + JSON、前端依赖字段齐全、列表按时间倒序、
  框 / 点标注保存与回读、越界与非法 kind 被拒、非法 shot id 与路径穿越拦截、删除清理三个文件、
  缩略图端点、页面与静态资源可访问；**分组**：首次启动自动建 `default` 组、旧 `shots/`+`thumbs/`
  迁移进默认组且**幂等**、多组数据物理隔离（跨组读图 / 读标注 404）、组名必填与去重、
  改名 / 改说明、删除组连目录一起删、删到最后一个组自动重建 `default`、跨组移动截图、
  非法 group key 与路径穿越拦截；**对比页**：两次捕获落 `compare/` 且不污染标注数据集、
  模型判定结果透传、缺槽位 400、图不存在 404、抛异常 / 返回非 dict 转 500、模型不可用转 503；
  **模型客户端**：JSON 解析 / 代码块围栏 / 前后夹带文字（`raw_decode`）/ 截断输出按字段抢救、
  数值越界夹到 0~1、`same_screen` 字符串转布尔、阈值与 `inconsistent` 判定、
  `health()` 四种失败态与 omni 模型通过。
- `test_viewport.py`：坐标换算、缩放、偏移、越界裁剪。
- `test_timing.py`：warm-up 退化、收敛后的盲等计算、异常值剔除、**连续超限回退并重新收敛**、
  盲等硬上限、discard 不入库、样本跨进程复用、窗口裁剪、识图成本滑窗。
- `test_bus.py`：事件总线的投递顺序 / priority、`*` 与 `**` 通配符、精确订阅、退订、once、
  异常隔离、递归深度保护、history。（runner 目前不用总线，测的是共用能力本身。）
- `test_duration_store.py`：sqlite 读写、均值、裁剪、SQL 注入防护。
- `test_mouse_activation.py`：窗口激活失败时**自动重试**、重试耗尽后跳过操作而不是崩进程、
  连续失败到上限抛 `WindowActivationError`、成功清零连续计数、非礼貌点击路径不受影响；
  **截屏前置前**：区域相交判定、区域外的窗口不算遮挡、菜单栏 / 最小化窗口跳过、
  窗口列表取不到时保守判为遮挡、没被遮挡时一次 osascript 都不发、拿不到 PID 时静默跳过。

改 runner / similarity 后至少保证 `test_runner.py` 与 `test_similarity_annotator.py` 通过。
新增分组不需要改测试（DSL 是数据，`--show` 与 `--dry-run` 就是它的检查工具）。

---

## 8. 已知限制

1. **模型判定慢，而且只分得开两档**：单次 1.3~4 秒；`similarity` 实测只有「同屏 0.99 /
   不同屏 0.05」两档，所以它能答「是不是同一界面」，**不能当连续相似度度量**。
   `matched = same_screen AND score >= 阈值(0.6)`：模型给 `same_screen=false` 时，
   **把阈值降到 0.4 也照样不命中** —— 别拿调阈值当万能解。
   ⚠️ 实测出现过第三档 **0.45**（雷麒麟「完成」连续 70 次、卡满 120s 超时）：镜像窗口上沿
   是标题栏，透出桌面壁纸且每局不同，模型据此判「不是同一界面」，理由里却写着
   "同一功能页面"。像素证据：失败图与参照图顶部 60px 平均差 80.5，其余各带只有 3~24。
   修法是判定时把两张图顶部 `JUDGE_MASK_TOP_PIXELS`(60) 涂黑（`runner/gfx.mask_top`），
   涂黑后 0.45/false -> **0.99/true**，同组「挑战 vs 完成」仍是 0.05/false。
   **不要改 prompt 来放宽**：试过「只看布局、忽略背景」的写法，目标场景是修好了，
   但同组的「挑战 vs 完成」被误判成同一界面（0.85），会导致在挑战屏点完成的坐标。
2. **必须用同时具备 completion + vision 的模型**：纯 embedding 模型不行 —— 实测
   `embeddinggemma-2:740m` 虽然 capabilities 带 vision，但 Ollama `/api/embed` 会**静默丢弃**
   `images`（三张不同图返回同一向量，cosine=1.000000，0.02s 无视觉编码），且不支持 generate / chat。
   `health()` 启动自检会拦住并给出原因。
3. **runner 已真机端到端跑通（2026-11-23，御魂十一 / iPhone Mirroring）**：`--times 1` 与
   `--times 2` 都跑完整轮 —— 挑战界面 0.99 → 点挑战 → 战斗 → 结束画面 0.99 → 点完成 → 回挑战，
   2 轮 132s（约 66s/轮），4 次点击、22 次判定、0 失败。窗口被挪到 (55,48) 后落点仍正确
   （标注 (598,306) → 逻辑 (887,660) → 屏幕 (651,355)）。
   踩到并修掉的坑：macOS 15+ 的 `CGWindowListCreateImage` 每次白等 30 秒（见 `vision/` 一节），
   表现就是「结束了半天不点、像卡在结束画面」；修复后结束画面 3~6 秒内就被认出并点掉。
   长跑前先 `--times 1 --debug` 确认判定理由与落点，再放量。
4. **无端到端测试**：涉及真实截屏、真实模型、真实点击的路径只能人工验证。
5. **截图必须与当前窗口比例一致**：模型判定看的是整张图。换手机 / 改镜像窗口大小后，
   旧截图会掉分甚至认不出 —— 重新截一组，别去调阈值。标注坐标本身不受影响（走逻辑坐标换算）。
6. **中途分支仍要靠钩子**：起点不定已经能声明（`entry` 入口对齐）；但「同一步之后
   有时回 A、有时回 B」这种**轮中间的分支**还没有语法，只能
   `on_step_timeout` 里 `ctx.matches("B")` 判一下、`ctx.click_label(...)` 点掉，
   返回 `True` 让主循环继续。真要做需要给 `step()` 加 `alternatives=`，尚未实现。
7. **头几轮仍需攒样本**：可用样本 < `TIMING_WARMUP_SAMPLES`(5) 时不盲等，按 `interval` 轮询；
   之后才逐步收敛。所以前 5 轮偏慢是预期行为，不是坏了。
8. **模型输出可能被截断**：`llm_judge` 会按字段抢救（`raw_decode` + 逐字段回填），
   极端情况仍会抛 `JudgeError`；runner 转成 `RunnerError` -> 退出码 1。要挂机整晚配 `--continue-on-error`。
9. **macOS 长时间挂机限制**：显示器休眠或手机锁屏时，合成点击根本送不到目标窗口。
   脚本检测到「主显示器休眠」会告警一次（`_warn_if_display_asleep`），但修不了它 ——
   挂机前关掉系统自动休眠，或 `caffeinate -di python main.py ...`。
   窗口**激活**失败已能自愈：自动重试 -> 跳过本次点击 -> 下一拍重来；
   连续失败到 `ACTIVATE_MAX_CONSECUTIVE_FAILURES` 才以退出码 1 干净退出。

### 归档管线的历史结论（模板匹配，只作参考）

这些是 `archive/` 那条路线真机踩出来的，**不再影响 runner**，但解释了为什么换路线，
以及哪天要复活模板匹配必须先解决什么。注意：`assets/templates/` 那 41 张模板图与
`settings` 里的阈值 / 尺度常量已删除，复活时要**重新采集模板**，图片可从 git 历史取回。

- **模板与采集比例强绑定**：同一张画面上 `挑战_碎片.png`(56x55) 在 x1.0 = 1.00，
  而 `碎片打完.png`(186x208) 要到 x0.4~x0.5 才有 0.99（x1.0 只有 0.27）。尺度表只能放宽到 0.4；
  收到 1.0~0.8 会**整个废掉结算识别**（真机踩过：战斗打完结算点不掉，连续 35 拍啥也没识别到）。
  根治办法是反过来做 —— 把截屏缩放到基准尺寸再匹配，而不是缩放模板，尚未实现。
- **缩小匹配会撞出假命中**：下限 `MIN_SCALED_TEMPLATE_SIDE = 24` 只管**绝对像素**、不管比例，
  模板缩到几十像素就失去判别力。**早先记录的误命中分数全部作废**（入口面板 0.925 /
  列表行 0.791 / 战斗画面挑战按钮 0.713）：那些是在尺度试到 0.3 的条件下量的，
  实际命中框只有 20×26、67×25 像素，是噪声不是真命中。当时还把「选择式神屏」误当成
  「挑战界面」（两者都有挑战按钮 0.999），导致误判列表行那一屏不存在。
- **watch 顺序比阈值更重要**：`detect_first` 顺序优先、不看分数，结算模板必须排第一，
  否则被入口面板遮蔽（真机卡死过近 4 分钟）。
- **`shard` 章节入口导航的四屏实测矩阵**（2026-11-21，第十八章；同屏多个达标是常态）：

  | 界面 | 列表行 | 挑战按钮 | 入口条 | 头像 |
  |---|---|---|---|---|
  | 章节界面 | 0.541 | 0.558 | 0.806 | **0.986** |
  | 副本界面 | 0.511 | 0.749 | **1.000** | 0.436 |
  | 选择式神屏 | **0.978** | 0.999 | 0.928 | 0.504 |
  | 选完式神 | 0.799 | **0.999** | 0.927 | 0.592 |

  顺序 = 结算 > 列表行 > 挑战按钮 > 入口条 > 头像；另有两条判据：列表行阈值 0.9
  （0.978 未选 vs 0.799 已选，掉分就是「已选好」）、入口条阈值 0.95（真命中 1.000，噪声 0.927~0.928）。
  `shard` 真机跑通 8 轮 + 15 轮（均值 34.9~36.5s/轮，`shard:battle` 收敛到 p10=28.3s，
  0 WARNING / 0 补点），覆盖的都是「结算后直接回挑战界面」这条入口。
- **`archive/flows/explore/dog_food.py` 调用了不存在的 `Flow.double_click`**：换狗粮时会
  `AttributeError`。迁移前就存在的缺陷，未修 —— 修法是给 `Flow` 加一个转发到
  `controller.double_click` 的方法。
- **旧坐标表的数值本来就没重新标定**：从旧脚本原样迁移，按 1024×768 客户区假设。这些常量已随
  模板匹配管线删除，`config/coordinates.py` 现在只剩 `Point` 类型；要查原值见 git 历史。
