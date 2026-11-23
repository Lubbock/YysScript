#!/usr/bin/env python3
"""模板图片管理界面（项目维护工具）。

解决的实际问题：游戏更新 UI 后模板图失效，需要重新截图替换（AGENTS.md 已知限制 #2）。
比「外部截图工具 + 手动裁剪 + 覆盖文件」方便的地方在于：

1. 一屏看到全部状态和它的模板缩略图，缺失 / 未引用直接标出来；
2. **截屏 → 浏览器里框选 → 直接存成新模板**，不用离开页面；
3. 替换前自动备份，可一键回滚；
4. 显示每个模板被哪些流程引用，换图前知道影响范围；
5. probe：拿当前屏幕试匹配某个模板，直接看分数和框，用来调阈值。

安全：默认只绑 127.0.0.1。这个服务能往 assets/ 写文件，绝对不要暴露到公网；
需要远程访问请用 SSH 隧道：ssh -L 8899:127.0.0.1:8899 <游戏机>

运行：
    python tools/asset_manager/app.py            # http://127.0.0.1:8899
    python tools/asset_manager/app.py --port 9000
"""
from __future__ import annotations

import argparse
import ast
import io
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# 允许从任意目录直接运行
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, abort, jsonify, request, send_from_directory  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import states  # noqa: E402  导入即触发全部状态自动注册
from config import settings  # noqa: E402
from states.base import StateKind, all_states  # noqa: E402

# --------------------------------------------------------------------------- #
# 可选依赖探测：截屏 / 模板匹配只在装了对应库时可用，缺失时前端禁用相应按钮
# --------------------------------------------------------------------------- #
try:
    import pyautogui

    HAS_CAPTURE = True
    CAPTURE_ERROR = ""
except Exception as exc:  # 取决于运行环境
    pyautogui = None
    HAS_CAPTURE = False
    CAPTURE_ERROR = "{}: {}".format(type(exc).__name__, exc)

try:
    import cv2
    import numpy as np

    HAS_MATCH = True
    MATCH_ERROR = ""
except Exception as exc:
    cv2 = None
    np = None
    HAS_MATCH = False
    MATCH_ERROR = "{}: {}".format(type(exc).__name__, exc)

TEMPLATE_DIR: Path = settings.TEMPLATE_DIR.resolve()
BACKUP_ROOT: Path = (settings.VAR_DIR / "backups" / "templates").resolve()
CAPTURE_DIR: Path = (settings.VAR_DIR / "captures").resolve()
STATIC_DIR = Path(__file__).resolve().parent / "static"

#: 只保留最近 N 张截图，避免 var/ 无限膨胀
MAX_CAPTURES = 20

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def safe_name(name: str) -> str:
    """校验模板文件名，阻断路径穿越。"""
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        abort(400, description="非法文件名: {!r}".format(name))
    if Path(name).suffix.lower() != ".png":
        abort(400, description="只接受 .png，收到: {}".format(name))
    if (TEMPLATE_DIR / name).resolve().parent != TEMPLATE_DIR:
        abort(400, description="路径越界: {!r}".format(name))
    return name


def image_meta(path: Path) -> Dict:
    """读取图片元信息；不存在或损坏时返回 exists/valid=False。"""
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    meta = {
        "exists": True,
        "bytes": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        with Image.open(path) as im:
            meta["width"], meta["height"] = im.size
            meta["mode"] = im.mode
            meta["valid"] = True
    except Exception as exc:
        meta["valid"] = False
        meta["error"] = str(exc)
    return meta


def backup(name: str) -> Optional[str]:
    """把现有模板备份到 var/backups/templates/<时间戳>/，返回备份目录名。"""
    source = TEMPLATE_DIR / name
    if not source.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target_dir = BACKUP_ROOT / stamp
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target_dir / name)
    return stamp


def atomic_write_png(path: Path, data: bytes) -> None:
    """校验是合法 PNG 后原子写入（先写 .tmp 再 replace，避免半截文件）。"""
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
    except Exception as exc:
        abort(400, description="不是合法的 PNG 图片: {}".format(exc))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _states_imported_by(py: Path) -> List[str]:
    """AST 扫描某个流程文件 import 了哪些状态常量。

    用 AST 而不是 import：flows 依赖 pyautogui，本机可能没装。
    """
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return []
    found: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not node.module.startswith("states."):
            continue
        if node.module in {"states.base", "states.machine"}:
            continue
        for alias in node.names:
            if alias.name not in found:
                found.append(alias.name)
    return sorted(found)


def flow_catalog() -> List[Dict]:
    """权威流程清单 -> 各自引用的状态。

    以 flows/registry.py 为准（该模块只依赖 typing，可安全导入），
    因此像 soul 这种纯定时、不引用任何状态的流程也会出现在列表里，
    而不是因为「没有状态」被静默丢掉。
    """
    from flows.registry import FLOW_SPECS

    catalog = []
    for name, spec in sorted(FLOW_SPECS.items()):
        module_path, _class_name, description = spec
        py = PROJECT_ROOT / (module_path.replace(".", "/") + ".py")
        catalog.append({
            "name": name,
            "description": description,
            "states": _states_imported_by(py) if py.is_file() else [],
        })
    return catalog


def flow_usage() -> Dict[str, List[str]]:
    """状态 key -> [流程名]，供状态卡片显示 used_by。"""
    usage: Dict[str, List[str]] = {}
    for flow in flow_catalog():
        for key in flow["states"]:
            usage.setdefault(key, []).append(flow["name"])
    return usage


def state_payload(usage: Dict[str, List[str]]) -> List[Dict]:
    """前端状态卡片所需的全部数据。"""
    payload = []
    for state in all_states():
        payload.append({
            "key": state.key,
            "label": state.label,
            "kind": state.kind.value,
            "threshold": state.threshold,
            "description": state.description,
            "used_by": usage.get(state.key, []),
            "templates": [dict(name=t, **image_meta(TEMPLATE_DIR / t)) for t in state.templates],
        })
    return payload


def prune_captures() -> None:
    """只保留最近 MAX_CAPTURES 张截图。"""
    if not CAPTURE_DIR.exists():
        return
    ordered = sorted(CAPTURE_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in ordered[MAX_CAPTURES:]:
        try:
            path.unlink()
        except OSError:
            pass


def window_region() -> Optional[tuple]:
    """尝试定位游戏窗口客户区；失败抛异常由调用方处理。"""
    from actions.window import GameWindow

    return GameWindow().refresh().region


# --------------------------------------------------------------------------- #
# 页面与静态资源
# --------------------------------------------------------------------------- #
@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


@app.get("/img/<path:name>")
def serve_template(name):
    """模板图片本体。no-store 保证换图后前端立刻看到新图。"""
    safe_name(name)
    if not (TEMPLATE_DIR / name).exists():
        abort(404)
    response = send_from_directory(TEMPLATE_DIR, name)
    response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


@app.get("/cap/<path:name>")
def serve_capture(name):
    safe_name(name)
    if not (CAPTURE_DIR / name).exists():
        abort(404)
    response = send_from_directory(CAPTURE_DIR, name)
    response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


def safe_stamp(stamp: str) -> str:
    """校验备份时间戳目录名，阻断路径穿越。"""
    if not stamp or stamp in {".", ".."} or "/" in stamp or "\\" in stamp:
        abort(400, description="非法备份标识: {!r}".format(stamp))
    if (BACKUP_ROOT / stamp).resolve().parent != BACKUP_ROOT:
        abort(400, description="备份路径越界: {!r}".format(stamp))
    return stamp


@app.get("/backup-img/<stamp>/<path:name>")
def serve_backup_image(stamp, name):
    """备份版本的图片本体，供备份列表显示真实缩略图（而不是当前文件）。"""
    safe_stamp(stamp)
    safe_name(name)
    directory = BACKUP_ROOT / stamp
    if not (directory / name).is_file():
        abort(404)
    response = send_from_directory(directory, name)
    response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(503)
def json_error(exc):
    return jsonify({"ok": False, "error": getattr(exc, "description", str(exc))}), exc.code


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.get("/api/info")
def api_info():
    used = {t for s in all_states() for t in s.templates}
    on_disk = {p.name for p in TEMPLATE_DIR.glob("*.png")}
    return jsonify({
        "template_dir": str(TEMPLATE_DIR),
        "backup_dir": str(BACKUP_ROOT),
        "capture_dir": str(CAPTURE_DIR),
        "base_client_size": list(settings.BASE_CLIENT_SIZE),
        "default_threshold": settings.DEFAULT_THRESHOLD,
        "counts": {
            "states": len(states.REGISTRY),
            "screen": len(all_states(StateKind.SCREEN)),
            "marker": len(all_states(StateKind.MARKER)),
            "templates_on_disk": len(on_disk),
            "missing": sorted(used - on_disk),
            "orphans": sorted(on_disk - used),
        },
        "capabilities": {
            "capture": HAS_CAPTURE,
            "capture_error": CAPTURE_ERROR,
            "match": bool(HAS_MATCH and HAS_CAPTURE),
            "match_error": MATCH_ERROR or CAPTURE_ERROR,
        },
    })


@app.get("/api/states")
def api_states():
    return jsonify(state_payload(flow_usage()))


@app.get("/api/flows")
def api_flows():
    """权威流程清单（含各自引用的状态），供前端按流程过滤。"""
    return jsonify(flow_catalog())


@app.post("/api/template/<path:name>")
def api_replace_template(name):
    """替换模板图片（自动备份）。form-data 字段名 file。"""
    safe_name(name)
    upload = request.files.get("file")
    if upload is None:
        abort(400, description="缺少 file 字段（multipart/form-data）")
    data = upload.read()
    if not data:
        abort(400, description="上传内容为空")

    path = TEMPLATE_DIR / name
    old = image_meta(path)
    stamp = backup(name)
    atomic_write_png(path, data)
    new = image_meta(path)

    warning = None
    if old.get("valid") and new.get("valid"):
        dw = abs(new["width"] - old["width"]) / max(old["width"], 1)
        dh = abs(new["height"] - old["height"]) / max(old["height"], 1)
        if dw > 0.3 or dh > 0.3:
            warning = ("尺寸变化较大：{}x{} → {}x{}。模板尺寸直接决定匹配框大小与点击中心，"
                       "截多了或只截了一部分都会导致识别不准。").format(
                old["width"], old["height"], new["width"], new["height"])
    return jsonify({"ok": True, "name": name, "backup": stamp,
                    "old": old, "new": new, "warning": warning})


@app.get("/api/template/<path:name>/backups")
def api_list_backups(name):
    safe_name(name)
    if not BACKUP_ROOT.exists():
        return jsonify([])
    found = []
    for stamp_dir in sorted(BACKUP_ROOT.iterdir(), reverse=True):
        candidate = stamp_dir / name
        if candidate.is_file():
            found.append(dict(stamp=stamp_dir.name, **image_meta(candidate)))
    return jsonify(found)


@app.post("/api/template/<path:name>/rollback")
def api_rollback(name):
    """从某个备份恢复。body: {"stamp": "20261117-221530-123456"}"""
    safe_name(name)
    stamp = (request.get_json(silent=True) or {}).get("stamp", "")
    if not stamp or "/" in stamp or "\\" in stamp or stamp in {".", ".."}:
        abort(400, description="非法备份标识")
    source = BACKUP_ROOT / stamp / name
    if not source.is_file():
        abort(404, description="备份不存在: {}".format(stamp))
    # 回滚前也备份当前版本，让回滚本身可撤销
    backup(name)
    atomic_write_png(TEMPLATE_DIR / name, source.read_bytes())
    return jsonify({"ok": True, "name": name, "restored_from": stamp,
                    "meta": image_meta(TEMPLATE_DIR / name)})


@app.post("/api/capture")
def api_capture():
    """截当前屏幕存到 var/captures/。body: {"region": "full"|"window"}"""
    if not HAS_CAPTURE:
        abort(503, description="当前环境无法截屏（{}）。请在装了 pyautogui 的游戏机上运行本服务。".format(CAPTURE_ERROR))
    payload = request.get_json(silent=True) or {}

    region = None
    if payload.get("region") == "window":
        try:
            region = window_region()
        except Exception as exc:
            return jsonify({"ok": False, "error": "定位游戏窗口失败：{}".format(exc)}), 400

    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    name = "cap_{}.png".format(datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    shot = pyautogui.screenshot(region=region)
    shot.save(CAPTURE_DIR / name)
    prune_captures()
    return jsonify({"ok": True, "name": name, "url": "/cap/{}".format(name),
                    "width": shot.width, "height": shot.height,
                    "region": list(region) if region else None})


@app.post("/api/crop")
def api_crop():
    """从已有截图或模板上裁一块，存成目标模板（自动备份目标）。

    body: {"source": "capture"|"template", "name": "cap_xxx.png",
           "x": 0, "y": 0, "w": 100, "h": 40, "target": "首页.png"}
    """
    payload = request.get_json(silent=True) or {}
    target = safe_name(payload.get("target", ""))
    src_name = payload.get("name", "")
    if not src_name or "/" in src_name or "\\" in src_name or src_name in {".", ".."}:
        abort(400, description="非法源文件名")

    base = (CAPTURE_DIR if payload.get("source") == "capture" else TEMPLATE_DIR).resolve()
    src_path = (base / src_name).resolve()
    if src_path.parent != base or not src_path.is_file():
        abort(404, description="源图片不存在: {}".format(src_name))

    try:
        x, y, w, h = int(payload["x"]), int(payload["y"]), int(payload["w"]), int(payload["h"])
    except (KeyError, TypeError, ValueError):
        abort(400, description="裁剪区域参数缺失或非法")
    if w < 4 or h < 4:
        abort(400, description="裁剪区域太小（至少 4x4），当前 {}x{}".format(w, h))

    with Image.open(src_path) as im:
        if x < 0 or y < 0 or x + w > im.width or y + h > im.height:
            abort(400, description="裁剪区域超出图片范围（图片 {}x{}）".format(im.width, im.height))
        buffer = io.BytesIO()
        im.crop((x, y, x + w, y + h)).convert("RGB").save(buffer, format="PNG")

    stamp = backup(target)
    atomic_write_png(TEMPLATE_DIR / target, buffer.getvalue())
    return jsonify({"ok": True, "target": target, "backup": stamp, "size": [w, h],
                    "meta": image_meta(TEMPLATE_DIR / target)})


@app.post("/api/probe")
def api_probe():
    """用当前屏幕试匹配一个模板，返回分数、框和标注图。用来调阈值 / 验证新图。

    body: {"name": "首页.png", "threshold": 0.7, "region": "full"|"window"}
    """
    if not (HAS_MATCH and HAS_CAPTURE):
        abort(503, description="probe 需要 cv2 + pyautogui（cv2: {} / 截屏: {}）".format(
            MATCH_ERROR or "ok", CAPTURE_ERROR or "ok"))

    payload = request.get_json(silent=True) or {}
    probe_name = safe_name(payload.get("name", ""))
    threshold = float(payload.get("threshold") or settings.DEFAULT_THRESHOLD)

    region = None
    if payload.get("region") == "window":
        try:
            region = window_region()
        except Exception as exc:
            return jsonify({"ok": False, "error": "定位游戏窗口失败：{}".format(exc)}), 400

    shot = pyautogui.screenshot(region=region)
    origin = (region[0], region[1]) if region else (0, 0)
    screen = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2GRAY)
    template = cv2.imread(str(TEMPLATE_DIR / probe_name), cv2.IMREAD_GRAYSCALE)
    if template is None:
        abort(404, description="模板读取失败: {}".format(probe_name))
    th, tw = template.shape[:2]

    if th > screen.shape[0] or tw > screen.shape[1]:
        return jsonify({"ok": True, "matched": [], "total_matches": 0, "best_score": 0.0,
                        "threshold": threshold,
                        "note": "模板（{}x{}）比截图（{}x{}）还大，无法匹配".format(
                            tw, th, screen.shape[1], screen.shape[0])})

    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(result >= threshold)
    boxes = [{"x": origin[0] + int(x), "y": origin[1] + int(y), "w": tw, "h": th,
              "score": round(float(result[y, x]), 4)} for x, y in zip(xs, ys)]
    boxes.sort(key=lambda b: b["score"], reverse=True)

    # 全场最高分（不论是否过阈值）——用来判断「差多少」，比只知道没命中有用
    _, max_score, _, max_loc = cv2.minMaxLoc(result)

    annotated = shot.copy()
    draw = ImageDraw.Draw(annotated)
    for index, box in enumerate(boxes[:30], 1):
        x0, y0 = box["x"] - origin[0], box["y"] - origin[1]
        draw.rectangle([x0, y0, x0 + tw, y0 + th], outline=(255, 40, 40), width=2)
        draw.text((x0 + 3, y0 + 3), "{} {:.3f}".format(index, box["score"]), fill=(255, 255, 0))
    # 未达阈值时把最高分位置画成蓝框，方便看「它以为最像的地方在哪」
    if not boxes:
        draw.rectangle([max_loc[0], max_loc[1], max_loc[0] + tw, max_loc[1] + th],
                       outline=(60, 140, 255), width=2)
        draw.text((max_loc[0] + 3, max_loc[1] + 3), "best {:.3f}".format(max_score),
                  fill=(120, 200, 255))

    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    shot_name = "probe_{}.png".format(datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    annotated.save(CAPTURE_DIR / shot_name)
    prune_captures()

    return jsonify({"ok": True, "matched": boxes[:30], "total_matches": len(boxes),
                    "best_score": round(float(max_score), 4),
                    "best_location": [origin[0] + int(max_loc[0]), origin[1] + int(max_loc[1])],
                    "threshold": threshold, "annotated_url": "/cap/{}".format(shot_name),
                    "region": list(region) if region else None})


def pick_port(host: str, preferred: int, tries: int = 20) -> int:
    """从 preferred 开始找一个能绑定的端口。

    开发机上端口撞车很常见，撞车时 Flask 直接抛 OSError 退出、报错也不直观，
    所以先探测再启动，被占用就向后顺延。
    """
    import socket

    for offset in range(tries):
        port = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
        return port
    raise SystemExit("在 {} 上找不到可用端口（从 {} 起试了 {} 个）".format(host, preferred, tries))


def main() -> int:
    parser = argparse.ArgumentParser(description="YysScript 模板图片管理界面")
    parser.add_argument("--host", default="127.0.0.1",
                        help="监听地址，默认 127.0.0.1（本服务可写 assets/，勿暴露公网）")
    parser.add_argument("--port", type=int, default=8899,
                        help="起始端口，被占用时自动向后顺延（默认 8899）")
    parser.add_argument("--debug", action="store_true", help="Flask 调试模式（自动重载）")
    args = parser.parse_args()

    port = pick_port(args.host, args.port)

    if args.host not in {"127.0.0.1", "localhost"}:
        print("⚠️  正在监听 {}：该服务可以覆盖 assets/templates 下的图片。".format(args.host))
        print("    远程访问请改用 SSH 隧道：ssh -L {p}:127.0.0.1:{p} <游戏机>".format(p=port))

    print("模板目录 : {}".format(TEMPLATE_DIR))
    print("备份目录 : {}".format(BACKUP_ROOT))
    print("截屏目录 : {}".format(CAPTURE_DIR))
    print("截屏能力 : {}{}".format("可用" if HAS_CAPTURE else "不可用",
                                 "" if HAS_CAPTURE else "（{}）".format(CAPTURE_ERROR)))
    print("匹配能力 : {}{}".format("可用" if (HAS_MATCH and HAS_CAPTURE) else "不可用",
                                 "" if (HAS_MATCH and HAS_CAPTURE)
                                 else "（{}）".format(MATCH_ERROR or CAPTURE_ERROR)))
    print("状态数量 : {}（界面 {} / 标记 {}）".format(
        len(states.REGISTRY), len(all_states(StateKind.SCREEN)), len(all_states(StateKind.MARKER))))
    if port != args.port:
        print("端口提示 : {} 已被占用，改用 {}".format(args.port, port))
    print("\n打开 http://{}:{}".format(args.host, port))

    app.run(host=args.host, port=port, debug=args.debug, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
