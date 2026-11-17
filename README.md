# YysScript

《阴阳师》PC 客户端自动化脚本。纯视觉方案：截屏 → OpenCV 图像识别 → 判断界面状态 → 换算坐标 → 拟人化点击。

已实现功能：自动探索、自动御魂、自动觉醒、自动结界突破、自动妖气封印、自动御心道场、限时活动事件循环。

> ⚠️ 自动化脚本违反《阴阳师》用户协议，有封号风险。本仓库仅作图像识别 / 桌面自动化的技术学习用途。

## 快速开始

```bash
pip install -r requirements.txt      # Windows + Python 3.8+

python main.py --check               # 自检：模板图片是否齐全、能否定位游戏窗口
python main.py --list                # 列出全部功能
python main.py --states              # 列出全部状态常量与阈值

python main.py explore --times 10    # 自动探索 10 轮
python main.py soul --times 30       # 自动御魂 30 次
python main.py awake --dungeon 4 --times 20
python main.py breakthrough --times 3
python main.py seal --times 50
python main.py heart --times 10
```

常用开关：`--fullscreen`（整屏当客户区）、`--align-window`（把窗口挪到左上角）、
`--no-humanize`（关闭随机抖动）、`--exp-only`（探索只打经验怪）、`--debug`。

退出码：`0` 正常 / `1` 流程异常 / `2` 参数缺失 / `130` 用户中断 / `300` 体力耗尽。

## 工作原理

1. `vision` 截取游戏窗口画面；
2. `cv2.matchTemplate` 与 `assets/templates/` 里的按钮截图比对，判断「当前在哪个界面」；
   地图上会移动的怪物改用 HSV 颜色阈值 + 腐蚀膨胀 + `findContours`，比模板匹配快很多；
3. `states` 把每张模板封装成具名状态常量，`StateMachine` 负责等待 / 轮询 / 多候选判定；
4. `actions` 找到游戏窗口客户区，把「基准 1024×768 逻辑坐标」按窗口实际位置和大小换算成屏幕坐标，
   再用带随机抖动与停顿的鼠标动作点击 —— 所以换分辨率、窗口不在屏幕原点也能工作；
5. `flows` 把状态串成完整玩法流程，一个功能一个子文件夹。

## 目录结构

```
config/     全局参数 + 唯一的坐标表（settings.py / coordinates.py）
core/       日志、异常、计时与耗时预测
vision/     图像识别：截屏、模板匹配、颜色轮廓检测
storage/    sqlite 持久化（动作耗时样本，用于预测等待时间）
states/     状态机：一个状态一个文件，全部定义成常量
actions/    操作层：找窗口 → 坐标换算 → 拟人化点击
flows/      功能编排：explore / soul / awake / breakthrough / seal / heart_dojo / events
assets/     模板图片（assets/templates/*.png）
tests/      单元测试（不依赖 cv2 / pyautogui，不截屏不点击）
tools/      维护工具（模板图片管理 Web 界面）+ 周边归档（语音、远控、Flask demo 等）
var/        运行时产物（日志、gray_scan.db）
main.py     命令行入口
AGENTS.md   目录职责与开发约定（改代码前先读）
```

分层依赖：`main → flows → states / actions / vision / storage / core / config`，不允许反向依赖。
详细的职责边界、坐标语义约定、常见改动落点见 **[AGENTS.md](AGENTS.md)**。

## 模板图片管理界面

游戏更新 UI 后模板图会失效，这是最常见的维护动作。用内置的 Web 界面换图，
不用外部截图工具 + 手动裁剪 + 覆盖文件：

```bash
python tools/asset_manager/app.py     # 打开 http://127.0.0.1:8899（端口被占会自动顺延）
```

能做什么：

- **状态卡片网格**：34 个状态的缩略图、阈值、尺寸，以及被哪些流程引用（换图前先看影响范围）；
  缺失的模板标红，磁盘上没被任何状态引用的图片单独列出；
- **截屏 → 框选 → 存成新模板**：把游戏切到目标界面，点「📷 截屏裁剪新模板」，
  在图上拖一个框，选目标状态，保存。支持 2× 放大便于框小图标；
- **拖拽上传替换**：也可以直接把本地 PNG 拖进状态详情里替换；
- **自动备份 + 一键回滚**：每次替换/裁剪前把旧图存到 `var/backups/templates/<时间戳>/`，
  换错了当场回滚（长期历史仍靠 git）；尺寸突变会给出警告；
- **probe 识别测试**：拿当前屏幕试匹配某个模板，直接看**匹配分数、命中框、标注图**。
  分数远低于阈值 = 模板该换了；只差一点 = 可以把阈值调低。这是调阈值最快的方式。

顶栏会显示当前环境的截屏 / 匹配能力：这两个功能需要 `pyautogui` + `opencv-python`，
所以请在**装了游戏客户端的那台机器上**运行本服务；缺依赖时按钮自动禁用并说明原因。

> ⚠️ 该服务默认只绑 `127.0.0.1`。它能覆盖 `assets/templates/` 下的文件，不要暴露到公网；
> 远程访问用 SSH 隧道：`ssh -L 8899:127.0.0.1:8899 <游戏机>`。

## 测试

```bash
python -m pytest tests -q
```

覆盖：坐标换算与缩放、坐标迁移一致性、状态注册表完整性（含模板文件是否存在）、
状态机等待/超时/多候选逻辑、sqlite 存取与裁剪。

## 自定义

| 想改什么 | 改哪里 |
|---|---|
| 按钮点不准 | `config/coordinates.py` |
| 识别不到界面 | 用模板管理界面 probe 看分数，再决定是调 `states/*.py` 的 `threshold` 还是重截模板 |
| 点击太快太规律 | `config/settings.py` 的 `HUMAN_*` 参数 |
| 日志 / 数据库位置 | 环境变量 `YYS_LOG_DIR`、`YYS_DB_PATH`、`YYS_TEMPLATE_DIR` |
| 加一个新玩法 | `flows/` 下新建子目录，并在 `flows/registry.py` 注册 |

## 与旧版本的差异

原仓库是 `scripts/` + `utils/` 的平铺脚本，坐标按 1024×768 屏幕写死、模板路径写死成
`E:/github/YysScript/`、依赖清单是 macOS 的 conda 导出（缺 opencv/pyautogui/pywin32）。
重构后：路径与坐标全部配置化并支持环境变量覆盖，坐标经窗口换算实现分辨率无关，
依赖清单重写，异常替代 `exit(300)`，并补齐可离线运行的单元测试。
迁移过程中顺带修掉的旧 bug：探索扫怪循环被无条件 `break` 提前终止、结界突破九宫格索引算错行、
`SqlScan.clear_kw(500)` 缺参数、日志 handler 重复注册、`cv2.imshow` 打断脚本、
定位失败时把 `None` 传给 `click`。
