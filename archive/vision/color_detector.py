"""颜色 / 轮廓检测。

对应旧 utils/Monster.py。用途：地图上会移动的怪物图标，模板匹配太慢，
改用 HSV 颜色阈值 + 腐蚀膨胀去噪 + findContours，速度快很多（README 里的核心思路）。

改进点：
1. 去掉 cv2.imshow（旧代码运行时会弹窗打断脚本），改成 --debug 时存盘标注图；
2. 兼容 OpenCV 3 / 4 的 findContours 返回值差异；
3. 缩放比例按真实截图尺寸计算，不再假设屏幕一定是 1280x800；
4. 保留旧代码的画面分区过滤（避开顶部 HUD 与底部操作栏），但用**比例**表达，
   因此不随分辨率变化；
5. 返回屏幕绝对坐标的 Box，由 actions 层换算成窗口内坐标。
"""
from __future__ import annotations

import time
from typing import List, Optional, Tuple

import cv2
import numpy as np

from config import settings
from core.logger import get_logger
from vision.capture import ScreenCapture
from vision.types import Box, Frame

log = get_logger(__name__)

#: 怪物图标的 HSV 区间（橙红色名字牌）
HSV_MONSTER_LOWER = np.array([7, 169, 30])
HSV_MONSTER_UPPER = np.array([14, 200, 67])
#: 经验怪标记的 HSV 区间
HSV_EXP_LOWER = np.array([5, 59, 170])
HSV_EXP_UPPER = np.array([20, 91, 202])

#: 轮廓最小面积，过滤噪点（检测图是缩小后的，所以阈值很小）
MIN_CONTOUR_AREA = 12
#: 经验怪与怪物配对时允许的最大水平距离（屏幕像素）
MAX_PAIR_DISTANCE_X = 800

#: 画面分区（按高度比例），对应旧代码在 640x400 检测图上的像素阈值：
#: - MIN_Y_RATIO 0.125 <- 旧 lock_monster 的 `if y > 50`，避开顶部 HUD
#: - EXP_MAX_Y_RATIO 0.5 <- 旧 paint_rect 的 `if y_real < 400`，只打上半屏的怪
MIN_Y_RATIO = 0.125
EXP_MAX_Y_RATIO = 0.5

DEBUG_DIR = settings.VAR_DIR / "debug"


def find_contours(binary: np.ndarray) -> List[np.ndarray]:
    """兼容 OpenCV 3（返回 3 个值）与 OpenCV 4（返回 2 个值）。"""
    result = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return list(result[-2]) if len(result) == 3 else list(result[0])


class MonsterDetector:
    """在地图截图里找出可点击的怪物位置。"""

    def __init__(
        self,
        capture: Optional[ScreenCapture] = None,
        detect_size: Optional[Tuple[int, int]] = None,
        debug: bool = False,
    ) -> None:
        self._capture = capture or ScreenCapture()
        self._detect_size = detect_size or settings.DETECT_SIZE
        self._debug = debug

    # ------------------------------------------------------------------ 对外
    def find_monsters(self, exp_only: bool = False) -> List[Box]:
        """返回怪物位置（屏幕绝对坐标 Box）。

        exp_only=True 时只返回「经验怪」：先找经验标记，再配对最近的怪物图标。
        """
        frame = self._capture.grab()
        small, scale_x, scale_y = self._resize(frame)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)

        monsters = self._boxes(
            self._mask(hsv, HSV_MONSTER_LOWER, HSV_MONSTER_UPPER), frame, scale_x, scale_y
        )
        monsters = [b for b in monsters if self._in_band(b, frame)]
        if not exp_only:
            log.info("颜色检测找到 %s 个怪物", len(monsters))
            self._save_debug(frame, monsters, "monster")
            return monsters

        exp_marks = self._boxes(
            self._mask(hsv, HSV_EXP_LOWER, HSV_EXP_UPPER, dilate=(4, 3)), frame, scale_x, scale_y
        )
        paired = [
            b for b in self._pair(exp_marks, monsters)
            if self._in_band(b, frame, max_ratio=EXP_MAX_Y_RATIO)
        ]
        log.info("颜色检测找到 %s 个经验怪（经验标记 %s 个）", len(paired), len(exp_marks))
        self._save_debug(frame, paired, "exp")
        return paired

    # ------------------------------------------------------------------ 内部
    def _resize(self, frame: Frame) -> Tuple[np.ndarray, float, float]:
        """缩放到检测尺寸，返回缩放后图像与「检测图 -> 屏幕」的比例。"""
        detect_w, detect_h = self._detect_size
        small = cv2.resize(frame.image, (detect_w, detect_h), interpolation=cv2.INTER_AREA)
        return small, frame.size[0] / detect_w, frame.size[1] / detect_h

    @staticmethod
    def _mask(
        hsv: np.ndarray,
        lower: np.ndarray,
        upper: np.ndarray,
        dilate: Tuple[int, int] = (8, 2),
    ) -> np.ndarray:
        """颜色阈值 -> 腐蚀去噪 -> 膨胀连通 -> 二值化。"""
        mask = cv2.inRange(hsv, lower, upper)
        mask = cv2.erode(mask, np.ones((2, 2), np.uint8), iterations=1)
        kernel_w, iterations = dilate
        mask = cv2.dilate(mask, np.ones((kernel_w, kernel_w), np.uint8), iterations=iterations)
        _, binary = cv2.threshold(mask, 1, 255, cv2.THRESH_BINARY)
        return binary

    def _boxes(
        self,
        binary: np.ndarray,
        frame: Frame,
        scale_x: float,
        scale_y: float,
    ) -> List[Box]:
        """轮廓 -> 屏幕绝对坐标 Box。"""
        boxes: List[Box] = []
        for contour in find_contours(binary):
            x, y, w, h = cv2.boundingRect(contour)
            if w * h < MIN_CONTOUR_AREA:
                continue
            boxes.append(
                Box(
                    x=frame.origin[0] + int(x * scale_x),
                    y=frame.origin[1] + int(y * scale_y),
                    w=int(w * scale_x),
                    h=int(h * scale_y),
                )
            )
        return boxes

    @staticmethod
    def _in_band(
        box: Box,
        frame: Frame,
        min_ratio: float = MIN_Y_RATIO,
        max_ratio: float = 1.0,
    ) -> bool:
        """目标中心是否落在画面允许的高度区间内（按比例，分辨率无关）。"""
        top = frame.origin[1] + frame.size[1] * min_ratio
        bottom = frame.origin[1] + frame.size[1] * max_ratio
        return top < box.center[1] < bottom

    @staticmethod
    def _pair(exp_marks: List[Box], monsters: List[Box]) -> List[Box]:
        """给每个经验标记配对水平方向最近的怪物（旧 ai_match 逻辑，去掉日志刷屏）。"""
        paired: List[Box] = []
        for exp in exp_marks:
            exp_x, _ = exp.center
            best: Optional[Box] = None
            best_distance = MAX_PAIR_DISTANCE_X
            for monster in monsters:
                distance = abs(monster.center[0] - exp_x)
                if distance < best_distance:
                    best_distance = distance
                    best = monster
            if best is not None:
                paired.append(best)
        return paired

    def _save_debug(self, frame: Frame, boxes: List[Box], tag: str) -> None:
        """把识别框画到截图上存盘，用于调 HSV 阈值（替代旧的 cv2.imshow）。"""
        if not self._debug:
            return
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        annotated = frame.image.copy()
        for index, box in enumerate(boxes, 1):
            x = box.x - frame.origin[0]
            y = box.y - frame.origin[1]
            cv2.rectangle(annotated, (x, y), (x + box.w, y + box.h), (0, 0, 255), 2)
            cv2.putText(annotated, str(index), (x, max(y - 5, 14)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        path = DEBUG_DIR / "{}_{}.png".format(tag, int(time.time()))
        cv2.imwrite(str(path), annotated)
        log.debug("识别调试图已保存: %s（%s 个目标）", path, len(boxes))
