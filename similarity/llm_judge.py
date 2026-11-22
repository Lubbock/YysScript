"""Ollama 多模态模型客户端。"""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import settings

PROMPT = """第一张图是 A，第二张图是 B，都是手机截图。判断它们是否为同一个界面。
同一功能页面即算同一界面；动画帧、数值、时间、滚动位置的细微差异不算不同界面。

只输出 JSON，不要任何解释文字。字段要求：
{"same_screen": true/false, "similarity": 0.00-1.00 的相似程度（要体现细微差别，禁止只输出 0.45/0.99 这类整数档）, "confidence": 0.00-1.00 你对 same_screen 的把握, "a_summary": "不超过12字", "b_summary": "不超过12字", "differences": ["最多2条，每条不超过15字，无差异则空数组"], "reason": "不超过30字"}"""

MAX_IMAGE_BYTES = 30 * 1024 * 1024
TEXT_LIMITS = {"a_summary": 80, "b_summary": 80, "reason": 200}
DIFF_LIMIT = 40


class JudgeError(Exception):
    """模型判定失败。"""


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return min(1.0, max(0.0, number))


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _string_list(value: Any, limit: int = DIFF_LIMIT, max_items: int = 8) -> List[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:max_items]:
        text = _text(item, limit)
        if text:
            out.append(text)
    return out


def salvage_json(raw: str) -> Tuple[Dict[str, Any], bool]:
    """解析模型输出，截断时按字段抢救。"""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    decoder = json.JSONDecoder()
    start = text.find("{")
    if start >= 0:
        try:
            data, _end = decoder.raw_decode(text, start)
            if isinstance(data, dict):
                return data, False
        except ValueError:
            pass

    partial: Dict[str, Any] = {}
    flag = re.search(r'"same_screen"\s*:\s*(true|false)', text, re.I)
    if flag:
        partial["same_screen"] = flag.group(1).lower() == "true"
    for key in ("similarity", "confidence"):
        found = re.search(r'"{}"\s*:\s*(-?[0-9.]+)'.format(key), text)
        if found:
            try:
                partial[key] = float(found.group(1))
            except ValueError:
                pass
    for key in ("a_summary", "b_summary", "reason"):
        found = re.search(r'"{}"\s*:\s*"((?:[^"\\]|\\.)*)(?:"|$)'.format(key), text)
        if found:
            partial[key] = found.group(1)
    found = re.search(r'"differences"\s*:\s*\[(.*?)(?:\]|$)', text, re.S)
    if found:
        partial["differences"] = [
            item.strip().strip('"') for item in found.group(1).split(",") if item.strip().strip('"')
        ]
    if not partial:
        raise JudgeError("模型输出不是可解析的 JSON：{}".format(text[:160] or "（空）"))
    return partial, True


class OmniJudge:
    """调用 Ollama 视觉模型判定两张图。"""

    def __init__(
        self,
        host: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        keep_alive: Optional[str] = None,
        num_predict: Optional[int] = None,
        threshold: Optional[float] = None,
    ) -> None:
        self.host = (host or settings.OLLAMA_HOST).rstrip("/")
        self.model = model or settings.OLLAMA_MODEL
        self.timeout = float(timeout if timeout is not None else settings.OLLAMA_TIMEOUT)
        self.keep_alive = keep_alive or settings.OLLAMA_KEEP_ALIVE
        self.num_predict = int(num_predict or settings.OLLAMA_NUM_PREDICT)
        self.threshold = float(
            threshold if threshold is not None else settings.SIMILARITY_MATCH_THRESHOLD
        )

    def _request(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self.host + path
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:300].decode("utf-8", "replace")
            raise JudgeError("Ollama 返回 HTTP {}：{}".format(exc.code, detail))
        except urllib.error.URLError as exc:
            raise JudgeError(
                "连不上 Ollama（{}）：{}。请确认已启动：ollama serve".format(self.host, exc.reason)
            )
        except TimeoutError:
            raise JudgeError("Ollama 请求超时（{} 秒）".format(self.timeout))
        except OSError as exc:
            raise JudgeError("请求 Ollama 失败 {}: {}".format(type(exc).__name__, exc))
        try:
            return json.loads(body)
        except ValueError as exc:
            raise JudgeError("Ollama 响应不是 JSON：{}".format(exc))

    def health(self) -> Dict[str, Any]:
        """探测服务与模型可用性。"""
        info: Dict[str, Any] = {
            "host": self.host,
            "model": self.model,
            "timeout": self.timeout,
            "threshold": self.threshold,
            "ok": False,
            "reachable": False,
            "found": False,
            "vision": False,
            "version": None,
            "capabilities": [],
            "error": "",
        }
        try:
            info["version"] = self._request("/api/version").get("version")
            info["reachable"] = True
        except JudgeError as exc:
            info["error"] = str(exc)
            return info

        try:
            models = self._request("/api/tags").get("models") or []
        except JudgeError as exc:
            info["error"] = str(exc)
            return info

        base = self.model.split(":")[0]
        entry = None
        for item in models:
            name = item.get("name", "")
            if name == self.model or name.split(":")[0] == base:
                entry = item
                info["model"] = name
                break
        if entry is None:
            names = ", ".join(sorted(m.get("name", "") for m in models)) or "（空）"
            info["error"] = "模型 {} 不存在。已安装：{}。拉取：ollama pull {}".format(
                self.model, names, self.model
            )
            return info

        info["found"] = True
        caps = entry.get("capabilities") or []
        info["capabilities"] = list(caps)
        info["vision"] = "vision" in caps
        if "completion" not in caps:
            info["error"] = "模型 {} 不支持 completion（只有 {}），无法做图片判定".format(
                info["model"], ", ".join(caps) or "无"
            )
            return info
        if not info["vision"]:
            info["error"] = "模型 {} 没有 vision 能力，看不到图片".format(info["model"])
            return info
        info["ok"] = True
        return info

    def _encode(self, path: Path) -> str:
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            raise JudgeError("读取图片失败 {}: {}".format(path, exc))
        if not data:
            raise JudgeError("图片为空: {}".format(path))
        if len(data) > MAX_IMAGE_BYTES:
            raise JudgeError("图片过大（{:.1f} MB），上限 {} MB".format(
                len(data) / 1048576, MAX_IMAGE_BYTES // 1048576))
        return base64.b64encode(data).decode("ascii")

    def judge(self, image_a: Path, image_b: Path) -> Dict[str, Any]:
        """让模型判定两张图，返回原始字段。"""
        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": PROMPT,
                "images": [self._encode(image_a), self._encode(image_b)],
            }],
            "stream": False,
            "format": "json",
            "keep_alive": self.keep_alive,
            "options": {"temperature": 0, "num_predict": self.num_predict},
        }
        started = time.monotonic()
        try:
            body = self._request("/api/chat", payload)
        except JudgeError as exc:
            message = str(exc)
            if "does not support" in message:
                raise JudgeError(
                    "模型 {} 不支持图文对话。请换成同时支持 completion + vision 的模型，"
                    "例如 ollama pull lfm3-omni，然后设 YYS_OLLAMA_MODEL。".format(self.model)
                )
            raise
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)

        content = ((body.get("message") or {}).get("content") or "").strip()
        if not content:
            raise JudgeError("模型返回空内容（done_reason={}）".format(body.get("done_reason")))
        data, truncated = salvage_json(content)

        same = data.get("same_screen")
        if not isinstance(same, bool):
            same = str(same).strip().lower() in ("true", "1", "yes")
        similarity = _clamp01(data.get("similarity"), _clamp01(data.get("confidence"), 0.5))
        confidence = _clamp01(data.get("confidence"), similarity)
        return {
            "same_screen": same,
            "similarity": similarity,
            "confidence": confidence,
            "a_summary": _text(data.get("a_summary"), TEXT_LIMITS["a_summary"]),
            "b_summary": _text(data.get("b_summary"), TEXT_LIMITS["b_summary"]),
            "differences": _string_list(data.get("differences")),
            "reason": _text(data.get("reason"), TEXT_LIMITS["reason"]),
            "truncated": truncated,
            "elapsed_ms": elapsed_ms,
            "model": self.model,
            "done_reason": body.get("done_reason"),
        }

    def compare(self, image_a: Path, image_b: Path) -> Dict[str, Any]:
        """判定并组装成对比接口契约。"""
        verdict = self.judge(image_a, image_b)
        score = verdict["similarity"]
        matched = bool(verdict["same_screen"]) and score >= self.threshold
        inconsistent = bool(verdict["same_screen"]) != (score >= self.threshold)

        if matched:
            message = "模型判定为同一界面（可信度 {:.0%}）".format(score)
        elif verdict["same_screen"]:
            message = "模型判定为同一界面，但相似度 {:.0%} 低于阈值 {:.0%}".format(
                score, self.threshold)
        else:
            message = "模型判定不是同一界面（相似度 {:.0%}）".format(score)
        if verdict["reason"]:
            message = "{}：{}".format(message, verdict["reason"])

        return {
            "matched": matched,
            "score": round(score, 4),
            "method": "ollama:{}".format(self.model),
            "message": message,
            "details": {
                "same_screen": verdict["same_screen"],
                "similarity": verdict["similarity"],
                "confidence": verdict["confidence"],
                "a_summary": verdict["a_summary"],
                "b_summary": verdict["b_summary"],
                "differences": verdict["differences"],
                "reason": verdict["reason"],
                "model": verdict["model"],
                "elapsed_ms": verdict["elapsed_ms"],
                "truncated": verdict["truncated"],
                "threshold": self.threshold,
                "inconsistent": inconsistent,
            },
        }


def default_judge() -> OmniJudge:
    """按 settings 构造客户端。"""
    return OmniJudge()


def _selftest() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Ollama 视觉模型自检")
    parser.add_argument("--host", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("images", nargs="*", help="两张图片路径，给了就跑一次真实对比")
    args = parser.parse_args()

    judge = OmniJudge(host=args.host, model=args.model)
    info = judge.health()
    print("服务 : {}".format(info["host"]))
    print("版本 : {}".format(info["version"]))
    print("模型 : {}  存在={}  能力={}".format(
        info["model"], info["found"], ", ".join(info["capabilities"]) or "无"))
    print("可用 : {}{}".format("是" if info["ok"] else "否",
                          "" if info["ok"] else "（{}）".format(info["error"])))
    if not info["ok"]:
        return 1
    if len(args.images) != 2:
        print("\n提示：传两张图片路径可跑真实对比，例如 python -m similarity.llm_judge a.png b.png")
        return 0

    try:
        result = judge.compare(Path(args.images[0]), Path(args.images[1]))
    except JudgeError as exc:
        print("对比失败：{}".format(exc))
        return 1
    print("\n判定 : {}".format("同一界面" if result["matched"] else "不是同一界面"))
    print("可信度: {:.1%}".format(result["score"]))
    print("说明 : {}".format(result["message"]))
    print("详情 : {}".format(json.dumps(result["details"], ensure_ascii=False, indent=2)))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_selftest())
