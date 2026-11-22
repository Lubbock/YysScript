"""相似度采集工具（similarity/）的存储与 API 契约测试。

不截屏、不依赖 cv2 / pyautogui：截屏函数用假的 grabber 注入。
重点锁定前端 app.js 依赖的 JSON 字段与标注校验规则。
"""
import io
import json
from pathlib import Path

import pytest
from PIL import Image

flask = pytest.importorskip("flask", reason="采集工具需要 flask")

from similarity import capture as capture_mod
from similarity.app import create_app
from similarity.llm_judge import JudgeError, OmniJudge, salvage_json
from similarity.store import ShotStore, StoreError


def make_png(width=40, height=60, color=(12, 130, 200)):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def fake_grab(width=40, height=60):
    def grab(source="window", process=None):
        if source not in capture_mod.SOURCES:
            raise capture_mod.CaptureError(
                "未知截图来源: {!r}（可选 {}）".format(source, " / ".join(capture_mod.SOURCES)))
        return capture_mod.Shot(
            png=make_png(width, height),
            width=width,
            height=height,
            source=source,
            origin=(100, 50),
            region=(100, 50, width, height),
            window_id=4242,
            process=process or "Fake Mirroring",
        )
    return grab


MATCH_VERDICT = {
    "matched": True,
    "score": 0.99,
    "method": "ollama:fake-omni:latest",
    "message": "模型判定为同一界面（可信度 99%）",
    "details": {
        "same_screen": True, "similarity": 0.99, "confidence": 0.99,
        "a_summary": "物品选择界面", "b_summary": "物品选择界面",
        "differences": [], "reason": "元素一致", "model": "fake-omni:latest",
        "elapsed_ms": 2100.0, "truncated": False, "threshold": 0.6,
        "inconsistent": False,
    },
}


class FakeJudge:
    """假模型客户端，不发网络请求。"""

    def __init__(self, verdict=None, error=None):
        self.model = "fake-omni:latest"
        self.host = "http://fake:11434"
        self.threshold = 0.6
        self.verdict = verdict or dict(MATCH_VERDICT)
        self.error = error
        self.calls = []
        self.health_calls = 0

    def health(self):
        self.health_calls += 1
        return {
            "ok": self.error is None, "host": self.host, "model": self.model,
            "version": "9.9.9", "reachable": True, "found": True,
            "vision": self.error is None,
            "capabilities": ["completion", "vision"], "error": self.error or "",
        }

    def compare(self, image_a, image_b):
        self.calls.append((Path(image_a).name, Path(image_b).name))
        if self.error:
            raise JudgeError(self.error)
        return dict(self.verdict)


@pytest.fixture()
def judge():
    return FakeJudge()


@pytest.fixture()
def client(tmp_path, monkeypatch, judge):
    monkeypatch.setattr(capture_mod, "capability",
                        lambda: {"ok": True, "errors": [], "platform": "test"})
    app = create_app(dataset_dir=tmp_path / "dataset", grabber=fake_grab(), judge=judge)
    app.testing = True
    return app.test_client()


@pytest.fixture()
def store(tmp_path):
    return ShotStore(tmp_path / "store")


def capture(client, source="window"):
    response = client.post("/api/groups/default/capture",
                           json={"source": source, "process": "Fake Mirroring"})
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def test_capture_saves_png_and_meta(client, tmp_path):
    shot = capture(client)

    for field in ("id", "image", "image_url", "captured_at", "width", "height",
                  "source", "region", "window_id", "process", "annotations",
                  "annotation_count", "note"):
        assert field in shot, "缺少前端依赖的字段 {}".format(field)
    assert (shot["width"], shot["height"]) == (40, 60)
    assert shot["source"] == "window"
    assert shot["annotations"] == []

    image = tmp_path / "dataset" / "groups" / "default" / "shots" / shot["image"]
    meta = image.with_suffix(".json")
    assert image.is_file() and meta.is_file()
    assert json.loads(meta.read_text(encoding="utf-8"))["window_id"] == 4242

    body = client.get(shot["image_url"])
    assert body.status_code == 200
    assert body.data == make_png()


def test_capture_fullscreen_source(client):
    response = client.post("/api/groups/default/capture", json={"source": "fullscreen"})
    assert response.status_code == 200
    assert response.get_json()["source"] == "fullscreen"


def test_capture_rejects_unknown_source(client):
    response = client.post("/api/groups/default/capture", json={"source": "adb"})
    assert response.status_code == 400
    assert "未知截图来源" in response.get_json()["error"]


def test_capture_reports_window_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_mod, "capability",
                        lambda: {"ok": True, "errors": [], "platform": "test"})

    def boom(source="window", process=None):
        raise capture_mod.CaptureError("定位目标窗口失败（进程 'X'）")

    app = create_app(dataset_dir=tmp_path / "err", grabber=boom)
    app.testing = True
    response = app.test_client().post("/api/groups/default/capture", json={"source": "window"})
    assert response.status_code == 400
    assert "定位目标窗口失败" in response.get_json()["error"]


def test_capture_without_dependencies(client, monkeypatch):
    monkeypatch.setattr(capture_mod, "capability",
                        lambda: {"ok": False, "errors": ["cv2: ImportError: x"], "platform": "darwin"})
    response = client.post("/api/groups/default/capture", json={"source": "window"})
    assert response.status_code == 503
    assert "无法截屏" in response.get_json()["error"]


def test_info_exposes_dataset_and_stats(client):
    capture(client)
    info = client.get("/api/info").get_json()
    assert info["capture"] is True
    assert info["sources"] == ["window", "fullscreen"]
    assert info["stats"]["shots"] == 1
    assert "dataset" in info["dataset_dir"]


def test_shot_list_is_newest_first(client):
    first = capture(client)
    second = capture(client)
    shots = client.get("/api/groups/default/shots").get_json()
    assert [item["id"] for item in shots] == [second["id"], first["id"]]


def test_save_and_reload_annotations(client):
    shot = capture(client)
    payload = {
        "annotations": [
            {"kind": "box", "label": "挑战按钮", "box": {"x": 4, "y": 6, "w": 20, "h": 12}},
            {"kind": "point", "label": "头像中心", "point": {"x": 9, "y": 11}},
        ],
        "note": "第十八章章节界面",
    }
    response = client.put(
        "/api/groups/default/shots/{}/annotations".format(shot["id"]), json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)
    saved = response.get_json()
    assert saved["annotation_count"] == 2
    assert saved["note"] == "第十八章章节界面"
    assert all(item["id"] for item in saved["annotations"])

    again = client.get("/api/groups/default/shots/{}".format(shot["id"])).get_json()
    assert again["annotations"][0]["box"] == {"x": 4, "y": 6, "w": 20, "h": 12}
    assert again["annotations"][1]["point"] == {"x": 9, "y": 11}
    assert again["updated_at"]

    listed = client.get("/api/groups/default/shots").get_json()[0]
    assert listed["annotation_count"] == 2
    labels = client.get("/api/info").get_json()["stats"]["labels"]
    assert set(labels) == {"挑战按钮", "头像中心"}


def test_annotation_out_of_range_rejected(client):
    shot = capture(client)
    url = "/api/groups/default/shots/{}/annotations".format(shot["id"])

    too_wide = client.put(url, json={
        "annotations": [{"kind": "box", "label": "x", "box": {"x": 30, "y": 0, "w": 50, "h": 10}}],
    })
    assert too_wide.status_code == 400
    assert "超出" in too_wide.get_json()["error"]

    overflow = client.put(url, json={
        "annotations": [{"kind": "box", "label": "x", "box": {"x": 35, "y": 0, "w": 10, "h": 10}}],
    })
    assert overflow.status_code == 400
    assert "超出图片范围" in overflow.get_json()["error"]


def test_annotation_bad_kind_rejected(client):
    shot = capture(client)
    response = client.put("/api/groups/default/shots/{}/annotations".format(shot["id"]), json={
        "annotations": [{"kind": "polygon", "label": "x"}],
    })
    assert response.status_code == 400
    assert "kind 非法" in response.get_json()["error"]


def test_save_annotations_unknown_shot(client):
    response = client.put("/api/groups/default/shots/20200101-000000-000000/annotations",
                          json={"annotations": []})
    assert response.status_code == 404


def test_invalid_shot_id_rejected(client):
    assert client.get("/api/groups/default/shots/../../etc").status_code in (400, 404)
    response = client.get("/api/groups/default/shots/not-an-id")
    assert response.status_code == 400
    assert "非法截图 id" in response.get_json()["error"]


def test_delete_shot_removes_files(client, tmp_path):
    shot = capture(client)
    image = tmp_path / "dataset" / "groups" / "default" / "shots" / shot["image"]
    assert client.delete(
        "/api/groups/default/shots/{}".format(shot["id"])).status_code == 200
    assert not image.exists()
    assert not image.with_suffix(".json").exists()
    assert client.get("/api/groups/default/shots").get_json() == []
    assert client.delete(
        "/api/groups/default/shots/{}".format(shot["id"])).status_code == 404


def test_thumbnail_endpoint(client):
    shot = capture(client)
    response = client.get("/shots/default/{}.thumb.jpg".format(shot["id"]))
    assert response.status_code == 200
    assert len(response.data) > 0
    with Image.open(io.BytesIO(response.data)) as thumb:
        assert max(thumb.size) <= 220


def test_static_page_and_assets(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "捕获截图".encode() in page.data
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_store_clean_annotations_assigns_unique_ids(store):
    cleaned = store.clean_annotations([
        {"kind": "box", "label": "a", "box": {"x": 0, "y": 0, "w": 5, "h": 5}},
        {"kind": "box", "label": "b", "box": {"x": 0, "y": 0, "w": 5, "h": 5}},
    ], 40, 60)
    ids = [item["id"] for item in cleaned]
    assert len(set(ids)) == 2


def test_store_rejects_bad_payload(store):
    with pytest.raises(StoreError):
        store.clean_annotations({"kind": "box"}, 40, 60)
    with pytest.raises(StoreError):
        store.clean_annotations([{"kind": "box", "box": {"x": "a", "y": 0, "w": 5, "h": 5}}], 40, 60)
    with pytest.raises(StoreError):
        store.clean_annotations([{"kind": "point", "point": {"x": 0, "y": 999}}], 40, 60)


def test_store_rejects_bad_shot_id(store):
    with pytest.raises(StoreError):
        store.image_path("../secrets")
    with pytest.raises(StoreError):
        store.image_path("a/b")


def compare_capture(client):
    response = client.post("/api/compare/capture",
                           json={"source": "window", "process": "Fake Mirroring"})
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def test_compare_page_and_assets(client):
    page = client.get("/compare")
    assert page.status_code == 200
    assert "对比".encode() in page.data
    assert client.get("/static/compare.js").status_code == 200
    index = client.get("/").get_data(as_text=True)
    assert "/compare" in index


def test_info_exposes_compare_fields(client, judge):
    info = client.get("/api/info").get_json()
    assert info["compare_dir"].endswith("compare")
    assert info["compare_method"] == "ollama:fake-omni:latest"
    assert info["threshold"] == 0.6
    assert info["model"]["ok"] is True
    assert info["model"]["version"] == "9.9.9"
    assert info["model"]["vision"] is True
    assert judge.health_calls >= 1


def test_compare_capture_keeps_dataset_clean(client, tmp_path):
    first = compare_capture(client)
    second = compare_capture(client)

    assert first["id"] != second["id"]
    for shot in (first, second):
        assert shot["image_url"].startswith("/compare-img/")
        assert shot["width"] == 40 and shot["height"] == 60
        assert client.get(shot["image_url"]).status_code == 200

    compare_dir = tmp_path / "dataset" / "compare"
    assert len(list(compare_dir.glob("*.png"))) == 2
    assert client.get("/api/groups/default/shots").get_json() == []
    assert client.get("/api/info").get_json()["stats"]["shots"] == 0


def test_compare_returns_model_verdict(client, judge):
    first = compare_capture(client)
    second = compare_capture(client)

    response = client.post("/api/compare", json={"a": first["id"], "b": second["id"]})
    assert response.status_code == 200, response.get_data(as_text=True)
    result = response.get_json()

    assert result["matched"] is True
    assert result["score"] == 0.99
    assert result["method"] == "ollama:fake-omni:latest"
    assert result["a"] == first["id"] and result["b"] == second["id"]
    assert isinstance(result["elapsed_ms"], float)
    assert result["message"]
    for field in ("same_screen", "similarity", "confidence", "a_summary",
                  "b_summary", "differences", "reason", "threshold"):
        assert field in result["details"], "前端依赖字段缺失: {}".format(field)
    assert judge.calls == [(first["id"] + ".png", second["id"] + ".png")]


def test_compare_negative_verdict(client, judge):
    judge.verdict = dict(MATCH_VERDICT, matched=False, score=0.05,
                         message="模型判定不是同一界面（相似度 5%）")
    first = compare_capture(client)
    second = compare_capture(client)

    response = client.post("/api/compare", json={"a": first["id"], "b": second["id"]})
    assert response.status_code == 200
    result = response.get_json()
    assert result["matched"] is False and result["score"] == 0.05


def test_compare_reports_model_failure_as_503(client, judge):
    judge.error = "连不上 Ollama（http://fake:11434）：Connection refused"
    first = compare_capture(client)
    second = compare_capture(client)

    response = client.post("/api/compare", json={"a": first["id"], "b": second["id"]})
    assert response.status_code == 503
    assert "连不上 Ollama" in response.get_json()["error"]


def test_info_reports_model_unavailable(client, judge):
    judge.error = "模型 foo 不存在"
    info = client.get("/api/info").get_json()
    assert info["model"]["ok"] is False
    assert info["model"]["error"] == "模型 foo 不存在"
    assert client.get("/api/model").get_json()["ok"] is False


def test_compare_requires_both_slots(client):
    first = compare_capture(client)
    response = client.post("/api/compare", json={"a": first["id"]})
    assert response.status_code == 400
    assert "槽位 b" in response.get_json()["error"]


def test_compare_unknown_image(client):
    first = compare_capture(client)
    response = client.post("/api/compare", json={
        "a": first["id"], "b": "c20200101-000000-000000"})
    assert response.status_code == 404
    assert "不存在" in response.get_json()["error"]


def test_compare_rejects_bad_image_id(client):
    for bad in ("../secrets", "not-an-id", ""):
        response = client.post("/api/compare", json={"a": bad, "b": bad})
        assert response.status_code == 400
        assert "非法对比图 id" in response.get_json()["error"]


def test_compare_serves_image_only_by_valid_id(client):
    assert client.get("/compare-img/nope.png").status_code == 400
    assert client.get("/compare-img/c20200101-000000-000000.png").status_code == 404


def test_compare_uses_injected_comparer(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_mod, "capability",
                        lambda: {"ok": True, "errors": [], "platform": "test"})
    seen = []

    def real_compare(image_a, image_b):
        seen.append((image_a.name, image_b.name))
        return {"matched": False, "score": 0.31, "method": "real-algo", "message": "不一样"}

    app = create_app(dataset_dir=tmp_path / "cmp", grabber=fake_grab(), comparer=real_compare)
    app.testing = True
    client = app.test_client()

    first = compare_capture(client)
    second = compare_capture(client)
    result = client.post("/api/compare", json={"a": first["id"], "b": second["id"]}).get_json()

    assert result["matched"] is False and result["score"] == 0.31
    assert result["method"] == "real-algo"
    assert seen == [(first["id"] + ".png", second["id"] + ".png")]
    assert all((tmp_path / "cmp" / "compare" / name).is_file() for name in seen[0])


def test_compare_reports_broken_comparer(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_mod, "capability",
                        lambda: {"ok": True, "errors": [], "platform": "test"})

    def boom(image_a, image_b):
        raise ValueError("算法炸了")

    app = create_app(dataset_dir=tmp_path / "cmp2", grabber=fake_grab(), comparer=boom)
    app.testing = True
    client = app.test_client()
    first = compare_capture(client)
    second = compare_capture(client)

    response = client.post("/api/compare", json={"a": first["id"], "b": second["id"]})
    assert response.status_code == 500
    assert "算法炸了" in response.get_json()["error"]


def test_compare_rejects_non_dict_comparer(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_mod, "capability",
                        lambda: {"ok": True, "errors": [], "platform": "test"})
    app = create_app(dataset_dir=tmp_path / "cmp3", grabber=fake_grab(),
                     comparer=lambda a, b: True)
    app.testing = True
    client = app.test_client()
    first = compare_capture(client)
    second = compare_capture(client)

    response = client.post("/api/compare", json={"a": first["id"], "b": second["id"]})
    assert response.status_code == 500
    assert "必须返回 dict" in response.get_json()["error"]


def test_compare_capture_without_dependencies(client, monkeypatch):
    monkeypatch.setattr(capture_mod, "capability",
                        lambda: {"ok": False, "errors": ["pyautogui: ImportError: x"],
                                 "platform": "test"})
    response = client.post("/api/compare/capture", json={"source": "window"})
    assert response.status_code == 503


def canned_judge(content, done_reason="stop", threshold=0.6, stub_encode=True):
    """构造把网络请求换成固定返回的 OmniJudge。"""
    judge = OmniJudge(host="http://fake:11434", model="fake-omni:latest",
                      timeout=5, threshold=threshold)
    judge._request = lambda path, payload=None: {
        "message": {"role": "assistant", "content": content},
        "done_reason": done_reason,
    }
    if stub_encode:
        judge._encode = lambda path: "ZmFrZQ=="
    return judge


GOOD_JSON = json.dumps({
    "same_screen": True, "similarity": 0.97, "confidence": 0.93,
    "a_summary": "物品选择界面", "b_summary": "物品选择界面",
    "differences": ["时间显示不同"], "reason": "元素一致",
}, ensure_ascii=False)


def test_judge_parses_model_json(tmp_path):
    judge = canned_judge(GOOD_JSON)
    verdict = judge.judge(tmp_path / "a.png", tmp_path / "b.png")
    assert verdict["same_screen"] is True
    assert verdict["similarity"] == 0.97 and verdict["confidence"] == 0.93
    assert verdict["differences"] == ["时间显示不同"]
    assert verdict["truncated"] is False
    assert verdict["model"] == "fake-omni:latest"
    assert isinstance(verdict["elapsed_ms"], float)


def test_judge_strips_code_fence(tmp_path):
    judge = canned_judge("```json\n" + GOOD_JSON + "\n```")
    assert judge.judge(tmp_path / "a", tmp_path / "b")["similarity"] == 0.97


def test_judge_salvages_truncated_output(tmp_path):
    broken = '{"same_screen": false, "similarity": 0.12, "confidence": 0.8, "reason": "布局完全不'
    verdict = canned_judge(broken).judge(tmp_path / "a", tmp_path / "b")
    assert verdict["same_screen"] is False
    assert verdict["similarity"] == 0.12
    assert verdict["truncated"] is True


def test_judge_clamps_out_of_range_numbers(tmp_path):
    payload = json.dumps({"same_screen": True, "similarity": 1.7, "confidence": -0.3})
    verdict = canned_judge(payload).judge(tmp_path / "a", tmp_path / "b")
    assert verdict["similarity"] == 1.0
    assert verdict["confidence"] == 0.0


def test_judge_falls_back_to_confidence(tmp_path):
    payload = json.dumps({"same_screen": "true", "confidence": 0.42})
    verdict = canned_judge(payload).judge(tmp_path / "a", tmp_path / "b")
    assert verdict["same_screen"] is True
    assert verdict["similarity"] == 0.42


def test_judge_rejects_unparsable_output(tmp_path):
    with pytest.raises(JudgeError):
        canned_judge("这不是 JSON").judge(tmp_path / "a", tmp_path / "b")


def test_judge_rejects_empty_content(tmp_path):
    with pytest.raises(JudgeError):
        canned_judge("", done_reason="length").judge(tmp_path / "a", tmp_path / "b")


def test_compare_applies_threshold(tmp_path):
    payload = json.dumps({"same_screen": True, "similarity": 0.55, "confidence": 0.9})
    result = canned_judge(payload, threshold=0.6).compare(tmp_path / "a", tmp_path / "b")
    assert result["matched"] is False
    assert result["score"] == 0.55
    assert result["method"] == "ollama:fake-omni:latest"
    assert result["details"]["inconsistent"] is True
    assert "低于阈值" in result["message"]

    payload = json.dumps({"same_screen": True, "similarity": 0.99, "confidence": 0.9})
    ok = canned_judge(payload, threshold=0.6).compare(tmp_path / "a", tmp_path / "b")
    assert ok["matched"] is True and ok["details"]["inconsistent"] is False


def test_compare_negative_marks_mismatch(tmp_path):
    payload = json.dumps({"same_screen": False, "similarity": 0.05, "confidence": 0.75,
                          "reason": "布局完全不同"})
    result = canned_judge(payload).compare(tmp_path / "a", tmp_path / "b")
    assert result["matched"] is False and result["score"] == 0.05
    assert "不是同一界面" in result["message"]
    assert "布局完全不同" in result["message"]


def test_salvage_json_variants():
    data, truncated = salvage_json('{"same_screen": true, "similarity": 0.9}')
    assert data["same_screen"] is True and truncated is False

    data, truncated = salvage_json('前言 {"same_screen": false, "similarity": 0.1} 后缀')
    assert data["same_screen"] is False and truncated is False

    data, truncated = salvage_json('{"same_screen": true, "similarity": 0.7, "reason": "被截')
    assert truncated is True
    assert data["same_screen"] is True and data["similarity"] == 0.7 and data["reason"] == "被截"


def test_health_detects_unreachable_service():
    judge = OmniJudge(host="http://127.0.0.1:1", model="fake:latest", timeout=1)
    info = judge.health()
    assert info["ok"] is False and info["reachable"] is False
    assert "连不上 Ollama" in info["error"]


def test_health_rejects_model_without_vision():
    judge = OmniJudge(host="http://fake", model="text-only:latest", timeout=1)
    judge._request = lambda path, payload=None: {
        "version": "9.9.9",
        "models": [{"name": "text-only:latest", "capabilities": ["completion"]}],
    } if path == "/api/tags" else {"version": "9.9.9"}
    info = judge.health()
    assert info["ok"] is False and info["found"] is True and info["vision"] is False
    assert "没有 vision" in info["error"]


def test_health_rejects_embedding_only_model():
    judge = OmniJudge(host="http://fake", model="embeddinggemma-2:740m", timeout=1)
    judge._request = lambda path, payload=None: {
        "models": [{"name": "embeddinggemma-2:740m",
                    "capabilities": ["embedding", "vision", "audio"]}],
    } if path == "/api/tags" else {"version": "9.9.9"}
    info = judge.health()
    assert info["ok"] is False
    assert "不支持 completion" in info["error"]


def test_health_reports_missing_model():
    judge = OmniJudge(host="http://fake", model="lfm3-omni:latest", timeout=1)
    judge._request = lambda path, payload=None: {
        "models": [{"name": "other:latest", "capabilities": ["completion"]}],
    } if path == "/api/tags" else {"version": "9.9.9"}
    info = judge.health()
    assert info["ok"] is False and info["found"] is False
    assert "ollama pull lfm3-omni:latest" in info["error"]


def test_health_accepts_omni_model():
    judge = OmniJudge(host="http://fake", model="lfm3-omni", timeout=1)
    judge._request = lambda path, payload=None: {
        "models": [{"name": "lfm3-omni:latest",
                    "capabilities": ["completion", "vision", "tools"]}],
    } if path == "/api/tags" else {"version": "0.40.2"}
    info = judge.health()
    assert info["ok"] is True and info["vision"] is True
    assert info["model"] == "lfm3-omni:latest"
    assert info["version"] == "0.40.2"


def test_judge_rejects_oversized_image(tmp_path):
    big = tmp_path / "big.png"
    big.write_bytes(b"x" * (31 * 1024 * 1024))
    judge = canned_judge(GOOD_JSON, stub_encode=False)
    with pytest.raises(JudgeError) as excinfo:
        judge.judge(big, tmp_path / "missing.png")
    assert "图片过大" in str(excinfo.value)


def test_judge_reports_missing_image(tmp_path):
    judge = canned_judge(GOOD_JSON, stub_encode=False)
    with pytest.raises(JudgeError) as excinfo:
        judge.judge(tmp_path / "nope.png", tmp_path / "nope2.png")
    assert "读取图片失败" in str(excinfo.value)


def create_group(client, name, description=""):
    response = client.post("/api/groups", json={"name": name, "description": description})
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def capture_into(client, key, source="window"):
    response = client.post("/api/groups/{}/capture".format(key),
                           json={"source": source, "process": "Fake Mirroring"})
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def test_default_group_created_on_startup(client):
    groups = client.get("/api/groups").get_json()
    assert len(groups) == 1
    assert groups[0]["key"] == "default"
    assert groups[0]["name"] == "默认分组"
    assert groups[0]["shots"] == 0
    assert client.get("/api/info").get_json()["stats"]["groups"] == 1


def test_groups_are_isolated(client, tmp_path):
    soul = create_group(client, "御魂探索", "御魂十层与探索界面")
    qilin = create_group(client, "麒麟", "麒麟副本")
    assert soul["key"] != qilin["key"]

    shot_a = capture_into(client, soul["key"])
    shot_b = capture_into(client, qilin["key"])
    shot_c = capture_into(client, qilin["key"])

    soul_shots = client.get("/api/groups/{}/shots".format(soul["key"])).get_json()
    qilin_shots = client.get("/api/groups/{}/shots".format(qilin["key"])).get_json()
    assert [item["id"] for item in soul_shots] == [shot_a["id"]]
    assert sorted(item["id"] for item in qilin_shots) == sorted([shot_b["id"], shot_c["id"]])

    assert shot_a["group"] == soul["key"]
    assert shot_a["image_url"] == "/shots/{}/{}.png".format(soul["key"], shot_a["id"])
    assert shot_a["thumb_url"].endswith("{}.thumb.jpg".format(shot_a["id"]))

    soul_dir = tmp_path / "dataset" / "groups" / soul["key"] / "shots"
    qilin_dir = tmp_path / "dataset" / "groups" / qilin["key"] / "shots"
    assert (soul_dir / shot_a["image"]).is_file()
    assert not (qilin_dir / shot_a["image"]).exists()
    assert len(list(qilin_dir.glob("*.png"))) == 2

    listing = {item["key"]: item for item in client.get("/api/groups").get_json()}
    assert listing[soul["key"]]["shots"] == 1
    assert listing[qilin["key"]]["shots"] == 2
    assert listing[soul["key"]]["description"] == "御魂十层与探索界面"


def test_cross_group_access_is_404(client):
    soul = create_group(client, "御魂探索")
    qilin = create_group(client, "麒麟")
    shot = capture_into(client, soul["key"])

    assert client.get("/api/groups/{}/shots/{}".format(qilin["key"], shot["id"])).status_code == 404
    assert client.get(shot["image_url"]).status_code == 200
    other = "/shots/{}/{}.png".format(qilin["key"], shot["id"])
    assert client.get(other).status_code == 404


def test_annotations_are_scoped_to_group(client):
    group = create_group(client, "御魂探索")
    shot = capture_into(client, group["key"])
    url = "/api/groups/{}/shots/{}/annotations".format(group["key"], shot["id"])

    saved = client.put(url, json={
        "annotations": [{"kind": "box", "label": "挑战", "box": {"x": 1, "y": 2, "w": 5, "h": 6}}],
        "note": "御魂十层",
    }).get_json()
    assert saved["annotation_count"] == 1

    listing = {item["key"]: item for item in client.get("/api/groups").get_json()}
    assert listing[group["key"]]["annotations"] == 1
    assert listing["default"]["annotations"] == 0


def test_group_name_validation(client):
    assert client.post("/api/groups", json={"name": ""}).status_code == 400
    assert client.post("/api/groups", json={"name": "   "}).status_code == 400
    assert client.post("/api/groups", json={}).status_code == 400
    assert client.post("/api/groups", json={"name": 123}).status_code == 400

    create_group(client, "御魂探索")
    dup = client.post("/api/groups", json={"name": "御魂探索"})
    assert dup.status_code == 400
    assert "已存在" in dup.get_json()["error"]


def test_group_rename_and_description(client):
    group = create_group(client, "御魂探索", "旧说明")
    updated = client.patch("/api/groups/{}".format(group["key"]),
                           json={"name": "御魂十层", "description": "新说明"}).get_json()
    assert updated["name"] == "御魂十层"
    assert updated["description"] == "新说明"

    partial = client.patch("/api/groups/{}".format(group["key"]),
                           json={"description": "只改说明"}).get_json()
    assert partial["name"] == "御魂十层"
    assert partial["description"] == "只改说明"

    assert client.patch("/api/groups/{}".format(group["key"]),
                        json={"name": "默认分组"}).status_code == 400
    assert client.patch("/api/groups/nope", json={"name": "x"}).status_code == 404


def test_group_routes_reject_bad_key(client):
    for bad in ("../secrets", "a/b", "nope"):
        assert client.get("/api/groups/{}/shots".format(bad)).status_code in (400, 404)
    response = client.get("/api/groups/..%2f..%2fetc/shots")
    assert response.status_code in (400, 404)


def test_delete_group_removes_directory(client, tmp_path):
    soul = create_group(client, "御魂探索")
    qilin = create_group(client, "麒麟")
    shot = capture_into(client, soul["key"])
    group_dir = tmp_path / "dataset" / "groups" / soul["key"]
    assert (group_dir / "shots" / shot["image"]).is_file()

    removed = client.delete("/api/groups/{}".format(soul["key"]))
    assert removed.status_code == 200
    assert removed.get_json()["deleted"] == soul["key"]
    assert not group_dir.exists()

    keys = [item["key"] for item in client.get("/api/groups").get_json()]
    assert keys == ["default", qilin["key"]]
    assert client.delete("/api/groups/{}".format(soul["key"])).status_code == 404


def test_delete_last_group_recreates_default(client):
    group = create_group(client, "御魂探索")
    client.delete("/api/groups/default")
    client.delete("/api/groups/{}".format(group["key"]))

    groups = client.get("/api/groups").get_json()
    assert [item["key"] for item in groups] == ["default"]
    assert client.post("/api/groups/default/capture", json={"source": "window"}).status_code == 200


def test_move_shot_between_groups(client, tmp_path):
    soul = create_group(client, "御魂探索")
    qilin = create_group(client, "麒麟")
    shot = capture_into(client, soul["key"])
    client.put("/api/groups/{}/shots/{}/annotations".format(soul["key"], shot["id"]), json={
        "annotations": [{"kind": "point", "label": "头像", "point": {"x": 3, "y": 4}}],
        "note": "跟着一起搬走",
    })

    moved = client.post("/api/groups/{}/shots/{}/move".format(soul["key"], shot["id"]),
                        json={"to": qilin["key"]})
    assert moved.status_code == 200, moved.get_data(as_text=True)
    record = moved.get_json()
    assert record["group"] == qilin["key"]
    assert record["annotation_count"] == 1
    assert record["note"] == "跟着一起搬走"
    assert record["image_url"].startswith("/shots/{}/".format(qilin["key"]))

    assert client.get("/api/groups/{}/shots".format(soul["key"])).get_json() == []
    assert len(client.get("/api/groups/{}/shots".format(qilin["key"])).get_json()) == 1
    soul_dir = tmp_path / "dataset" / "groups" / soul["key"] / "shots"
    qilin_dir = tmp_path / "dataset" / "groups" / qilin["key"] / "shots"
    assert not (soul_dir / shot["image"]).exists()
    assert (qilin_dir / shot["image"]).is_file()
    assert client.get(record["image_url"]).status_code == 200

    same = client.post("/api/groups/{}/shots/{}/move".format(qilin["key"], shot["id"]),
                       json={"to": qilin["key"]})
    assert same.status_code == 400
    missing = client.post("/api/groups/{}/shots/{}/move".format(qilin["key"], shot["id"]),
                          json={"to": "nope"})
    assert missing.status_code == 404


def test_legacy_shots_migrated_into_default_group(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_mod, "capability",
                        lambda: {"ok": True, "errors": [], "platform": "test"})
    legacy = tmp_path / "dataset" / "shots"
    legacy.mkdir(parents=True)
    (tmp_path / "dataset" / "thumbs").mkdir(parents=True)
    shot_id = "20260101-000000-000001"
    (legacy / "{}.png".format(shot_id)).write_bytes(make_png())
    (legacy / "{}.json".format(shot_id)).write_text(json.dumps({
        "id": shot_id, "image": "{}.png".format(shot_id),
        "captured_at": "2026-01-01 00:00:00", "width": 40, "height": 60,
        "source": "window", "annotations": [], "note": "旧数据",
    }, ensure_ascii=False), encoding="utf-8")

    app = create_app(dataset_dir=tmp_path / "dataset", grabber=fake_grab(),
                     judge=FakeJudge())
    app.testing = True
    client = app.test_client()

    shots = client.get("/api/groups/default/shots").get_json()
    assert [item["id"] for item in shots] == [shot_id]
    assert shots[0]["note"] == "旧数据"
    migrated = tmp_path / "dataset" / "groups" / "default" / "shots"
    assert (migrated / "{}.png".format(shot_id)).is_file()
    assert (migrated / "{}.json".format(shot_id)).is_file()
    assert not legacy.exists()
    assert client.get("/shots/default/{}.png".format(shot_id)).status_code == 200


def test_migration_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_mod, "capability",
                        lambda: {"ok": True, "errors": [], "platform": "test"})
    root = tmp_path / "dataset"
    first = create_app(dataset_dir=root, grabber=fake_grab(), judge=FakeJudge())
    first.testing = True
    shot = first.test_client().post(
        "/api/groups/default/capture", json={"source": "window"}).get_json()

    (root / "shots").mkdir(exist_ok=True)
    second = create_app(dataset_dir=root, grabber=fake_grab(), judge=FakeJudge())
    second.testing = True
    client = second.test_client()
    shots = client.get("/api/groups/default/shots").get_json()
    assert [item["id"] for item in shots] == [shot["id"]]
    assert len(list((root / "groups" / "default" / "shots").glob("*.png"))) == 1
