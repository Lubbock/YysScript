# archive/ — 旧「模板匹配 + 状态机」识别管线的归档

这里的代码**已全部停用**，不参与运行，也不被 pytest 收集（见 `archive/conftest.py`
与根目录 `pytest.ini` 的 `norecursedirs`）。保留它的唯一目的是**作为参考实现**：
新管线（`runner/`）在重构时可以随时回来抄逻辑、对照行为、或整块搬回复用。

## 为什么归档

旧管线的识别方式是「截屏 → OpenCV 模板匹配 / 颜色轮廓 → 命中状态常量 → 查坐标表点击」，
有三个结构性痛点：

1. **模板图与客户端版本强绑定**：游戏一改 UI，几十张模板全要重截；
2. **采集比例是混的**：同一张画面上 `挑战_碎片.png` 要 x1.0 才命中，`碎片打完.png`
   要 x0.4~x0.5 才有 0.99（x1.0 只有 0.27），尺度表只能放宽到 0.4；
3. **缩小匹配会撞出假命中**：模板缩到几十像素就失去判别力，在任意画面上撞出 0.9+，
   脚本照着点就是在乱点（真机踩过多次，见 git log `abe8e63`、`d46d5a8`、`bbac997`）。

新路线改成「截屏 → 本地多模态大模型判定是否同一界面 → 点标注坐标」，
不再依赖模板图，识别与点击位置都由 `similarity/dataset/` 里的分组标注数据驱动。

## 归档了什么

| 路径 | 原位置 | 内容 |
|---|---|---|
| `main.py` | `/main.py` | 旧命令行入口，注册 9 个流程（soul / explore / shard / awake / breakthrough / seal / heart / event-*） |
| `flows/` | `/flows/` | 9 个流程编排 + 事件驱动引擎（`engine.py`、`signals.py`、`bus` 订阅方 `battle_cycle` / `stage_cycle` / `rules`） |
| `states/` | `/states/` | 43 个状态常量文件（一状态一文件）+ `base.py` 注册表 + `machine.py` 状态机 |
| `vision/template_matcher.py` | `/vision/` | OpenCV 多尺度模板匹配 + NMS + 模板缓存 |
| `vision/color_detector.py` | `/vision/` | HSV 阈值 + 腐蚀膨胀 + findContours 定位会移动的怪物 |
| `vision/scales.py` | `/vision/` | 尺度策略纯计算层（绝对像素下限） |
| `actions/controller.py` | `/actions/` | 旧门面 `GameController`：把 window + viewport + mouse + matcher + detector 装在一起 |
| `tools/asset_manager/` | `/tools/` | 模板图片管理 Web 界面（截屏框选存模板、备份回滚、probe 试匹配） |
| `tests/` | `/tests/` | 上述模块的 7 个测试文件 |

### 连带归档的三个（不是可选的）

这三个如果不跟着走，留在原地会直接 import 断裂：

- `actions/controller.py` —— 它 import `vision.template_matcher` 与 `vision.color_detector`；
- `tools/asset_manager/` —— 它 `import states` 并读 `states.REGISTRY` 生成状态清单；
- 7 个测试文件 —— 它们 import `flows.*` / `states.*` / `vision.scales`。

## 刻意**没有**归档（新管线仍在用的共享基础层）

| 路径 | 新管线怎么用 |
|---|---|
| `actions/viewport.py` | 标注坐标 → 基准逻辑坐标 → 当前窗口屏幕坐标 |
| `actions/mouse.py` | 拟人化点击（抖动、随机停顿、macOS 礼貌点击与自动重试） |
| `actions/window.py` | 定位模拟器 / iOS 镜像窗口客户区，提供 region 与 window id |
| `vision/capture.py` | 截屏（按窗口区域截；截屏前由调用方 `ensure_frontmost` 把窗口提到最前） |
| `vision/types.py` | `Frame` 数据结构（`Box` / `Match` 已随模板匹配删除） |
| `core/timing.py` | 自适应等待（盲等到历史 p10 + 细粒度轮询、异常值剔除、超限回退） |
| `core/bus.py` | 事件总线（新流程可选用） |
| `core/logger.py`、`core/errors.py` | 日志与异常体系 |
| `storage/` | 耗时样本落 sqlite（`core/timing.py` 依赖它） |
| `config/settings.py`、`config/coordinates.py` | 参数；`coordinates.py` 只剩 `Point` 类型 |

> 归档管线**专属**的东西已经删掉了，复活时要一并补回来：
> `assets/templates/` 那 41 张模板图、`config/settings.py` 里的 `TEMPLATE_SCALES` /
> `MIN_SCALED_TEMPLATE_SIDE` / `DEFAULT_THRESHOLD` / `STRICT_THRESHOLD` / `MAX_MATCHES` /
> `MATCH_MERGE_DISTANCE`、`config/coordinates.py` 的界面坐标常量、`core/stopwatch.py`。
> 图片与数值都能从 git 历史取回（`git log --diff-filter=D --name-only -- assets/`、
> `git show <commit>:config/coordinates.py`），但模板图与客户端版本强绑定，
> 取回后大概率仍要按当前窗口比例重截。

## 怎么复活某一块

```bash
# 例：把状态机搬回来
git mv archive/states states
# 然后修 import，并把它需要的 vision/template_matcher.py 一并搬回
git mv archive/vision/template_matcher.py vision/
# 补回 vision/__init__.py 的 _LAZY 条目（Box / Match 也要从 vision/types.py 补回）
# 补回 settings 的阈值 / 尺度常量、coordinates 的坐标常量、core/stopwatch.py
# 模板图 assets/templates/ 从 git 历史取回后按当前窗口重截
# 对应测试文件
git mv archive/tests/test_state_machine.py tests/
```

搬回来后记得跑 `python -m pytest tests -q`，并从 `pytest.ini` 的
`norecursedirs` 里确认没有误伤（archive 仍需保留在列表里，除非整个归档区清空）。
