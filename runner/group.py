"""分组解析：把标注数据变成可执行引用。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from config import settings
from runner.errors import GroupError
from similarity.store import DEFAULT_DATASET, Dataset, StoreError

Region = Tuple[int, int, int, int]


@dataclass(frozen=True)
class AnnotationRef:
    """一个标注，坐标已归一成点击点。"""

    id: str
    kind: str
    label: str
    x: int
    y: int

    @property
    def point(self) -> Tuple[int, int]:
        return self.x, self.y

    def describe(self) -> str:
        return "{}「{}」({},{})".format(self.kind, self.label or "未命名", self.x, self.y)


@dataclass(frozen=True)
class ShotRef:
    """一张截图及其全部标注。"""

    id: str
    image_path: Path
    width: int
    height: int
    region: Region
    note: str
    captured_at: str
    annotations: Tuple[AnnotationRef, ...]

    @property
    def origin(self) -> Tuple[int, int]:
        return self.region[0], self.region[1]

    @property
    def size(self) -> Tuple[int, int]:
        return self.region[2], self.region[3]

    def labels(self) -> List[str]:
        return [item.label for item in self.annotations if item.label]

    def find(self, label: str) -> Optional[AnnotationRef]:
        for item in self.annotations:
            if item.label == label:
                return item
        return None

    def only(self) -> AnnotationRef:
        """取唯一标注，多于一个时报错。"""
        if not self.annotations:
            raise GroupError("截图 {} 没有任何标注，无法点击".format(self.id))
        if len(self.annotations) > 1:
            raise GroupError(
                "截图 {} 有 {} 个标注（{}），请在 step(click=...) 里指名要点哪个".format(
                    self.id, len(self.annotations), ", ".join(self.labels())))
        return self.annotations[0]

    def describe(self) -> str:
        return "{} {}x{} [{}]".format(
            self.id, self.width, self.height, ", ".join(self.labels()) or "无标注")


@dataclass(frozen=True)
class GroupRef:
    """一个分组的可执行视图。"""

    key: str
    name: str
    description: str
    directory: Path
    shots: Tuple[ShotRef, ...]

    @property
    def dsl_path(self) -> Path:
        return self.directory / settings.RUNNER_DSL_FILENAME

    def has_dsl(self) -> bool:
        return self.dsl_path.is_file()

    def all_labels(self) -> List[str]:
        seen: List[str] = []
        for shot in self.shots:
            for label in shot.labels():
                if label not in seen:
                    seen.append(label)
        return seen

    def shot(self, shot_id: str) -> ShotRef:
        for item in self.shots:
            if item.id == shot_id:
                return item
        raise GroupError("分组「{}」里没有截图 {}".format(self.name, shot_id))

    def by_label(self, label: str) -> List[ShotRef]:
        return [item for item in self.shots if item.find(label) is not None]

    def by_note(self, note: str) -> List[ShotRef]:
        return [item for item in self.shots if item.note == note]

    def timing_prefix(self) -> str:
        """计时 key 前缀，用分组名便于读日志。"""
        return self.name or self.key

    def describe(self) -> str:
        return "分组「{}」[{}] {} 张截图 / {} 个标注".format(
            self.name, self.key, len(self.shots),
            sum(len(item.annotations) for item in self.shots))


def _annotation(raw: Dict) -> AnnotationRef:
    kind = raw.get("kind")
    if kind == "box":
        box = raw.get("box") or {}
        x = int(box.get("x", 0)) + int(box.get("w", 0)) // 2
        y = int(box.get("y", 0)) + int(box.get("h", 0)) // 2
    elif kind == "point":
        point = raw.get("point") or {}
        x, y = int(point.get("x", 0)), int(point.get("y", 0))
    else:
        raise GroupError("未知标注类型: {!r}".format(kind))
    return AnnotationRef(
        id=str(raw.get("id", "")), kind=str(kind),
        label=str(raw.get("label", "")), x=x, y=y)


def _region(record: Dict) -> Region:
    region = record.get("region")
    if isinstance(region, (list, tuple)) and len(region) == 4:
        return tuple(int(v) for v in region)
    origin = record.get("origin") or [0, 0]
    return (int(origin[0]), int(origin[1]),
            int(record.get("width", 0)), int(record.get("height", 0)))


def _shot(record: Dict, store) -> ShotRef:
    return ShotRef(
        id=record["id"],
        image_path=store.image_path(record["id"]),
        width=int(record.get("width", 0)),
        height=int(record.get("height", 0)),
        region=_region(record),
        note=str(record.get("note", "")),
        captured_at=str(record.get("captured_at", "")),
        annotations=tuple(_annotation(item) for item in (record.get("annotations") or [])),
    )


def open_dataset(root: Optional[Path] = None) -> Dataset:
    """打开数据集。"""
    dataset = Dataset(root or DEFAULT_DATASET)
    dataset.ensure()
    return dataset


def list_groups(root: Optional[Path] = None) -> List[Dict]:
    """列出全部分组。"""
    return open_dataset(root).list_groups()


def load_group(name_or_key: str, root: Optional[Path] = None) -> GroupRef:
    """按名字或 key 载入分组。"""
    if not name_or_key or not str(name_or_key).strip():
        raise GroupError("必须指定分组名或 key")
    wanted = str(name_or_key).strip()
    dataset = open_dataset(root)
    try:
        groups = dataset.list_groups()
    except StoreError as exc:
        raise GroupError("读取分组清单失败：{}".format(exc))

    record = None
    for item in groups:
        if item["key"] == wanted or item["name"] == wanted:
            record = item
            break
    if record is None:
        raise GroupError("找不到分组「{}」。现有分组：{}".format(
            wanted, ", ".join("{}（{}）".format(i["name"], i["key"]) for i in groups) or "无"))

    store = dataset.shots(record["key"])
    shots = tuple(
        _shot(item, store)
        for item in sorted(store.list_shots(), key=lambda x: x["captured_at"])
    )
    return GroupRef(
        key=record["key"],
        name=record["name"],
        description=record.get("description", ""),
        directory=Path(record.get("dir") or store.root),
        shots=shots,
    )
