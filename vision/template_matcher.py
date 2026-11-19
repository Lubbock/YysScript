"""模板匹配。

对应旧 utils/MapCv.py 的 __in_screenshot__ / location_screen / location_multiscreen。
改进点：
1. 模板图片只读一次并缓存（旧代码每次识别都 cv2.imread）；
2. 路径来自 config.settings.TEMPLATE_DIR，不再写死 E:/github/...；
3. 命中结果做非极大值抑制，同一个按钮不会返回几十个重复点；
4. 返回 Box（含左上角 + 宽高），既能取中心点也能复现旧的右下角行为。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from config import settings
from core.errors import ConfigError
from vision.capture import ScreenCapture
from vision.types import Box, Match


class TemplateMatcher:
    """基于 cv2.matchTemplate 的模板匹配器。"""

    def __init__(
        self,
        capture: Optional[ScreenCapture] = None,
        template_dir: Optional[Path] = None,
    ) -> None:
        self._capture = capture or ScreenCapture()
        self._template_dir = Path(template_dir) if template_dir else settings.TEMPLATE_DIR
        self._cache: Dict[str, np.ndarray] = {}

    # ------------------------------------------------------------------ 模板
    def template_path(self, filename: str) -> Path:
        return self._template_dir / filename

    def load_template(self, filename: str) -> np.ndarray:
        """读取灰度模板，带缓存。模板缺失时抛 ConfigError 而不是静默返回 None。"""
        cached = self._cache.get(filename)
        if cached is not None:
            return cached
        path = self.template_path(filename)
        template = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if template is None:
            raise ConfigError("模板图片读取失败: {}".format(path))
        self._cache[filename] = template
        return template

    # ------------------------------------------------------------------ 匹配
    def match(
        self,
        filename: str,
        threshold: Optional[float] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
        scales: Optional[Sequence[float]] = None,
    ) -> Optional[Match]:
        """返回置信度最高的一次命中；没有命中返回 None。"""
        matches = self.match_all(
            filename, threshold=threshold, region=region, limit=1, scales=scales
        )
        return matches[0] if matches else None

    def exists(
        self,
        filename: str,
        threshold: Optional[float] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> bool:
        """只判断存在性，对应旧的 __in_screenshot__。"""
        return self.match(filename, threshold=threshold, region=region) is not None

    def match_all(
        self,
        filename: str,
        threshold: Optional[float] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
        limit: Optional[int] = None,
        scales: Optional[Sequence[float]] = None,
    ) -> List[Match]:
        """返回全部命中，按置信度降序，已做去重合并。

        scales 为模板尺度候选，默认读 settings.TEMPLATE_SCALES，用于截屏与模板
        采集尺度不一致的场景（例如 macOS 上截 iOS 镜像窗口）。
        """
        limit = limit or settings.MAX_MATCHES
        threshold = settings.DEFAULT_THRESHOLD if threshold is None else threshold
        scales = tuple(scales if scales is not None else settings.TEMPLATE_SCALES) or (1.0,)

        frame = self._capture.grab_gray(region)
        template = self.load_template(filename)
        fh, fw = frame.image.shape[:2]

        candidates: List[Match] = []
        for scale in scales:
            scaled = self._scaled(template, scale)
            if scaled is None:
                continue
            th, tw = scaled.shape[:2]
            if th > fh or tw > fw:
                continue  # 模板比截图还大，matchTemplate 会抛异常
            result = cv2.matchTemplate(frame.image, scaled, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(result >= threshold)
            for x, y in zip(xs, ys):
                box = Box(
                    x=frame.origin[0] + int(x),
                    y=frame.origin[1] + int(y),
                    w=tw,
                    h=th,
                )
                candidates.append(Match(box=box, score=float(result[y, x]), template=filename))

        candidates.sort(key=lambda m: m.score, reverse=True)
        return self._suppress(candidates, limit)

    @staticmethod
    def _scaled(template: np.ndarray, scale: float) -> Optional[np.ndarray]:
        """按 scale 缩放模板；缩放后过小则返回 None 跳过该尺度。"""
        if abs(scale - 1.0) < 1e-6:
            return template
        h, w = template.shape[:2]
        tw, th = int(round(w * scale)), int(round(h * scale))
        if tw < 8 or th < 8:
            return None
        return cv2.resize(template, (tw, th), interpolation=cv2.INTER_AREA)

    @staticmethod
    def _suppress(candidates: List[Match], limit: int) -> List[Match]:
        """非极大值抑制：距离过近的命中视为同一个目标，只留置信度最高的。"""
        distance = settings.MATCH_MERGE_DISTANCE
        kept: List[Match] = []
        for candidate in candidates:
            cx, cy = candidate.center
            if any(abs(cx - ax) <= distance and abs(cy - ay) <= distance for ax, ay in
                   (k.center for k in kept)):
                continue
            kept.append(candidate)
            if len(kept) >= limit:
                break
        return kept
