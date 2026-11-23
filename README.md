# YysScript

《阴阳师》客户端自动化脚本。不读内存、不调游戏接口，纯视觉方案：

```
截屏 → 本地多模态大模型判定「当前是不是这一屏」 → 换算坐标 → 拟人化点击
```

玩法顺序不写在代码里，而是每个分组自带一份 Python DSL（`flow.py`）声明；
主循环按 DSL 逐步推进，跑完最后一步回到第一步。

> ⚠️ 自动化脚本违反《阴阳师》用户协议，有封号风险。本仓库仅作图像识别与桌面自动化的技术学习用途。

## 快速开始

```bash
pip install -r requirements.txt
ollama pull lfm3-omni:latest          # 判定模型，必须同时具备 completion + vision

# 1) 采集：新建分组 → 截屏 → 在图上框选/点选标注 → 保存
python similarity/app.py              # http://127.0.0.1:8901，只绑本机

# 2) 生成并调整 DSL
python main.py --list                 # 全部分组（截图数 / 标注数 / 有没有 DSL）
python main.py --group 御魂十一 --init-dsl
python main.py --group 御魂十一 --show      # 打印每步的截图、标注、坐标、超时

# 3) 跑
python main.py --group 御魂十一 --dry-run   # 只解析，不截屏不点击
python main.py --group 御魂十一 --times 10  # 跑 10 轮；不给 --times 就无限循环
```

常用开关：`--debug`（含每次判定的理由与差异）、`--no-adaptive-wait`、`--continue-on-error`、
`--round-timeout`、`--model` / `--threshold`、`--no-humanize`、`--data-dir`。

退出码：`0` 正常 / `1` 运行异常（截屏与点击失败）/ `2` 参数、分组或 DSL 错误 /
`130` 用户中断 / `300` 体力耗尽。

## DSL 长什么样

分组目录下的 `flow.py`，文件里**不需要任何 import**：

```python
name = "御魂十一"
round_timeout = 600

steps = [
    step("挑战", timeout=90),      # 等到「挑战」这张图 → 点它的标注
    step("完成", timeout=300),     # 战斗打完 → 点结算
]

def on_step_timeout(ctx, st):
    """超时兜底：返回 True 表示已自愈，继续下一步。"""
    return False
```

`target` 用标注名 / 截图备注 / 截图 id 指认界面，点击位置来自标注，不写在代码里。
复杂处理写钩子（`on_step_matched` / `on_step_timeout` / `on_round_*` / `before_run` / `after_run`），
钩子拿到 `ctx`：截屏、比图、点任意标注、读写跨轮变量、图形算法 `ctx.gfx`。

⚠️ 不要在 DSL 里写 `blind_wait`，它会永久覆盖自适应等待算出来的值。

## 工作原理

1. `similarity/` 产出数据集：分组截图 + 像素标注，判定用本地 Ollama 多模态模型（不做 OpenCV 模板匹配）；
2. `runner/` 读分组与 DSL，每步**只和当前那一张图比**（顺序已由 DSL 声明，不必遍历全组）；
3. `actions/` 定位窗口 → `Viewport` 把标注像素经「截图时的窗口」归一成逻辑坐标，再按「当前窗口」放大成屏幕坐标 → `HumanMouse` 拟人化点击。窗口挪过、改过大小都仍然点得准；
4. `core/timing.py` 记录每步 / 每轮真实耗时（落 `var/gray_scan.db`），攒够 5 个样本后先盲等到接近历史 p10，再按 1 秒细轮询。

真机实测（macOS + iPhone Mirroring，御魂十一）：单轮约 66 秒，一次判定 1.3~3.3 秒。

## macOS / iPhone 镜像

`pip install pyobjc-framework-Quartz pyobjc-framework-Cocoa`，打开「iPhone 镜像」并保持不最小化。
点击会短暂激活镜像窗口、随即把光标与焦点还给你原来的应用，轮询期间完全不碰鼠标。

- 截屏走**区域截屏**（macOS 15+ 的 `CGWindowListCreateImage` 已被移除，调用要白等 30 秒才返回 NULL），
  所以**跑之前把镜像窗口露出来**，被其它窗口挡住会拍到遮挡物；
- 显示器休眠或手机锁屏时合成点击送不到目标窗口，挂机前关掉自动休眠，或 `caffeinate -di python main.py ...`。

## 目录结构

```
config/      全局参数 + Point 坐标类型 + runner 超时/间隔常量
core/        日志、异常、计时、事件总线、自适应等待
storage/     sqlite 持久化（耗时样本）
actions/     找窗口 → Viewport 坐标换算 → HumanMouse 拟人化点击
vision/      截屏（Frame / Box / ScreenCapture）
similarity/  标注采集 Web 界面 + 双图对比 + Ollama 判定；数据集 dataset/groups/<key>/，每组自带 flow.py
runner/      当前主线：读分组 → 加载 DSL → 主循环 → 单图判定 → 换算坐标并点击
tests/       单元测试（不依赖 cv2 / pyautogui / 模型，不截屏不点击）
archive/     归档的旧模板匹配管线（states/ flows/ 模板匹配等），不参与运行与测试
var/         运行时产物（日志、gray_scan.db、调试图），不进版本库
main.py      命令行入口
AGENTS.md    目录职责与开发约定（改代码前先读）
```

依赖方向：`main → runner → similarity / actions → vision / storage / core / config`，不允许反向依赖。
职责边界、三套坐标语义、常见改动落点见 **[AGENTS.md](AGENTS.md)**。

## 测试

```bash
python -m pytest tests -q
```

224 个用例，全部离线：分组解析与 DSL 加载校验、坐标换算的精确像素断言、主循环与超时、
钩子语义、自适应等待、标注页与对比页的 API 契约、模型客户端的 JSON 抢救与自检门禁。
`archive/` 已被 `pytest.ini` 与 `archive/conftest.py` 排除收集。

## 为什么换了识别方式

旧的「OpenCV 多尺度模板匹配 + 状态机」管线整体归档在 `archive/`。它有两个绕不过去的坑：
模板图与客户端版本、采集比例强绑定（游戏一改 UI 就要重截几十张），而缩小匹配会在任意画面上
撞出 0.9+ 的假命中，脚本照着点就是乱点。新路线把识别交给多模态模型，只需要「截图 + 标注」，
维护成本从「维护模板库」降为「重新截一组图」。旧的时序常量与误命中矩阵仍记录在
AGENTS.md 末尾，写新 DSL 时可以对照。
