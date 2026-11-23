# similarity/ — 基于图像相似度的方案（隔离实验区）

与现有的模板匹配管线（`vision/template_matcher.py` + `states/` + `flows/`）**用文件夹隔离**：
主流程不 import 本目录，本目录只**只读复用**下层能力，不改动模板匹配的任何行为。

## 当前实现范围

两个页面，顶部导航互相跳转：

**A. 标注采集（`/`）—— 按分组组织**

1. **建分组**：点「＋ 新建分组」，起名（如 `御魂探索`、`麒麟`），可写一句说明；
2. **进分组**：从「当前分组」下拉里选，进去之后捕获 / 标注都只属于这个分组；
3. 点「📷 捕获截图」抓取手机模拟器 / iOS 镜像窗口画面；
4. 在图上**框选区域**或**点选位置**并打标签，保存；
5. 左侧列出**本分组**的历史截图，可随时打开继续标注；再捕获下一张，重复上述过程；
6. 换分组：下拉里选另一个（如 `麒麟`），列表与画布立刻切到那个分组的数据，互不干扰。

分组是**真实的目录隔离**，不只是筛选标签：一个分组一个独立目录，截图与标注各存各的。
另外支持分组改名 / 改说明 / 删除（连同其中截图与标注），以及把某张截图**移动**到别的
分组（标注与备注一起搬走）。首次启动会自动建一个「默认分组」，并把改造前采集的旧截图迁进去。

**B. 图片对比（`/compare`）**

1. **连点两次「📷 捕获截图」**，依次填入 A、B 两个槽位，两张图并排显示；
2. 点「🔍 对比」把两张图一起发给本地 Ollama 多模态模型判定，结果显示可信度、是否同一界面、
   两边各识别成什么、差异列表与判断依据；
3. 每个槽位可单独「重拍」，「🗑 清空」重来，「🧠 检测模型」重新探测服务。

**对比算法 = 本地大模型判定**，不用 OpenCV 做像素比对。默认调 `lfm3-omni:latest`
（`POST /api/chat`，`format: json`、`temperature: 0`），单次实测 1.3~2.8 秒。
对比页的截图落在 `dataset/compare/`，**不进标注数据集**，只保留最近 40 张。

> ⚠️ 模型必须同时支持 `completion` + `vision`。**纯 embedding 模型不行** —— 实测
> `embeddinggemma-2:740m` 的 capabilities 里虽然带 vision，但 Ollama 的 `/api/embed`
> 会**静默丢弃** `images` 字段：三张不同的图返回完全相同的向量（cosine = 1.000000），
> 且与纯文本向量一致，耗时 0.02s（根本没做视觉编码）。启动自检会把原因写进
> 页面的「模型不可用」提示里。

## 运行

```bash
pip install -r requirements.txt        # flask / opencv-python / PyAutoGUI / Pillow
ollama pull lfm3-omni                  # 多模态判定模型，约 2.4 GB
ollama serve                           # 装了 Ollama.app 的话默认已在跑
python similarity/app.py               # http://127.0.0.1:8901
```

命令行自检（不用起 web）：

```bash
python -m similarity.llm_judge              # 探测服务与模型能力
python -m similarity.llm_judge a.png b.png  # 跑一次真实对比
```

常用参数：

```bash
python similarity/app.py --port 9100                  # 换端口（被占用自动顺延）
python similarity/app.py --model qwen2.5vl:7b         # 换判定模型
python similarity/app.py --ollama-host http://127.0.0.1:11434
python similarity/app.py --threshold 0.8              # 判定同屏的最低可信度
python similarity/app.py --process "iPhone Mirroring" # macOS 目标窗口进程名
python similarity/app.py --data-dir /path/to/dataset  # 数据集目录
```

环境变量：`YYS_SIMILARITY_DATASET`、`YYS_MAC_WINDOW_PROCESS`、`YYS_OLLAMA_HOST`、
`YYS_OLLAMA_MODEL`、`YYS_OLLAMA_TIMEOUT`、`YYS_OLLAMA_KEEP_ALIVE`、`YYS_SIMILARITY_THRESHOLD`。

## 截图从哪来

复用现有代码，不重复实现：

| 来源 | 用到的模块 | 说明 |
|---|---|---|
| 目标窗口（默认） | `actions/window.py` + `vision/capture.py` | macOS 按进程名找窗口（默认 iPhone Mirroring），按窗口区域截屏；截屏前先把该窗口提到最前，避免拍到压在上面的窗口。Windows 走 `Win32WindowFinder` |
| 整屏 | 同上（`FullScreenFinder`） | 找不到窗口、或想连桌面一起截时用 |

截图尺寸 = 窗口点尺寸（Retina 会缩回点数），所以**标注坐标与点击坐标同一单位**。
窗口定位失败时接口返回 400 并给出原因（进程名写错 / 窗口最小化 / 未开镜像）。

## 页面操作（标注采集）

| 操作 | 方式 |
|---|---|
| 框选标注 | 「▭ 框选」模式（快捷键 `B`），在图上拖出一个矩形 |
| 点标注 | 「• 点标注」模式（快捷键 `P`），在图上点一下 |
| 改标签 / 微调坐标 | 右侧标注列表，标签是文本框，x/y/w/h（或 x/y）是数字框 |
| 选中 / 删除标注 | 点图上的框或右侧列表选中，`Delete` 删除 |
| 保存 | 「💾 保存标注」或 `Ctrl/Cmd + S`；未保存时切换截图会提示 |
| 1:1 显示 | 勾选后按图片原始像素显示，便于精确标注（可滚动） |
| 删除截图 | 左侧列表项右侧的 ✕（连同标注一起删，不可恢复） |
| 新建 / 切换分组 | 顶部「当前分组」下拉切换；「＋ 新建分组」弹窗填名字与说明 |
| 改名 / 改说明 | 「✎ 编辑」（弹窗会预填当前值） |
| 删除分组 | 「🗑 删除」—— 连同其中全部截图与标注，会二次确认 |
| 把截图移到别的分组 | 图下方「把当前截图移到 …」下拉 +「移动」，标注与备注一起搬走 |

标注坐标一律存**图片原始像素**，与浏览器里的显示缩放无关，所以窗口大小 / 缩放变化不影响数据。

对比页（`/compare`）的操作：

| 操作 | 方式 |
|---|---|
| 捕获 A / B | 连点两次「📷 捕获截图」，自动先填 A 再填 B（`Ctrl/Cmd + R`） |
| 重拍某一个槽位 | 该槽位右上角的「重拍」 |
| 对比 | 「🔍 对比」或 `Enter`（两张都就绪才可点） |
| 清空 | 「🗑 清空」，两个槽位一起清掉重新开始 |

## 数据格式

```
similarity/dataset/
├── groups.json                              # 分组清单（有序，入版本库）
├── groups/
│   ├── default/                             # 默认分组，key 固定为 default
│   │   ├── shots/
│   │   │   ├── 20261122-235401-503128.png   # 截图本体（不入版本库）
│   │   │   └── 20261122-235401-503128.json  # 标注 + 截图元信息（入版本库）
│   │   └── thumbs/                          # 缩略图缓存（不入版本库，可随意删）
│   └── g20261123-020913-d6fc/               # 「御魂探索」，key 自动生成
│       ├── shots/…
│       └── thumbs/…
└── compare/                                 # 对比页临时截图（不属于任何分组，只留最近 40 张）
```

JSON 结构：

```json
{
  "id": "20261122-235401-503128",
  "image": "20261122-235401-503128.png",
  "group": "default",
  "captured_at": "2026-11-22 23:54:01",
  "updated_at": "2026-11-22 23:59:01",
  "source": "window",
  "width": 690,
  "height": 356,
  "origin": [32, 277],
  "region": [32, 277, 690, 356],
  "window_id": 267290,
  "process": "iPhone Mirroring",
  "note": "第十八章章节界面",
  "annotations": [
    {"id": "a638myi4w", "kind": "box",   "label": "挑战按钮", "box":   {"x": 138, "y": 107, "w": 173, "h": 107}},
    {"id": "aifodws3c", "kind": "point", "label": "头像",     "point": {"x": 483, "y": 89}}
  ]
}
```

字段说明：`group` 是所属分组的 key（与所在目录一致，冗余存一份便于单文件自解释）；
`origin` / `region` / `window_id` 记录了截图当时窗口在屏幕上的位置，以后要把标注坐标换算成
屏幕点击坐标时直接用得上；`source=fullscreen` 时 `region` 是整屏。

`groups.json` 结构（分组顺序即页面下拉顺序）：

```json
{"groups": [{"key": "default", "name": "默认分组", "description": "…",
             "created_at": "2026-11-23 02:08:20", "updated_at": "2026-11-23 02:08:20"}]}
```

分组 `key` 是自动生成的 ASCII 短 id（默认分组固定为 `default`），`name` 才是你看到的中文名 ——
这样改名不会动目录、也不会让 URL 里出现中文。名字在数据集内唯一。

> 截图 PNG 与缩略图被 `dataset/.gitignore` 排除（体积大、属于本地采集数据），
> 标注 JSON 保留在版本库里，方便 review 标签体系。要把图片也纳入版本管理，删掉那个 `.gitignore` 即可。

## 接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/info` | 数据集目录、截屏能力、默认进程名、全局统计、模型可用性 |
| GET | `/api/groups` | 分组列表（含各组截图数 / 标注数 / 目录路径） |
| POST | `/api/groups` | 新建分组，body `{"name": "御魂探索", "description": "…"}` |
| GET | `/api/groups/<key>` | 单个分组详情 |
| PATCH | `/api/groups/<key>` | 改名 / 改说明（两个字段都可只传一个） |
| DELETE | `/api/groups/<key>` | 删除分组连同其中全部截图与标注 |
| GET | `/api/groups/<key>/shots` | 该分组的截图列表（按时间倒序） |
| POST | `/api/groups/<key>/capture` | 截图并存进该分组，body `{"source": "window"\|"fullscreen", "process": "…"}` |
| GET | `/api/groups/<key>/shots/<id>` | 单张截图的完整元信息 + 标注 |
| PUT | `/api/groups/<key>/shots/<id>/annotations` | 整体替换标注，body `{"annotations": […], "note": "…"}` |
| POST | `/api/groups/<key>/shots/<id>/move` | 移到别的分组，body `{"to": "<key>"}` |
| DELETE | `/api/groups/<key>/shots/<id>` | 删除截图与标注 |
| GET | `/shots/<key>/<id>.png` / `.thumb.jpg` | 原图 / 缩略图 |
| GET | `/compare` | 图片对比页面 |
| POST | `/api/compare/capture` | 对比页截图，落 `dataset/compare/`，**不进标注数据集** |
| POST | `/api/compare` | 比较两张图，body `{"a": "<id>", "b": "<id>"}`；调模型判定 |
| GET | `/api/model` | 强制重新探测 Ollama 服务与模型能力 |
| GET | `/compare-img/<id>.png` | 对比页截图本体 |

标注在服务端会做校验：`kind` 只接受 `box` / `point`，坐标必须是图片范围内的整数，
非法 `id` 会被重新分配，路径穿越一律拦截。

`/api/compare` 返回：

```json
{
  "matched": true,
  "score": 0.99,
  "method": "ollama:lfm3-omni:latest",
  "message": "模型判定为同一界面（可信度 99%）：两图内容完全一致…",
  "elapsed_ms": 2806.9,
  "details": {
    "same_screen": true, "similarity": 0.99, "confidence": 0.99,
    "a_summary": "…", "b_summary": "…", "differences": ["…"], "reason": "…",
    "threshold": 0.6, "inconsistent": false, "truncated": false, "elapsed_ms": 2806.1
  }
}
```

`score` 就是前端显示的**可信度**（取模型的 `similarity`）。
`matched = same_screen AND score >= threshold`，阈值默认 0.6。
两者矛盾时 `inconsistent=true`，页面弹黄条提示人工复核。

## 换模型 / 调阈值 / 换算法

- **换模型**：`--model` 或 `YYS_OLLAMA_MODEL`。必须同时支持 `completion` + `vision`，
  启动自检会拦住纯 embedding 模型和无视觉的模型并说明原因。
- **调阈值**：`--threshold` 或 `YYS_SIMILARITY_THRESHOLD`。
- **改提示词**：`similarity/llm_judge.py` 的 `PROMPT`。字段名别改，前端与解析都依赖它。
- **换整套算法**：给 `create_app(comparer=my_func)` 传一个
  `(path_a, path_b) -> dict` 的函数即可，接口与前端都不用动
  （见 `tests/test_similarity_annotator.py::test_compare_uses_injected_comparer`）。

健壮性已经处理掉的坑：模型输出被 `num_predict` 截断（按字段抢救 + `truncated` 标记）、
JSON 前后夹带解释文字（`raw_decode`）、代码块围栏、数值越界（夹到 0~1）、
`same_screen` 返回字符串而非布尔、服务没起 / 模型不存在 / 超时（转 503 + 可操作的提示）。

### 实测标定（真机 iPhone 镜像截图）

用 5 张真实截图组成 6 对，拿 OpenCV 直方图相关性当参考真值：

| 图对 | 模型判定 | 可信度 | 参考真值（直方图相关 / 平均像素差） |
|---|---|---|---|
| img1-img2 | 同一界面 | 0.99 | 0.996 / 2.2 |
| img3-img4 | 同一界面 | 0.99 | 1.000 / 1.7 |
| img1-img3 | 同一界面 | 0.99 | 0.857 / 22.8 |
| img1-img4 | 同一界面 | 0.99 | 0.855 / 22.3 |
| img0-img1 | 不同界面 | 0.05 | 0.100 / 91.0 |
| img0-img3 | 不同界面 | 0.05 | -0.001 / 109.9 |

**6/6 判定正确**，A/B 顺序反转结论一致。单次耗时 1.3~2.8 秒。

⚠️ 一个已知局限：模型的 `similarity` **只分得开两档**（同屏 0.99、不同屏 0.05），
中间地带（如 0.85 那两对）也给 0.99。所以它适合回答「是不是同一个界面」，
**不适合当连续的相似度度量**。要细粒度分数得换算法（见上面的 `comparer` 注入点）。

## 文件

| 文件 | 职责 |
|---|---|
| `capture.py` | 截屏：定位窗口 → 抓图 → PNG 编码；依赖缺失 / 窗口找不到时给出可读错误 |
| `store.py` | 数据集读写：`Dataset`（分组清单 / 迁移 / 跨组移动）、`ShotStore`（单组截图与标注校验）、`CompareStore`（对比页临时图）。纯标准库，可独立单测 |
| `llm_judge.py` | **对比算法主体**：Ollama 客户端、提示词、输出解析与容错、服务自检、CLI |
| `compare.py` | 薄封装：`compare_images(a, b, judge=None)` → 契约 dict |
| `app.py` | Flask 页面与接口，`create_app()` 可注入数据集目录、假截屏、假 judge、假 comparer |
| `static/` | 原生 JS 页面，无构建步骤：`index.html` + `app.js`（标注采集）、`compare.html` + `compare.js`（图片对比） |

## 测试

```bash
python -m pytest tests/test_similarity_annotator.py -q
```

用假的截屏函数注入，**不真截屏、不需要 cv2 / pyautogui**，覆盖存储与接口契约。

## 安全

默认只绑 `127.0.0.1`。该服务能往数据集目录写文件，需要远程访问请用 SSH 隧道：

```bash
ssh -L 8901:127.0.0.1:8901 <游戏机>
```
