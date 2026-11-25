"""单图比对：只判定「当前画面是不是这一张」。

DSL 把界面顺序声明成 steps 之后，每一步只需要拿当前截图和**那一张**目标图比，
不必遍历分组里的全部图片 —— 这是分组有序流转带来的主要收益。

送模型前把两张图的顶部 `settings.JUDGE_MASK_TOP_PIXELS` 像素涂黑：镜像窗口上沿是标题栏，
会透出桌面壁纸，每次都不同，不涂黑会把同一界面判成 0.45 / same_screen=false。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from config import settings
from core.logger import get_logger
from runner import gfx
from runner.errors import RunnerError
from runner.group import ShotRef
from runner.session import Session
from similarity.llm_judge import JudgeError, OmniJudge

log = get_logger(__name__)


@dataclass(frozen=True)
class Verdict:
    """一次判定结果。"""

    matched: bool
    score: float
    same_screen: bool
    elapsed: float
    shot_id: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)

    @property
    def truncated(self) -> bool:
        return bool(self.detail.get("truncated"))

    def describe(self) -> str:
        return "{}「{}」可信度 {:.2f}（{}）".format(
            "命中" if self.matched else "未命中", self.shot_id, self.score,
            self.detail.get("reason") or ("同屏" if self.same_screen else "不同屏"))


class ScreenMatcher:
    """截屏 + 模型判定，并把判定耗时记进自适应等待。"""

    def __init__(
        self,
        session: Session,
        judge: Optional[OmniJudge] = None,
        timer: Optional[Any] = None,
        probe_key: str = "probe",
    ) -> None:
        self.session = session
        self.judge = judge or OmniJudge()
        self.timer = timer
        self.probe_key = probe_key
        self.calls = 0

    @property
    def threshold(self) -> float:
        return self.judge.threshold

    def matches(self, shot: ShotRef) -> Verdict:
        """当前画面是否就是这张截图。"""
        started = time.monotonic()
        pixels = settings.JUDGE_MASK_TOP_PIXELS
        try:
            png, _frame = self.session.grab()
            target: Any = shot.image_path
            if pixels > 0:
                png = gfx.mask_top_png(png, pixels)
                target = gfx.mask_top_png(shot.image_path.read_bytes(), pixels)
            verdict = self.judge.judge(png, target)
        except JudgeError as exc:
            raise RunnerError("模型判定失败：{}".format(exc))
        except OSError as exc:
            raise RunnerError("读取目标截图失败 {}: {}".format(shot.image_path, exc))
        cost = time.monotonic() - started

        self.calls += 1
        if self.timer is not None:
            self.timer.record_probe(self.probe_key, cost)

        score = float(verdict["similarity"])
        same = bool(verdict["same_screen"])
        return Verdict(
            matched=same and score >= self.threshold,
            score=score,
            same_screen=same,
            elapsed=cost,
            shot_id=shot.id,
            detail={
                "confidence": verdict["confidence"],
                "reason": verdict["reason"],
                "a_summary": verdict["a_summary"],
                "b_summary": verdict["b_summary"],
                "differences": verdict["differences"],
                "truncated": verdict["truncated"],
                "threshold": self.threshold,
                "mask_top": pixels,
                "model": verdict["model"],
            },
        )

    def compare(self, left: Any, right: Any) -> Verdict:
        """任意两张图（路径或 PNG 字节）互比。"""
        started = time.monotonic()
        try:
            verdict = self.judge.judge(left, right)
        except JudgeError as exc:
            raise RunnerError("模型判定失败：{}".format(exc))
        cost = time.monotonic() - started
        score = float(verdict["similarity"])
        same = bool(verdict["same_screen"])
        return Verdict(matched=same and score >= self.threshold, score=score,
                       same_screen=same, elapsed=cost, detail=dict(verdict))
