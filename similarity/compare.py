"""图片对比：调用本地 Ollama 视觉模型判定。

算法完全由模型给出，不做 OpenCV 像素比对。

实际执行在 `llm_judge.OmniJudge`：把两张截图 base64 一起发给
`POST {OLLAMA_HOST}/api/chat`（`format: json`、`temperature: 0`），
让模型判断是否同一界面并给出可信度，再解析成前端要的契约。

返回契约（前端只认这几个键）：
    matched  bool   是否比对成功
    score    float  可信度 0~1
    method   str    "ollama:<模型名>"
    message  str    一句话说明
    details  dict   same_screen / similarity / confidence / a_summary /
                    b_summary / differences / reason / elapsed_ms / threshold

换模型不用改代码：环境变量 YYS_OLLAMA_MODEL，或 config/settings.py 的 OLLAMA_MODEL。
模型必须同时支持 completion + vision（`lfm3-omni` 可以；纯 embedding 模型不行，
因为 Ollama 的 /api/embed 会静默丢弃 images 字段）。

自检：
    python -m similarity.llm_judge                  # 只看服务与模型是否可用
    python -m similarity.llm_judge a.png b.png      # 跑一次真实对比
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from similarity.llm_judge import JudgeError, OmniJudge, default_judge

__all__ = ["JudgeError", "OmniJudge", "compare_images"]


def compare_images(
    image_a: Path,
    image_b: Path,
    judge: Optional[OmniJudge] = None,
) -> Dict[str, Any]:
    """比较两张图片。"""
    return (judge or default_judge()).compare(image_a, image_b)
