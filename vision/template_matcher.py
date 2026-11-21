"""模板匹配。

对应旧 utils/MapCv.py 的 __in_screenshot__ / location_screen / location_multiscreen。
改进点：
1. 模板图片只读一次并缓存（旧代码每次识别都 cv2.imread）；
2. 路径来自 config.settings.TEMPLATE_DIR，不再写死 E:/github/...；
3. 命中结果做非极大值抑制，同一个按钮不会返回几十个重复点；
4. 返回 Box（含左上角 + 宽高），既能取中心点也能复现旧的右下角行为；
5. 多尺度匹配前按「缩放后的绝对像素下限」筛掉不可信的尺度（见 vision/scales.py）——
   模板缩到几十像素就没有判别力，会在任意画面上撞出高分假命中，脚本照着点就是乱点。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import cv2
import numpy as np

from config import settings
from core.errors import ConfigError
from core.logger import get_logger
from vision.capture import ScreenCapture
from vision.scales import usable_scales
from vision.types import Box, Match

log = get_logger("vision.template_matcher")


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
        #: 已经提示过「这张模板可能截错了比例」的名字，避免每次识图都刷一条 warning
        self._warned: Set[str] = set()

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

        scales 为模板尺度候选，默认读 settings.TEMPLATE_SCALES；实际尝试的尺度还会
        按模板尺寸过滤一遍（`_usable`），缩放后小于像素下限的一律不用。
        """
        limit = limit or settings.MAX_MATCHES
        threshold = settings.DEFAULT_THRESHOLD if threshold is None else threshold
        requested = tuple(scales if scales is not None else settings.TEMPLATE_SCALES) or (1.0,)

        frame = self._capture.grab_gray(region)
        template = self.load_template(filename)
        fh, fw = frame.image.shape[:2]
        scales, dropped = self._usable(template, requested)

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

        if not candidates:
            # 一个都没匹配上才值得喊；筛掉过尺度本身不是错误（大模板只需要 1.0）
            self._warn_unmatched(filename, template, requested, dropped)
        candidates.sort(key=lambda m: m.score, reverse=True)
        return self._suppress(candidates, limit)

    @staticmethod
    def _scaled(template: np.ndarray, scale: float) -> Optional[np.ndarray]:
        """按 scale 缩放模板；缩放后低于像素下限则返回 None 跳过该尺度。"""
        if abs(scale - 1.0) < 1e-6:
            return template
        h, w = template.shape[:2]
        tw, th = int(round(w * scale)), int(round(h * scale))
        if tw < settings.MIN_SCALED_TEMPLATE_SIDE or th < settings.MIN_SCALED_TEMPLATE_SIDE:
            return None
        return cv2.resize(template, (tw, th), interpolation=cv2.INTER_AREA)

    @staticmethod
    def _usable(template: np.ndarray,
                scales: Sequence[float]) -> Tuple[Tuple[float, ...], Tuple[float, ...]]:
        """返回（可用尺度, 被筛掉的尺度）。

        筛掉的典型例子：41x51 的模板在 0.5 尺度只剩 20x25 像素，那种块在任何画面上
        都能撞上 0.9+ 的分数（真机就照着它在探索章节界面上反复点同一个空白处）。
        """
        kept = usable_scales(template.shape[1], template.shape[0], scales)
        dropped = tuple(scale for scale in scales if scale not in kept)
        return kept, dropped

    def _warn_unmatched(self, filename: str, template: np.ndarray,
                        requested: Tuple[float, ...], dropped: Tuple[float, ...]) -> None:
        """模板在所有可用尺度上都没命中，且有尺度被下限筛掉 -> 提示可能截错了比例。

        这两个条件必须同时成立才 warn：只被筛掉尺度但照样命中的模板（例如 56x55 的
        挑战按钮不需要 0.4 尺度）不该被报出来，否则每次挂机都在刷无效告警。
        """
        if not dropped or filename in self._warned:
            return
        self._warned.add(filename)
        log.warning(
            "模板 %s（%dx%d）在可用尺度 %s 上都没匹配到（%s 因缩放后小于 %d 像素被跳过）："
            "若这个界面本该被识别出来，说明这张模板不是按当前窗口比例截的，"
            "请用 tools/asset_manager 从实时窗口重新截图",
            filename, template.shape[1], template.shape[0],
            "/".join("{:.1f}".format(item) for item in requested if item not in dropped) or "无",
            "/".join("{:.1f}".format(item) for item in dropped),
            settings.MIN_SCALED_TEMPLATE_SIDE)

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
