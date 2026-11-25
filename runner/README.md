# runner/ — DSL 驱动的分组标注执行管线

把 `similarity/` 采集到的「分组 + 截图 + 标注」真正跑起来：主循环按分组里的 DSL 声明
顺序推进，每一步**只比对一张目标图**（不是遍历整组），命中后点标注位置。

```bash
python main.py --list                       # 列出全部分组
python main.py --group 御魂十一 --init-dsl   # 显式生成草稿（缺 flow.py 时首次运行会自动生成链式草稿）
python main.py --group 御魂十一 --show       # 打印解析结果（不截屏不点击）
python main.py --group 御魂十一 --dry-run    # 走引擎但不执行（离线可用）
python main.py --group 御魂十一 --times 10   # 跑 10 轮
python main.py --group 御魂十一              # 无限循环，Ctrl-C 停
```

退出码：`0` 正常 / `1` 流程异常 / `2` 参数或 DSL 错误 / `130` 用户中断 / `300` 体力耗尽。

## 分层

| 文件 | 职责 |
|---|---|
| `group.py` | 分组解析：读数据集 → `GroupRef` / `ShotRef` / `AnnotationRef`（box 标注自动取中心点） |
| `dsl.py` | 加载 `flow.py`：注入命名空间、`exec`、校验 steps、收集钩子；`load_or_scaffold()` 缺文件时按标注生成链式草稿 |
| `session.py` | 窗口 + 截屏 + **Viewport 坐标换算** + 拟人化鼠标（旧 `GameController` 的精简替代） |
| `matcher.py` | 单图比对：截当前屏 → 两张图顶部涂黑 → 送模型 → `Verdict`；判定耗时记进 probe 窗口 |
| `actor.py` | 点击：命中后停顿、调 `session.click_annotation`、激活失败自动重试 |
| `engine.py` | 主循环：轮次控制、按 steps 推进、自适应等待、超时、钩子、报告 |
| `gfx.py` | 外部图形算法库，DSL 里直接 `gfx.xxx()` 调用 |

依赖方向：`main.py → runner/ → (actions/ + core/ + config/ + storage/ + vision/capture + similarity/)`。
`runner/` 不被 `similarity/` 反向依赖；`similarity/` 只提供数据与模型判定。

## 坐标怎么换算（三套语义）

| 类型 | 定义 | 谁产出 |
|---|---|---|
| 标注坐标 | 截图**原始像素**，原点 = 截图左上角 | 标注采集页 |
| 逻辑坐标 | 基准客户区 1024×768（`config/coordinates.Point`） | Viewport |
| 屏幕坐标 | 显示器绝对像素 | Viewport → 交给 HumanMouse |

标注点击走**两次** Viewport：

```
标注像素 (598,306)
  + 采集时窗口原点 (189,251)  ->  屏幕 (787,557)
  用「采集时」窗口矩形 (189,251,690,356) to_logical  ->  逻辑 (887,660)
  用「当前」窗口矩形 to_screen                        ->  当前屏幕坐标
  HumanMouse.click(当前屏幕坐标)                       ->  抖动 + 随机停顿 + macOS 礼貌点击
```

所以**采集之后把镜像窗口拖动或缩放，点击位置依然落在同一个界面元素上**。
截图 JSON 里的 `region` / `origin` 就是为这一步存的（采集当时的窗口矩形）。
窗口尺寸没变时，这套换算是恒等的（(598,306) → (787,557)），不会引入误差。

## DSL 写法

文件位置：`similarity/dataset/groups/<key>/flow.py`（文件名可用 `YYS_RUNNER_DSL` 改）。
主流程发现它就自动加载。**不需要任何 import** —— 这些名字已经注入：

| 注入名 | 是什么 |
|---|---|
| `step(...)` | 声明一步 |
| `gfx` | 图形算法库（`runner/gfx.py`） |
| `shots` | 本组全部 `ShotRef`，按采集时间排序 |
| `group` | 本组 `GroupRef` |
| `labels` | 本组全部标注名（去重） |
| `log` / `settings` | 日志器 / 全局配置 |

### step()

```python
step(target, click=None, shot=None, label=None, timeout=None, interval=None,
     blind_wait=None, settle=None, optional=False, on_match=None, on_timeout=None)
```

| 参数 | 含义 |
|---|---|
| `target` | 期望出现的界面，用**标注名** / 截图备注 / 截图 id 指认 |
| `click` | 命中后点哪个标注名，默认与 `target` 同名 |
| `shot` | 标注名有歧义时（多张图都有同名标注），显式指定截图 id |
| `timeout` | 这一步最多等多少秒，默认 `RUNNER_STEP_TIMEOUT`(120) |
| `interval` | 两次判定之间**额外**睡眠秒数，默认 `RUNNER_PROBE_INTERVAL`(1.0) |
| `blind_wait` | 强制盲等秒数，**会覆盖自适应等待**（一般别写，见下） |
| `settle` | 命中后、点击前的停顿，默认 `RUNNER_SETTLE_PAUSE`(0.6) |
| `optional` | `True` 时等不到就跳过这一步，不算失败 |
| `on_match` / `on_timeout` | 本步专属钩子 |

解析规则：`target` 先按**标注名**找（唯一命中即用），找不到再按**备注**，再按**截图 id**；
多处命中会报错并列出候选 id。`click` 省略时：目标图只有一个标注就点它，
多个标注则报错要求指名。目标图**没有任何标注**时，这一步只识别不点击。

### 最小例子（就是「御魂十一」现在的 DSL）

```python
name = "御魂十一"
round_timeout = 600

steps = [
    step("挑战", timeout=90),
    step("完成", timeout=300),
]
```

跑完最后一步自动回到 `steps[0]`，轮数由 `--times` 控制。

### entry：起点不在第 1 格时，先对齐再跑

「御魂十一」正常是 `挑战 -> 完成`，另一条来路是
`碎片副本选中 -> 式神选中 -> 挑战 -> 完成`。手机停在哪个界面不由脚本决定，
所以每轮开头先问一次「现在是哪张图」：

```python
steps = [
    step("碎片副本选中", timeout=60),
    step("式神选中", timeout=60),
    step("挑战", timeout=90),
    step("完成", timeout=300),
]

entry = ["挑战", "碎片副本选中", "式神选中", "完成"]
```

- 按 `entry` 的**声明顺序**逐个判定，命中第 N 步就从第 N 步起跑，跑到序列末尾结束本轮；
- 命中的那次判定**直接复用**，不会为同一步再截一次图；
- 顺序就是成本：正常回环第一个就命中，额外开销≈0；最坏探测次数 = 候选数；
- 全都不命中 → 记 WARNING，退回从第 1 步开始等（等于不写 `entry`）；
- `entry = "all"` 按 `steps` 声明顺序探测全部；`--dry-run` 不截屏，探测整段跳过；
  `--show` 会打印入口探测顺序。

写进 `steps` 的图必须已在该分组里标注过，否则解析期就报
「分组里找不到「xxx」」并列出可用标注 —— 先去标注页补那两屏，再改这份 DSL。

### 钩子（函数名固定，写了就自动挂上）

```python
def before_run(ctx): ...
def on_round_started(ctx): ...
def on_step_matched(ctx, st):     # 命中后、点击前；return False 跳过本次点击
def on_step_timeout(ctx, st):     # 超时兜底；return True = 已自愈，继续下一步
def on_round_finished(ctx, report): ...
def after_run(ctx, report): ...
```

`st` 是 `Step`，`report` 是 `RoundReport` / `RunReport`。钩子里抛异常会转成
`RunnerError` 并写进当轮报告（不会静默吞掉）。

### ctx 能做什么

```python
ctx.group / ctx.flow / ctx.shots          # 数据
ctx.round_index / ctx.times               # 进度
ctx.vars                                  # dict，跨步骤存自己的状态
ctx.log / ctx.gfx                         # 日志与图形算法
ctx.grab()                                # 截当前屏，返回 PNG 字节
ctx.matches("完成")                        # 当前画面是不是这张图 -> Verdict
ctx.compare(a, b)                         # 任意两张图（路径或字节）互比
ctx.shot("挑战")                           # 按标注名/备注/id 取 ShotRef
ctx.click_label("完成", "确定")             # 点某张图上的某个标注
ctx.click_logical(Point(x, y))            # 点基准逻辑坐标
ctx.click_screen((x, y))                  # 点屏幕绝对坐标
ctx.wait(1.5)
ctx.stop("体力耗尽")                       # 优雅停止，跑完当前步骤退出
ctx.fail("出错了")                         # 立即中止并报错
ctx.timer / ctx.session / ctx.matcher / ctx.actor   # 需要更底层时直接拿
```

### 用 gfx 做自定义判断

```python
def on_step_matched(ctx, st):
    png = ctx.grab()
    if gfx.brightness(png) < 40:
        ctx.log.warning("画面过暗，可能息屏了")
        return False
    if gfx.color_ratio(png, (0, 120, 100), (10, 255, 255)) > 0.2:
        ctx.click_label("挑战", "确认")
```

`gfx` 现有：`decode` / `encode_png` / `size` / `gray` / `brightness` / `saturation` /
`crop` / `resize` / `align` / `mean_pixel_diff` / `histogram_similarity` /
`changed_ratio` / `is_mostly_dark` / `color_ratio` / `center_of` / `scale_point` / `describe`。
都接受 PNG 字节、路径或 numpy 数组。要加新算法直接在 `gfx.py` 里加函数，DSL 立刻能用。

## 智能等待怎么保留的

沿用 `core/timing.py`，没有重写：

- 每步计时 key = `<分组名>:<步骤名>`（如 `御魂十一:挑战`），整轮 = `<分组名>:round`，
  样本落 `var/gray_scan.db` 的 `GAMETIME_RECORD`（**老库直接可用**）；
- 每步开等前问 `timer.plan(key, timeout, interval)`：可用样本 < 5 时不盲等（= 头几轮
  按 `interval` 轮询攒样本），收敛后盲等到 `p10 × 0.85 − 一次判定成本`，再按
  `TIMING_FINE_INTERVAL` 细轮询；
- 一次模型判定实测 1.3~2.8 秒，会通过 `record_probe()` 记进 probe 滑动窗口，
  盲等时自动扣掉，避免"刚盲等完就白判定一次"；
- 超时 / 异常的轮次走 `discard()` 不入库，不污染估计；
- `--no-adaptive-wait` 可整体关掉。

> ⚠️ **别在 DSL 里写 `blind_wait`**，它会永久覆盖自适应算出来的值，等于把智能等待关掉。
> 只有某一步的耗时完全固定、且你确定不想让它自学时才用。

## 模型调用成本

一次判定 1.3~2.8 秒（`lfm3-omni:latest`，本机 MLX）。因为每步只比对**一张**目标图，
一轮的判定次数 ≈ 各步轮询次数之和；自适应盲等收敛后，稳定态下一步通常只判定 1~2 次。
头 5 轮是 warm-up，判定次数会明显偏多，属正常。

要压成本：把 `RUNNER_PROBE_INTERVAL` 调大（默认 1.0，真实周期 = 判定耗时 + 该值），
或在 DSL 里给长步骤单独设 `interval`。

## 测试

```bash
python -m pytest tests/test_runner.py -q
```

窗口 / 鼠标 / 截屏 / 模型全部注入假实现，**不截屏、不点击、不连 Ollama、不需要
cv2 / pyautogui**（`runner/` 各模块导入期都不加载它们，cv2 只在 `gfx` 调用时才 import）。
覆盖：分组解析与 box 取中心、DSL 加载与各类非法输入、steps 解析（标注名/备注/id、
歧义报错、多标注必须指名）、**坐标换算（窗口未动 = 恒等；窗口移动+缩放后仍落对位置）**、
主循环轮次与顺序、**每步只比对自己的目标图**、轮询重试、步超时、整轮超时、optional 跳过、
钩子（返回值语义、执行顺序、异常转 RunnerError、ctx 能力）、dry-run、点击重试、
计时样本入库、probe 成本记录、阈值判定。
