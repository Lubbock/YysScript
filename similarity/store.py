"""数据集存储：截图 PNG + 同名标注 JSON。"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_DATASET: Path = Path(__file__).resolve().parent / "dataset"

SHOT_ID_RE = re.compile(r"^\d{8}-\d{6}-\d{6}$")
ANN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
KINDS = ("box", "point")
LABEL_MAX = 40
NOTE_MAX = 200
MAX_ANNOTATIONS = 200

GROUP_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,48}$")
GROUP_NAME_MAX = 40
GROUP_DESC_MAX = 200
DEFAULT_GROUP_KEY = "default"
DEFAULT_GROUP_NAME = "默认分组"


class StoreError(Exception):
    """存储或参数错误。"""


class ShotNotFound(StoreError):
    """截图不存在。"""


class GroupNotFound(StoreError):
    """分组不存在。"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _int(value: Any, field: str, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise StoreError("{} 不是整数: {!r}".format(field, value))
    if number < low or number > high:
        raise StoreError("{} 超出范围 [{}, {}]: {}".format(field, low, high, number))
    return number


class ShotStore:
    """截图与标注的读写。"""

    def __init__(self, root: Optional[Path] = None, url_prefix: str = "/shots") -> None:
        self.root = Path(root).expanduser().resolve() if root else DEFAULT_DATASET
        self.shots_dir = self.root / "shots"
        self.thumbs_dir = self.root / "thumbs"
        self.url_prefix = url_prefix.rstrip("/")

    def ensure(self) -> None:
        """建目录。"""
        self.shots_dir.mkdir(parents=True, exist_ok=True)
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)

    def check_id(self, shot_id: str) -> str:
        """校验截图 id。"""
        if not isinstance(shot_id, str) or not SHOT_ID_RE.match(shot_id):
            raise StoreError("非法截图 id: {!r}".format(shot_id))
        return shot_id

    def image_path(self, shot_id: str) -> Path:
        return self.shots_dir / "{}.png".format(self.check_id(shot_id))

    def meta_path(self, shot_id: str) -> Path:
        return self.shots_dir / "{}.json".format(self.check_id(shot_id))

    def thumb_path(self, shot_id: str) -> Path:
        return self.thumbs_dir / "{}.jpg".format(self.check_id(shot_id))

    def new_id(self) -> str:
        """生成唯一截图 id。"""
        while True:
            shot_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            if not self.meta_path(shot_id).exists():
                return shot_id

    def save_shot(self, png: bytes, meta: Dict[str, Any]) -> Dict[str, Any]:
        """落盘截图与元信息。"""
        if not png:
            raise StoreError("截图内容为空")
        self.ensure()
        shot_id = self.new_id()
        record = {
            "id": shot_id,
            "image": "{}.png".format(shot_id),
            "captured_at": _now(),
            "annotations": [],
            "note": "",
        }
        record.update(meta)
        record["id"] = shot_id
        record["image"] = "{}.png".format(shot_id)

        image = self.image_path(shot_id)
        image.write_bytes(png)
        self._write_meta(shot_id, record)
        return self.present(record)

    def _write_meta(self, shot_id: str, record: Dict[str, Any]) -> None:
        payload = dict(record)
        for derived in ("image_url", "thumb_url", "annotation_count"):
            payload.pop(derived, None)
        path = self.meta_path(shot_id)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def present(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """补上前端用的派生字段。"""
        out = dict(record)
        out["image_url"] = "{}/{}.png".format(self.url_prefix, out["id"])
        out["thumb_url"] = "{}/{}.thumb.jpg".format(self.url_prefix, out["id"])
        out["annotation_count"] = len(out.get("annotations") or [])
        return out

    def save_annotations(
        self,
        shot_id: str,
        annotations: List[Dict[str, Any]],
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """整体替换某张截图的标注。"""
        record = self.get(shot_id)
        record["annotations"] = self.clean_annotations(
            annotations, int(record["width"]), int(record["height"])
        )
        if note is not None:
            if not isinstance(note, str):
                raise StoreError("备注必须是字符串")
            record["note"] = note.strip()[:NOTE_MAX]
        record["updated_at"] = _now()
        self._write_meta(shot_id, record)
        self.thumb_path(shot_id).unlink(missing_ok=True)
        return self.present(record)

    def delete(self, shot_id: str) -> None:
        """删除截图及其标注。"""
        self.check_id(shot_id)
        for path in (self.image_path(shot_id), self.meta_path(shot_id), self.thumb_path(shot_id)):
            path.unlink(missing_ok=True)

    def get(self, shot_id: str) -> Dict[str, Any]:
        """读单张截图元信息。"""
        path = self.meta_path(shot_id)
        if not path.is_file():
            raise ShotNotFound("截图不存在: {}".format(shot_id))
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StoreError("标注文件损坏 {}: {}".format(shot_id, exc))
        return self.present(record)

    def list_shots(self) -> List[Dict[str, Any]]:
        """按时间倒序列出全部截图。"""
        if not self.shots_dir.exists():
            return []
        shots = []
        for path in self.shots_dir.glob("*.json"):
            try:
                shots.append(self.get(path.stem))
            except StoreError:
                continue
        shots.sort(key=lambda item: item["id"], reverse=True)
        return shots

    def stats(self) -> Dict[str, Any]:
        """数据集统计。"""
        shots = self.list_shots()
        return {
            "shots": len(shots),
            "annotations": sum(len(item.get("annotations") or []) for item in shots),
            "labels": sorted({
                ann["label"]
                for item in shots
                for ann in (item.get("annotations") or [])
                if ann.get("label")
            }),
        }

    def clean_annotations(
        self, raw: Any, width: int, height: int
    ) -> List[Dict[str, Any]]:
        """校验并规范化标注列表。"""
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            raise StoreError("annotations 必须是数组")
        if len(raw) > MAX_ANNOTATIONS:
            raise StoreError("单张截图最多 {} 个标注".format(MAX_ANNOTATIONS))

        cleaned: List[Dict[str, Any]] = []
        seen = set()
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise StoreError("第 {} 个标注不是对象".format(index + 1))
            kind = item.get("kind", "box")
            if kind not in KINDS:
                raise StoreError("第 {} 个标注 kind 非法: {!r}".format(index + 1, kind))

            label = item.get("label", "")
            if not isinstance(label, str):
                raise StoreError("第 {} 个标注 label 必须是字符串".format(index + 1))
            label = label.strip()[:LABEL_MAX]

            ann_id = item.get("id")
            if not isinstance(ann_id, str) or not ANN_ID_RE.match(ann_id):
                ann_id = "a" + uuid.uuid4().hex[:8]
            while ann_id in seen:
                ann_id = "a" + uuid.uuid4().hex[:8]
            seen.add(ann_id)

            entry: Dict[str, Any] = {
                "id": ann_id,
                "kind": kind,
                "label": label,
            }
            if kind == "box":
                box = item.get("box") or {}
                if not isinstance(box, dict):
                    raise StoreError("第 {} 个标注 box 必须是对象".format(index + 1))
                x = _int(box.get("x"), "box.x", 0, max(width - 1, 0))
                y = _int(box.get("y"), "box.y", 0, max(height - 1, 0))
                w = _int(box.get("w"), "box.w", 1, width)
                h = _int(box.get("h"), "box.h", 1, height)
                if x + w > width or y + h > height:
                    raise StoreError(
                        "第 {} 个标注超出图片范围（{}x{}，图片 {}x{}）".format(
                            index + 1, w, h, width, height
                        )
                    )
                entry["box"] = {"x": x, "y": y, "w": w, "h": h}
            else:
                point = item.get("point") or {}
                if not isinstance(point, dict):
                    raise StoreError("第 {} 个标注 point 必须是对象".format(index + 1))
                entry["point"] = {
                    "x": _int(point.get("x"), "point.x", 0, max(width - 1, 0)),
                    "y": _int(point.get("y"), "point.y", 0, max(height - 1, 0)),
                }
            cleaned.append(entry)
        return cleaned


COMPARE_ID_RE = re.compile(r"^c\d{8}-\d{6}-\d{6}$")
MAX_COMPARE_IMAGES = 40


class CompareStore:
    """对比页用的临时截图，与标注数据集分开存放。"""

    def __init__(self, root: Optional[Path] = None) -> None:
        base = Path(root).expanduser().resolve() if root else DEFAULT_DATASET
        self.root = base / "compare"

    def ensure(self) -> None:
        """建目录。"""
        self.root.mkdir(parents=True, exist_ok=True)

    def check_id(self, image_id: str) -> str:
        """校验对比图 id。"""
        if not isinstance(image_id, str) or not COMPARE_ID_RE.match(image_id):
            raise StoreError("非法对比图 id: {!r}".format(image_id))
        return image_id

    def image_path(self, image_id: str) -> Path:
        return self.root / "{}.png".format(self.check_id(image_id))

    def new_id(self) -> str:
        """生成唯一对比图 id。"""
        while True:
            image_id = "c" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            if not (self.root / "{}.png".format(image_id)).exists():
                return image_id

    def save(self, png: bytes, meta: Dict[str, Any]) -> Dict[str, Any]:
        """落盘一张对比图。"""
        if not png:
            raise StoreError("截图内容为空")
        self.ensure()
        image_id = self.new_id()
        self.image_path(image_id).write_bytes(png)
        record = dict(meta)
        record["id"] = image_id
        record["image_url"] = "/compare-img/{}.png".format(image_id)
        record["captured_at"] = _now()
        self.prune()
        return record

    def prune(self) -> None:
        """只保留最近 MAX_COMPARE_IMAGES 张。"""
        if not self.root.exists():
            return
        ordered = sorted(self.root.glob("*.png"), key=lambda p: p.name, reverse=True)
        for path in ordered[MAX_COMPARE_IMAGES:]:
            try:
                path.unlink()
            except OSError:
                pass


class Dataset:
    """数据集：分组清单 + 每组一份 ShotStore + 对比用临时图。

    目录布局：
        <root>/groups.json                    分组清单（有序）
        <root>/groups/<key>/shots/<id>.png    截图
        <root>/groups/<key>/shots/<id>.json   标注 + 元信息
        <root>/groups/<key>/thumbs/<id>.jpg   缩略图缓存
        <root>/compare/<cid>.png              对比页临时图（不属于任何分组）
    """

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root).expanduser().resolve() if root else DEFAULT_DATASET
        self.groups_dir = self.root / "groups"
        self.manifest_path = self.root / "groups.json"
        self.compare_store = CompareStore(self.root)

    def ensure(self) -> int:
        """建目录并迁移旧数据。"""
        self.groups_dir.mkdir(parents=True, exist_ok=True)
        self.compare_store.ensure()
        groups = self._read_manifest()
        if not groups:
            groups = [self._record(
                DEFAULT_GROUP_KEY, DEFAULT_GROUP_NAME,
                "分组功能上线前采集的截图都归到这里")]
            self._write_manifest(groups)
        self.shots(groups[0]["key"]).ensure()
        return self._migrate_legacy()

    def _migrate_legacy(self) -> int:
        """旧数据搬进默认分组。"""
        legacy = self.root / "shots"
        if not legacy.is_dir():
            return 0
        target = self.shots(DEFAULT_GROUP_KEY)
        target.ensure()
        moved = 0
        for path in sorted(legacy.iterdir()):
            dest = target.shots_dir / path.name
            if not dest.exists():
                shutil.move(str(path), str(dest))
                moved += 1
        old_thumbs = self.root / "thumbs"
        if old_thumbs.is_dir():
            target.thumbs_dir.mkdir(parents=True, exist_ok=True)
            for path in sorted(old_thumbs.iterdir()):
                dest = target.thumbs_dir / path.name
                if not dest.exists():
                    shutil.move(str(path), str(dest))
        for directory in (legacy, old_thumbs):
            try:
                if directory.is_dir() and not any(directory.iterdir()):
                    directory.rmdir()
            except OSError:
                pass
        return moved

    def _read_manifest(self) -> List[Dict[str, Any]]:
        if not self.manifest_path.is_file():
            return []
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        entries = data.get("groups") if isinstance(data, dict) else None
        return [item for item in (entries or [])
                if isinstance(item, dict) and GROUP_KEY_RE.match(str(item.get("key", "")))]

    def _write_manifest(self, groups: List[Dict[str, Any]]) -> None:
        self.groups_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.manifest_path.with_name(self.manifest_path.name + ".tmp")
        tmp.write_text(json.dumps({"groups": groups}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self.manifest_path)

    def _record(self, key: str, name: str, description: str = "") -> Dict[str, Any]:
        return {
            "key": key,
            "name": name,
            "description": description,
            "created_at": _now(),
            "updated_at": _now(),
        }

    def _new_key(self) -> str:
        """生成不撞车的分组 key。"""
        while True:
            key = "g{}-{}".format(
                datetime.now().strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:4])
            if not (self.groups_dir / key).exists():
                return key

    def check_key(self, key: Any) -> str:
        """校验分组 key，阻断路径穿越。"""
        if not isinstance(key, str) or not GROUP_KEY_RE.match(key):
            raise StoreError("非法分组 key: {!r}".format(key))
        return key

    def resolve_key(self, key: Optional[str] = None) -> str:
        """把空 key 解析成默认分组。"""
        return self.check_key(key) if key else DEFAULT_GROUP_KEY

    def group_dir(self, key: str) -> Path:
        return self.groups_dir / self.check_key(key)

    def shots(self, key: str) -> ShotStore:
        """某分组的截图仓库。"""
        checked = self.check_key(key)
        return ShotStore(self.group_dir(checked), url_prefix="/shots/{}".format(checked))

    def get_group(self, key: str) -> Dict[str, Any]:
        """读分组记录（不含统计）。"""
        checked = self.check_key(key)
        for item in self._read_manifest():
            if item["key"] == checked:
                return dict(item)
        raise GroupNotFound("分组不存在: {}".format(checked))

    def present_group(self, record: Dict[str, Any]) -> Dict[str, Any]:
        store = self.shots(record["key"])
        listed = store.list_shots()
        out = dict(record)
        out["shots"] = len(listed)
        out["annotations"] = sum(len(item.get("annotations") or []) for item in listed)
        out["dir"] = str(store.root)
        return out

    def list_groups(self) -> List[Dict[str, Any]]:
        """按清单顺序列出分组。"""
        return [self.present_group(item) for item in self._read_manifest()]

    def create_group(self, name: Any, description: Any = "") -> Dict[str, Any]:
        """新建分组。"""
        clean_name = self._clean_name(name)
        clean_desc = self._clean_desc(description)
        groups = self._read_manifest()
        self._assert_name_free(groups, clean_name)
        record = self._record(self._new_key(), clean_name, clean_desc)
        groups.append(record)
        self._write_manifest(groups)
        self.shots(record["key"]).ensure()
        return self.present_group(record)

    def update_group(
        self, key: str, name: Any = None, description: Any = None
    ) -> Dict[str, Any]:
        """改名 / 改说明。"""
        checked = self.check_key(key)
        groups = self._read_manifest()
        target = next((item for item in groups if item["key"] == checked), None)
        if target is None:
            raise GroupNotFound("分组不存在: {}".format(checked))
        if name is not None:
            clean_name = self._clean_name(name)
            self._assert_name_free(groups, clean_name, except_key=checked)
            target["name"] = clean_name
        if description is not None:
            target["description"] = self._clean_desc(description)
        target["updated_at"] = _now()
        self._write_manifest(groups)
        return self.present_group(target)

    def delete_group(self, key: str) -> Dict[str, Any]:
        """删除分组连同其全部截图与标注。"""
        checked = self.check_key(key)
        groups = self._read_manifest()
        kept = [item for item in groups if item["key"] != checked]
        if len(kept) == len(groups):
            raise GroupNotFound("分组不存在: {}".format(checked))
        removed = next(item for item in groups if item["key"] == checked)
        if not kept:
            kept = [self._record(DEFAULT_GROUP_KEY, DEFAULT_GROUP_NAME,
                                 "删掉最后一个分组后自动重建")]
        self._write_manifest(kept)
        shutil.rmtree(self.group_dir(checked), ignore_errors=True)
        self.shots(kept[0]["key"]).ensure()
        return removed

    def move_shot(self, shot_id: str, from_key: str, to_key: str) -> Dict[str, Any]:
        """把一张截图连同标注搬到另一个分组。"""
        source = self.shots(from_key)
        target = self.shots(to_key)
        if source.root == target.root:
            raise StoreError("源分组与目标分组相同")
        record = source.get(shot_id)
        image = source.image_path(shot_id)
        if not image.is_file():
            raise ShotNotFound("截图文件已丢失: {}".format(shot_id))
        target.ensure()
        if target.meta_path(shot_id).exists():
            raise StoreError("目标分组已存在同 id 的截图: {}".format(shot_id))
        shutil.move(str(image), str(target.image_path(shot_id)))
        shutil.move(str(source.meta_path(shot_id)), str(target.meta_path(shot_id)))
        thumb = source.thumb_path(shot_id)
        if thumb.is_file():
            thumb.unlink()
        payload = dict(record)
        payload["group"] = target.root.name
        target._write_meta(shot_id, payload)
        return target.get(shot_id)

    def stats(self) -> Dict[str, Any]:
        """全数据集统计。"""
        listed = []
        for item in self._read_manifest():
            listed.extend(self.shots(item["key"]).list_shots())
        return {
            "groups": len(self._read_manifest()),
            "shots": len(listed),
            "annotations": sum(len(item.get("annotations") or []) for item in listed),
            "labels": sorted({
                ann["label"]
                for item in listed
                for ann in (item.get("annotations") or [])
                if ann.get("label")
            }),
        }

    def _clean_name(self, name: Any) -> str:
        if not isinstance(name, str):
            raise StoreError("分组名必须是字符串")
        clean = " ".join(name.split())[:GROUP_NAME_MAX]
        if not clean:
            raise StoreError("分组名不能为空")
        return clean

    def _clean_desc(self, description: Any) -> str:
        if description in (None, ""):
            return ""
        if not isinstance(description, str):
            raise StoreError("分组说明必须是字符串")
        return " ".join(description.split())[:GROUP_DESC_MAX]

    def _assert_name_free(
        self, groups: List[Dict[str, Any]], name: str, except_key: Optional[str] = None
    ) -> None:
        for item in groups:
            if item.get("name") == name and item.get("key") != except_key:
                raise StoreError("分组名已存在: {}".format(name))
