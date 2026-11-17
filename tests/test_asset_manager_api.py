"""模板管理工具（tools/asset_manager）的 API 契约测试。

重点不是测 Flask 本身，而是**锁定前端 app.js 依赖的 JSON 字段**：
前端是原生 JS，字段名写错不会报错、只会静默渲染成空白，所以用测试兜住。

用 Flask test_client，不需要真实起服务，也不需要 pyautogui / cv2。
"""
import importlib.util
import io
import sys
from pathlib import Path

import pytest
from PIL import Image

flask = pytest.importorskip("flask", reason="模板管理工具需要 flask")

TOOL = Path(__file__).resolve().parents[1] / "tools" / "asset_manager" / "app.py"


def load_app_module():
    """tools/ 不是包，按文件路径加载模块。"""
    spec = importlib.util.spec_from_file_location("asset_manager_app", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules["asset_manager_app"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """把模板 / 备份 / 截图目录指到临时目录，避免测试动到真实 assets。"""
    mod = load_app_module()
    tpl = tmp_path / "templates"
    tpl.mkdir()
    monkeypatch.setattr(mod, "TEMPLATE_DIR", tpl.resolve())
    monkeypatch.setattr(mod, "BACKUP_ROOT", (tmp_path / "backups").resolve())
    monkeypatch.setattr(mod, "CAPTURE_DIR", (tmp_path / "captures").resolve())
    # 真实状态注册表引用的模板在临时目录里都不存在，正好覆盖「缺失」分支
    return mod, tpl, mod.app.test_client()


def make_png(size=(60, 40), color=(10, 200, 90)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# /api/info —— 前端顶栏统计与能力徽标
# --------------------------------------------------------------------------- #
def test_info_shape(env):
    mod, tpl, client = env
    data = client.get("/api/info").get_json()

    for key in ("template_dir", "backup_dir", "capture_dir", "base_client_size",
                "default_threshold", "counts", "capabilities"):
        assert key in data, "前端读取的字段缺失: {}".format(key)
    for key in ("states", "screen", "marker", "templates_on_disk", "missing", "orphans"):
        assert key in data["counts"], "counts 缺字段: {}".format(key)
    for key in ("capture", "capture_error", "match", "match_error"):
        assert key in data["capabilities"], "capabilities 缺字段: {}".format(key)

    assert data["counts"]["states"] == 34
    assert data["counts"]["screen"] + data["counts"]["marker"] == data["counts"]["states"]
    assert isinstance(data["capabilities"]["match"], bool)
    assert len(data["base_client_size"]) == 2


def test_info_reports_missing_and_orphans(env):
    mod, tpl, client = env
    (tpl / "scc.png").write_bytes(make_png())          # 磁盘有、无状态引用
    (tpl / "首页.png").write_bytes(make_png())          # 有状态引用
    data = client.get("/api/info").get_json()

    assert "scc.png" in data["counts"]["orphans"]
    assert "首页.png" not in data["counts"]["missing"]
    assert "EXPLORE_MAP" not in str(data["counts"]["missing"])  # 该状态模板仍缺失
    assert len(data["counts"]["missing"]) == 33          # 34 个状态只补了 1 张图


# --------------------------------------------------------------------------- #
# /api/states —— 卡片网格
# --------------------------------------------------------------------------- #
def test_states_shape(env):
    mod, tpl, client = env
    states = client.get("/api/states").get_json()
    assert len(states) == 34

    by_key = {s["key"]: s for s in states}
    home = by_key["HOME"]
    for key in ("key", "label", "kind", "threshold", "description", "used_by", "templates"):
        assert key in home, "状态对象缺字段: {}".format(key)
    assert home["kind"] in {"screen", "marker"}
    assert home["templates"][0]["name"] == "首页.png"

    t = home["templates"][0]
    for key in ("name", "exists"):
        assert key in t, "模板对象缺字段: {}".format(key)
    assert t["exists"] is False          # 临时目录里没这张图
    assert "width" not in t              # 不存在时不应有尺寸字段


def test_states_template_meta_when_file_present(env):
    mod, tpl, client = env
    (tpl / "首页.png").write_bytes(make_png((142, 142)))
    home = next(s for s in client.get("/api/states").get_json() if s["key"] == "HOME")
    t = home["templates"][0]
    for key in ("exists", "width", "height", "bytes", "mtime", "mode", "valid"):
        assert key in t, "已存在模板缺字段: {}".format(key)
    assert (t["width"], t["height"]) == (142, 142)
    assert t["valid"] is True


def test_states_used_by_matches_flow_imports(env):
    """used_by 来自 AST 扫描 flows/，应能反映真实引用关系。"""
    mod, tpl, client = env
    by_key = {s["key"]: s for s in client.get("/api/states").get_json()}
    assert "explore" in by_key["HOME"]["used_by"]
    assert "explore" in by_key["EXPLORE_MAP"]["used_by"]
    assert "breakthrough" in by_key["MARKER_ATTACK"]["used_by"]
    # 只有 states/base.py、machine.py 之类不会被计入
    assert all(f != "base" for f in by_key["HOME"]["used_by"])


def test_marker_kind_flagged(env):
    mod, tpl, client = env
    by_key = {s["key"]: s for s in client.get("/api/states").get_json()}
    assert by_key["MARKER_FULL_LEVEL"]["kind"] == "marker"
    assert by_key["HOME"]["kind"] == "screen"
    assert by_key["MARKER_CHAPTER_NINE"]["threshold"] == 0.9   # 高精度阈值


# --------------------------------------------------------------------------- #
# /api/flows —— 流程过滤下拉
# --------------------------------------------------------------------------- #
def test_flows_shape(env):
    mod, tpl, client = env
    flows = client.get("/api/flows").get_json()
    names = {f["name"] for f in flows}
    # 以 flows/registry.py 为准：即使某个流程不引用任何状态，也必须出现在清单里
    assert names == {"explore", "soul", "awake", "breakthrough", "seal", "heart",
                     "event-aband3t", "event-aj8fer"}
    for f in flows:
        assert set(f) == {"name", "description", "states"}
        assert isinstance(f["states"], list)
        assert f["description"]


def test_soul_flow_references_no_states(env):
    """记录现状：soul 是纯定时流程（click → sleep 80s → click），不做任何状态校验。

    所以它会出现在流程下拉里但 states 为空，状态卡片的 used_by 也不会出现 soul。
    若将来给 SoulFlow 补上状态校验，这条测试会失败并提醒更新预期。
    """
    mod, tpl, client = env
    flows = {f["name"]: f for f in client.get("/api/flows").get_json()}
    assert flows["soul"]["states"] == []
    assert flows["explore"]["states"], "explore 应该引用了状态"
    assert "HOME" in flows["explore"]["states"]


# --------------------------------------------------------------------------- #
# 替换 + 备份 + 回滚
# --------------------------------------------------------------------------- #
def test_replace_creates_backup_and_reports_size_warning(env):
    mod, tpl, client = env
    (tpl / "首页.png").write_bytes(make_png((142, 142)))
    original = (tpl / "首页.png").read_bytes()

    res = client.post("/api/template/首页.png",
                      data={"file": (io.BytesIO(make_png((60, 40))), "new.png")},
                      content_type="multipart/form-data").get_json()

    assert res["ok"] is True
    assert res["backup"]                            # 生成了备份
    assert res["new"]["width"] == 60 and res["new"]["height"] == 40
    assert res["old"]["width"] == 142
    assert res["warning"]                           # 142x142 -> 60x40 触发尺寸警告
    assert (tpl / "首页.png").read_bytes() != original

    # 备份内容 == 替换前的原图
    backups = client.get("/api/template/首页.png/backups").get_json()
    assert len(backups) == 1
    assert backups[0]["stamp"] == res["backup"]
    assert (backups[0]["width"], backups[0]["height"]) == (142, 142)
    for key in ("stamp", "exists", "width", "height", "bytes"):
        assert key in backups[0], "备份对象缺字段: {}".format(key)


def test_no_warning_when_size_similar(env):
    mod, tpl, client = env
    (tpl / "首页.png").write_bytes(make_png((100, 100)))
    res = client.post("/api/template/首页.png",
                      data={"file": (io.BytesIO(make_png((105, 100))), "n.png")},
                      content_type="multipart/form-data").get_json()
    assert res["warning"] is None


def test_backup_image_endpoint_serves_backup_not_current(env):
    """备份缩略图必须是备份本身，否则回滚前看到的图是错的。"""
    mod, tpl, client = env
    (tpl / "首页.png").write_bytes(make_png((142, 142), (255, 0, 0)))
    res = client.post("/api/template/首页.png",
                      data={"file": (io.BytesIO(make_png((30, 30), (0, 0, 255))), "n.png")},
                      content_type="multipart/form-data").get_json()

    raw = client.get("/backup-img/{}/首页.png".format(res["backup"]))
    assert raw.status_code == 200
    with Image.open(io.BytesIO(raw.data)) as im:
        assert im.size == (142, 142)          # 备份是旧图尺寸
    with Image.open(io.BytesIO(client.get("/img/首页.png").data)) as im:
        assert im.size == (30, 30)            # 当前是新图尺寸


def test_rollback_restores_previous_version(env):
    mod, tpl, client = env
    (tpl / "首页.png").write_bytes(make_png((142, 142)))
    res = client.post("/api/template/首页.png",
                      data={"file": (io.BytesIO(make_png((30, 30))), "n.png")},
                      content_type="multipart/form-data").get_json()

    r = client.post("/api/template/首页.png/rollback",
                    json={"stamp": res["backup"]}).get_json()
    assert r["ok"] is True
    with Image.open(tpl / "首页.png") as im:
        assert im.size == (142, 142)
    # 回滚本身也会留一份备份，所以可以再回滚回去
    assert len(client.get("/api/template/首页.png/backups").get_json()) == 2


# --------------------------------------------------------------------------- #
# 裁剪（不依赖截屏能力，源可以指定为已有模板）
# --------------------------------------------------------------------------- #
def test_crop_saves_target(env):
    mod, tpl, client = env
    (tpl / "wait_adventure.png").write_bytes(make_png((598, 92)))
    (tpl / "满.png").write_bytes(make_png((40, 38)))

    r = client.post("/api/crop", json={
        "source": "template", "name": "wait_adventure.png",
        "x": 10, "y": 5, "w": 80, "h": 40, "target": "满.png",
    }).get_json()

    assert r["ok"] is True and r["size"] == [80, 40] and r["backup"]
    with Image.open(tpl / "满.png") as im:
        assert im.size == (80, 40)
    assert r["meta"]["width"] == 80


def test_crop_rejects_out_of_bounds(env):
    mod, tpl, client = env
    (tpl / "满.png").write_bytes(make_png((40, 38)))
    res = client.post("/api/crop", json={
        "source": "template", "name": "满.png",
        "x": 0, "y": 0, "w": 9999, "h": 20, "target": "满.png"})
    assert res.status_code == 400
    assert "超出" in res.get_json()["error"]


def test_crop_rejects_too_small(env):
    mod, tpl, client = env
    (tpl / "满.png").write_bytes(make_png((40, 38)))
    res = client.post("/api/crop", json={
        "source": "template", "name": "满.png",
        "x": 0, "y": 0, "w": 2, "h": 2, "target": "满.png"})
    assert res.status_code == 400
    assert "4x4" in res.get_json()["error"]


# --------------------------------------------------------------------------- #
# 安全边界：路径穿越 / 类型校验 / 非法输入
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [
    "/img/..%2f..%2fconfig%2fsettings.py",
    "/img/settings.py",
    "/img/首页.txt",
    "/img/%2e%2e%2f%2e%2e%2fmain.py",
    "/cap/..%2f..%2fREADME.md",
])
def test_path_traversal_blocked(env, bad):
    mod, tpl, client = env
    assert client.get(bad).status_code == 400


def test_upload_rejects_non_png(env):
    mod, tpl, client = env
    (tpl / "满.png").write_bytes(make_png())
    before = (tpl / "满.png").read_bytes()
    res = client.post("/api/template/满.png",
                      data={"file": (io.BytesIO(b"definitely not a png"), "x.png")},
                      content_type="multipart/form-data")
    assert res.status_code == 400
    assert (tpl / "满.png").read_bytes() == before   # 坏文件没有覆盖掉好文件


def test_upload_requires_file_field(env):
    mod, tpl, client = env
    assert client.post("/api/template/满.png", data={}).status_code == 400


def test_rollback_rejects_bad_stamp(env):
    mod, tpl, client = env
    (tpl / "满.png").write_bytes(make_png())
    for stamp in ["", "..", "../../etc", "a/b"]:
        res = client.post("/api/template/满.png/rollback", json={"stamp": stamp})
        assert res.status_code in (400, 404), stamp


def test_missing_template_returns_404(env):
    mod, tpl, client = env
    assert client.get("/img/满.png").status_code == 404


def test_static_and_index_served(env):
    mod, tpl, client = env
    assert client.get("/").status_code == 200
    assert "模板图片管理".encode() in client.get("/").data
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_errors_are_json(env):
    """前端统一按 {error} 解析，HTML 错误页会导致提示变成 'HTTP 400'。"""
    mod, tpl, client = env
    body = client.get("/img/settings.py").get_json()
    assert body["ok"] is False and body["error"]


# --------------------------------------------------------------------------- #
# 无截屏能力时的降级
# --------------------------------------------------------------------------- #
def test_capture_degrades_without_pyautogui(env, monkeypatch):
    mod, tpl, client = env
    monkeypatch.setattr(mod, "HAS_CAPTURE", False)
    res = client.post("/api/capture", json={})
    assert res.status_code == 503
    assert "pyautogui" in res.get_json()["error"]


def test_probe_degrades_without_cv2(env, monkeypatch):
    mod, tpl, client = env
    monkeypatch.setattr(mod, "HAS_MATCH", False)
    res = client.post("/api/probe", json={"name": "首页.png"})
    assert res.status_code == 503


def test_safe_name_helper(env):
    mod, tpl, client = env
    assert mod.safe_name("首页.png") == "首页.png"
    with pytest.raises(Exception):
        mod.safe_name("../evil.png")
    with pytest.raises(Exception):
        mod.safe_name("evil.jpg")
    with pytest.raises(Exception):
        mod.safe_name("")
