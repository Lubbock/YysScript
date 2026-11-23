"""第九章地图图标。"""
from config import settings
from states.base import State, StateKind

MARKER_CHAPTER_NINE = State(
    key="MARKER_CHAPTER_NINE",
    label="第九章",
    templates=("第九章.png",),
    threshold=settings.STRICT_THRESHOLD,
    kind=StateKind.MARKER,
    description="探索选图时的第九章图标；用高阈值避免误匹配到其它章节",
)
