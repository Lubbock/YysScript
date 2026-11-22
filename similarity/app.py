#!/usr/bin/env python3
"""相似度方案的数据采集界面。

两个页面：
- `/`         标注采集（按分组）：捕获截图 -> 框选 / 点选标注 -> 存进当前分组
- `/compare`  图片对比：两次捕获填 A / B -> 调本地 Ollama 多模态模型判定

数据落在 `similarity/dataset/`，分组结构见 `store.Dataset`。

安全：默认只绑 127.0.0.1（服务可写数据集目录）。远程访问用 SSH 隧道：
    ssh -L 8901:127.0.0.1:8901 <游戏机>

运行：
    python similarity/app.py                    # http://127.0.0.1:8901
    python similarity/app.py --port 9100 --model lfm3-omni:latest
"""
from __future__ import annotations

import argparse
import io
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, abort, jsonify, request, send_from_directory  # noqa: E402

from similarity import capture as capture_mod  # noqa: E402
from similarity.llm_judge import JudgeError, OmniJudge, default_judge  # noqa: E402
from similarity.store import (  # noqa: E402
    DEFAULT_DATASET,
    Dataset,
    GroupNotFound,
    ShotNotFound,
    ShotStore,
    StoreError,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
THUMB_SIDE = 220
MODEL_CACHE_TTL = 30.0

Grabber = Callable[..., capture_mod.Shot]


def send_thumbnail(store: ShotStore, shot_id: str, side: int = THUMB_SIDE):
    """生成并返回缩略图。"""
    try:
        store.check_id(shot_id)
    except StoreError as exc:
        abort(400, description=str(exc))
    source = store.image_path(shot_id)
    if not source.is_file():
        abort(404)
    thumb = store.thumb_path(shot_id)
    if not thumb.is_file() or thumb.stat().st_mtime < source.stat().st_mtime:
        try:
            from PIL import Image

            store.thumbs_dir.mkdir(parents=True, exist_ok=True)
            with Image.open(source) as image:
                image.thumbnail((side, side))
                buffer = io.BytesIO()
                image.convert("RGB").save(buffer, format="JPEG", quality=80)
            thumb.write_bytes(buffer.getvalue())
        except Exception:
            return send_from_directory(store.shots_dir, source.name)
    response = send_from_directory(store.thumbs_dir, thumb.name)
    response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


def create_app(
    dataset_dir: Optional[Path] = None,
    grabber: Optional[Grabber] = None,
    comparer: Optional[Callable[[Path, Path], Dict[str, Any]]] = None,
    judge: Optional[OmniJudge] = None,
    process: Optional[str] = None,
) -> Flask:
    """组装 Flask 应用。"""
    root = Path(dataset_dir or os.environ.get("YYS_SIMILARITY_DATASET") or DEFAULT_DATASET)
    dataset = Dataset(root)
    migrated = dataset.ensure()
    compare_store = dataset.compare_store
    grab = grabber or capture_mod.grab
    judge_obj = judge or default_judge()
    compare = comparer or judge_obj.compare
    compare_name = (
        "{}:{}".format(getattr(comparer, "__module__", "?"), getattr(comparer, "__name__", "?"))
        if comparer is not None else "ollama:{}".format(judge_obj.model)
    )
    default_process = process or capture_mod.default_process()
    model_cache: Dict[str, Any] = {"at": None, "info": None}

    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
    app.config["MIGRATED"] = migrated

    def group_store(key: str) -> ShotStore:
        """取分组仓库，分组不存在转 404。"""
        try:
            dataset.get_group(key)
        except GroupNotFound as exc:
            abort(404, description=str(exc))
        except StoreError as exc:
            abort(400, description=str(exc))
        return dataset.shots(key)

    def grab_shot(payload: Dict[str, Any]) -> capture_mod.Shot:
        """按请求参数截一张图。"""
        source = payload.get("source") or "window"
        process_name = (payload.get("process") or "").strip() or (
            default_process if source == "window" else None
        )
        probe = capture_mod.capability()
        if not probe["ok"]:
            abort(503, description="当前环境无法截屏：{}".format("; ".join(probe["errors"])))
        try:
            return grab(source=source, process=process_name)
        except (StoreError, capture_mod.CaptureError) as exc:
            abort(400, description=str(exc))
        except Exception as exc:
            abort(500, description="截屏失败 {}: {}".format(type(exc).__name__, exc))

    def model_health(force: bool = False) -> Dict[str, Any]:
        """模型可用性，带缓存。"""
        now = time.monotonic()
        stale = model_cache["at"] is None or now - model_cache["at"] > MODEL_CACHE_TTL
        if force or stale:
            try:
                model_cache["info"] = judge_obj.health()
            except Exception as exc:
                model_cache["info"] = {
                    "ok": False, "host": judge_obj.host, "model": judge_obj.model,
                    "error": "{}: {}".format(type(exc).__name__, exc),
                }
            model_cache["at"] = now
        return model_cache["info"]

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/static/<path:filename>")
    def static_files(filename):
        return send_from_directory(STATIC_DIR, filename)

    @app.get("/compare")
    def compare_page():
        return send_from_directory(STATIC_DIR, "compare.html")

    @app.get("/shots/<group_key>/<shot_id>.png")
    def shot_image(group_key: str, shot_id: str):
        store = group_store(group_key)
        try:
            store.check_id(shot_id)
        except StoreError as exc:
            abort(400, description=str(exc))
        if not store.image_path(shot_id).is_file():
            abort(404)
        response = send_from_directory(store.shots_dir, "{}.png".format(shot_id))
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response

    @app.get("/shots/<group_key>/<shot_id>.thumb.jpg")
    def shot_thumb(group_key: str, shot_id: str):
        return send_thumbnail(group_store(group_key), shot_id)

    @app.get("/compare-img/<image_id>.png")
    def compare_image(image_id: str):
        try:
            compare_store.check_id(image_id)
        except StoreError as exc:
            abort(400, description=str(exc))
        if not compare_store.image_path(image_id).is_file():
            abort(404)
        response = send_from_directory(compare_store.root, "{}.png".format(image_id))
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response

    @app.get("/api/info")
    def api_info():
        probe = capture_mod.capability()
        return jsonify({
            "dataset_dir": str(dataset.root),
            "default_process": default_process,
            "sources": list(capture_mod.SOURCES),
            "capture": probe["ok"],
            "capture_error": "; ".join(probe["errors"]),
            "platform": probe["platform"],
            "stats": dataset.stats(),
            "compare_dir": str(compare_store.root),
            "compare_method": compare_name,
            "threshold": judge_obj.threshold,
            "model": model_health(),
        })

    @app.get("/api/model")
    def api_model():
        """重新探测模型服务。"""
        return jsonify(model_health(force=True))

    @app.get("/api/groups")
    def api_groups():
        return jsonify(dataset.list_groups())

    @app.post("/api/groups")
    def api_create_group():
        payload = request.get_json(silent=True) or {}
        try:
            group = dataset.create_group(payload.get("name"), payload.get("description", ""))
        except StoreError as exc:
            abort(400, description=str(exc))
        return jsonify(group)

    @app.get("/api/groups/<group_key>")
    def api_group(group_key: str):
        try:
            return jsonify(dataset.present_group(dataset.get_group(group_key)))
        except GroupNotFound as exc:
            abort(404, description=str(exc))
        except StoreError as exc:
            abort(400, description=str(exc))

    @app.patch("/api/groups/<group_key>")
    def api_update_group(group_key: str):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400, description="请求体必须是 JSON 对象")
        try:
            group = dataset.update_group(
                group_key, payload.get("name"), payload.get("description"))
        except GroupNotFound as exc:
            abort(404, description=str(exc))
        except StoreError as exc:
            abort(400, description=str(exc))
        return jsonify(group)

    @app.delete("/api/groups/<group_key>")
    def api_delete_group(group_key: str):
        try:
            removed = dataset.delete_group(group_key)
        except GroupNotFound as exc:
            abort(404, description=str(exc))
        except StoreError as exc:
            abort(400, description=str(exc))
        return jsonify({"ok": True, "deleted": removed["key"], "name": removed["name"]})

    @app.get("/api/groups/<group_key>/shots")
    def api_shots(group_key: str):
        return jsonify(group_store(group_key).list_shots())

    @app.post("/api/groups/<group_key>/capture")
    def api_capture(group_key: str):
        """截图并存进指定分组。"""
        store = group_store(group_key)
        shot = grab_shot(request.get_json(silent=True) or {})
        meta = dict(shot.meta())
        meta["group"] = group_key
        return jsonify(store.save_shot(shot.png, meta))

    @app.get("/api/groups/<group_key>/shots/<shot_id>")
    def api_shot(group_key: str, shot_id: str):
        try:
            return jsonify(group_store(group_key).get(shot_id))
        except ShotNotFound as exc:
            abort(404, description=str(exc))
        except StoreError as exc:
            abort(400, description=str(exc))

    @app.put("/api/groups/<group_key>/shots/<shot_id>/annotations")
    def api_save_annotations(group_key: str, shot_id: str):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400, description="请求体必须是 JSON 对象")
        try:
            record = group_store(group_key).save_annotations(
                shot_id, payload.get("annotations"), payload.get("note"))
        except ShotNotFound as exc:
            abort(404, description=str(exc))
        except StoreError as exc:
            abort(400, description=str(exc))
        return jsonify(record)

    @app.post("/api/groups/<group_key>/shots/<shot_id>/move")
    def api_move_shot(group_key: str, shot_id: str):
        """把截图搬到另一个分组。body: {"to": "<group_key>"}"""
        payload = request.get_json(silent=True) or {}
        try:
            dataset.get_group(group_key)
            dataset.get_group(payload.get("to"))
            record = dataset.move_shot(shot_id, group_key, payload.get("to"))
        except (GroupNotFound, ShotNotFound) as exc:
            abort(404, description=str(exc))
        except StoreError as exc:
            abort(400, description=str(exc))
        return jsonify(record)

    @app.delete("/api/groups/<group_key>/shots/<shot_id>")
    def api_delete_shot(group_key: str, shot_id: str):
        store = group_store(group_key)
        try:
            store.get(shot_id)
        except ShotNotFound as exc:
            abort(404, description=str(exc))
        except StoreError as exc:
            abort(400, description=str(exc))
        store.delete(shot_id)
        return jsonify({"ok": True, "id": shot_id, "group": group_key})

    @app.post("/api/compare/capture")
    def api_compare_capture():
        """对比页截图，不属于任何分组。"""
        shot = grab_shot(request.get_json(silent=True) or {})
        return jsonify(compare_store.save(shot.png, shot.meta()))

    @app.post("/api/compare")
    def api_compare():
        """比较两张已捕获的图片。"""
        payload = request.get_json(silent=True) or {}
        paths = {}
        for slot in ("a", "b"):
            image_id = payload.get(slot)
            try:
                compare_store.check_id(image_id)
            except StoreError as exc:
                abort(400, description="槽位 {}: {}".format(slot, exc))
            path = compare_store.image_path(image_id)
            if not path.is_file():
                abort(404, description="槽位 {} 的图片不存在或已被清理: {}".format(slot, image_id))
            paths[slot] = path

        started = time.monotonic()
        try:
            result = compare(paths["a"], paths["b"])
        except JudgeError as exc:
            abort(503, description="模型判定失败：{}".format(exc))
        except Exception as exc:
            abort(500, description="对比失败 {}: {}".format(type(exc).__name__, exc))
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)

        if not isinstance(result, dict):
            abort(500, description="对比函数必须返回 dict，实际是 {}".format(type(result).__name__))
        body = dict(result)
        body.setdefault("matched", False)
        body["a"] = payload.get("a")
        body["b"] = payload.get("b")
        body["elapsed_ms"] = elapsed_ms
        return jsonify(body)

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(405)
    @app.errorhandler(500)
    @app.errorhandler(503)
    def json_error(exc):
        code = getattr(exc, "code", 500)
        return jsonify({"ok": False, "error": getattr(exc, "description", str(exc))}), code

    return app


def pick_port(host: str, preferred: int, tries: int = 20) -> int:
    """找一个可用端口。"""
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
    parser = argparse.ArgumentParser(description="相似度方案：分组标注采集 + 图片对比界面")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8901)
    parser.add_argument("--data-dir", default=None, help="数据集目录，默认 similarity/dataset")
    parser.add_argument("--process", default=None, help="macOS 目标窗口进程名")
    parser.add_argument("--ollama-host", default=None, help="Ollama 地址，默认 127.0.0.1:11434")
    parser.add_argument("--model", default=None, help="多模态模型名，默认 lfm3-omni:latest")
    parser.add_argument("--threshold", type=float, default=None, help="判定同屏的最低可信度")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    dataset_dir = Path(args.data_dir or os.environ.get("YYS_SIMILARITY_DATASET") or DEFAULT_DATASET)
    judge = None
    if args.ollama_host or args.model or args.threshold is not None:
        judge = OmniJudge(host=args.ollama_host, model=args.model, threshold=args.threshold)
    port = pick_port(args.host, args.port)
    app = create_app(dataset_dir=dataset_dir, judge=judge, process=args.process)
    active_judge = judge or default_judge()

    if args.host not in {"127.0.0.1", "localhost"}:
        print("⚠️  正在监听 {}：该服务可写数据集目录，请勿暴露公网。".format(args.host))
    dataset = Dataset(dataset_dir)
    print("数据集目录 : {}".format(dataset.root))
    print("分组数量   : {}{}".format(
        len(dataset.list_groups()),
        "（已把 {} 个旧文件迁进默认分组）".format(app.config["MIGRATED"])
        if app.config["MIGRATED"] else ""))
    for group in dataset.list_groups():
        print("  - {} [{}] {} 张截图 / {} 个标注".format(
            group["name"], group["key"], group["shots"], group["annotations"]))
    probe = capture_mod.capability()
    print("截屏能力   : {}{}".format(
        "可用" if probe["ok"] else "不可用",
        "" if probe["ok"] else "（{}）".format("; ".join(probe["errors"]))))
    info = active_judge.health()
    print("模型服务   : {}  版本 {}".format(info["host"], info["version"]))
    print("判定模型   : {}  能力={}".format(
        info["model"], ", ".join(info["capabilities"]) or "无"))
    print("模型可用   : {}{}".format(
        "是" if info["ok"] else "否", "" if info["ok"] else "（{}）".format(info["error"])))
    print("判定阈值   : {}".format(active_judge.threshold))
    if port != args.port:
        print("端口提示   : {} 已被占用，改用 {}".format(args.port, port))
    print("\n打开 http://{}:{}".format(args.host, port))

    app.run(host=args.host, port=port, debug=args.debug, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
