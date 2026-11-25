"""图形算法库：在分组 DSL 里直接调用。

DSL 文件不需要 import 本模块 —— 加载时已把 `gfx` 注入到它的命名空间，
直接写 `gfx.brightness(png)` 即可。要加自己的算法，在本文件里加一个函数就行。

所有函数都接受三种入参：PNG/JPEG 字节、图片路径、或已解码的 numpy 数组，
返回值一律是纯数字 / 纯数组，方便在 DSL 的条件表达式里直接用。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence, Tuple, Union

Image = Union[Path, str, bytes, bytearray, Any]
Box = Tuple[int, int, int, int]


def _cv2():
    import cv2

    return cv2


def _np():
    import numpy as np

    return np


def decode(image: Image) -> Any:
    """解码成 BGR 数组。"""
    np = _np()
    cv2 = _cv2()
    if isinstance(image, (bytes, bytearray)):
        buffer = np.frombuffer(bytes(image), np.uint8)
        array = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if array is None:
            raise ValueError("无法把这段字节解码成图片")
        return array
    if isinstance(image, (str, Path)):
        array = cv2.imread(str(image), cv2.IMREAD_COLOR)
        if array is None:
            raise ValueError("图片读取失败: {}".format(image))
        return array
    return image


def encode_png(array: Any) -> bytes:
    """BGR 数组编码成 PNG 字节。"""
    cv2 = _cv2()
    ok, buffer = cv2.imencode(".png", array)
    if not ok:
        raise ValueError("PNG 编码失败")
    return buffer.tobytes()


def size(image: Image) -> Tuple[int, int]:
    """宽高。"""
    height, width = decode(image).shape[:2]
    return int(width), int(height)


def gray(image: Image) -> Any:
    """灰度数组。"""
    cv2 = _cv2()
    return cv2.cvtColor(decode(image), cv2.COLOR_BGR2GRAY)


def brightness(image: Image) -> float:
    """平均亮度 0~255。"""
    return float(gray(image).mean())


def saturation(image: Image) -> float:
    """平均饱和度 0~255。"""
    cv2 = _cv2()
    hsv = cv2.cvtColor(decode(image), cv2.COLOR_BGR2HSV)
    return float(hsv[:, :, 1].mean())


def crop(image: Image, box: Box) -> Any:
    """按 (x, y, w, h) 裁一块。"""
    array = decode(image)
    x, y, w, h = (int(v) for v in box)
    height, width = array.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("裁剪区域 {} 落在图片 {}x{} 之外".format(box, width, height))
    return array[y0:y1, x0:x1]


def resize(image: Image, width: int, height: int) -> Any:
    """缩放到指定尺寸。"""
    cv2 = _cv2()
    return cv2.resize(decode(image), (int(width), int(height)), interpolation=cv2.INTER_AREA)


def align(a: Image, b: Image) -> Tuple[Any, Any]:
    """把两张图对齐到同一尺寸。"""
    left, right = decode(a), decode(b)
    if left.shape[:2] != right.shape[:2]:
        height, width = left.shape[:2]
        right = resize(right, width, height)
    return left, right


def mean_pixel_diff(a: Image, b: Image) -> float:
    """平均像素差 0~255，越小越像。"""
    np = _np()
    left, right = align(a, b)
    lg = np.asarray(left, dtype=np.int16)
    rg = np.asarray(right, dtype=np.int16)
    return float(np.abs(lg - rg).mean())


def histogram_similarity(a: Image, b: Image, bins: int = 64) -> float:
    """灰度直方图相关性 -1~1，1 表示分布一致。"""
    cv2 = _cv2()
    left, right = align(a, b)
    hl = cv2.calcHist([left], [0], None, [bins], [0, 256])
    hr = cv2.calcHist([right], [0], None, [bins], [0, 256])
    cv2.normalize(hl, hl)
    cv2.normalize(hr, hr)
    return float(cv2.compareHist(hl, hr, cv2.HISTCMP_CORREL))


def changed_ratio(a: Image, b: Image, tolerance: int = 12) -> float:
    """变化像素占比 0~1。"""
    np = _np()
    left, right = align(a, b)
    diff = np.abs(np.asarray(left, np.int16) - np.asarray(right, np.int16)).max(axis=2)
    return float((diff > int(tolerance)).mean())


def is_mostly_dark(image: Image, threshold: float = 60.0) -> bool:
    """画面是否整体偏暗。"""
    return brightness(image) < float(threshold)


def color_ratio(image: Image, lower: Sequence[int], upper: Sequence[int]) -> float:
    """HSV 区间内的像素占比 0~1。"""
    cv2 = _cv2()
    np = _np()
    hsv = cv2.cvtColor(decode(image), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(lower, np.uint8), np.array(upper, np.uint8))
    return float(mask.mean() / 255.0)


def center_of(box: Box) -> Tuple[int, int]:
    """矩形中心点。"""
    x, y, w, h = (int(v) for v in box)
    return x + w // 2, y + h // 2


def scale_point(point: Sequence[float], from_size: Sequence[int],
                to_size: Sequence[int]) -> Tuple[int, int]:
    """把坐标从一种尺寸换算到另一种。"""
    fw, fh = int(from_size[0]), int(from_size[1])
    tw, th = int(to_size[0]), int(to_size[1])
    if fw <= 0 or fh <= 0:
        raise ValueError("源尺寸必须为正数: {}".format(from_size))
    return int(round(point[0] * tw / fw)), int(round(point[1] * th / fh))


def describe(image: Image) -> str:
    """一行摘要，写日志用。"""
    width, height = size(image)
    return "{}x{} 亮度{:.0f} 饱和{:.0f}".format(width, height, brightness(image),
                                              saturation(image))


def mask_top(image: Image, pixels: int) -> Any:
    """把图片顶部 pixels 行涂黑，尺寸不变。"""
    array = decode(image)
    height = int(array.shape[0])
    cut = max(0, min(height, int(pixels)))
    if cut == 0:
        return array
    masked = array.copy()
    masked[:cut] = 0
    return masked


def mask_top_png(png: bytes, pixels: int) -> bytes:
    """PNG 字节顶部涂黑后重新编码；pixels<=0 时原样返回。"""
    if int(pixels) <= 0:
        return png
    return encode_png(mask_top(png, pixels))


HELPERS = {
    "decode": decode,
    "encode_png": encode_png,
    "size": size,
    "gray": gray,
    "brightness": brightness,
    "saturation": saturation,
    "crop": crop,
    "resize": resize,
    "align": align,
    "mean_pixel_diff": mean_pixel_diff,
    "histogram_similarity": histogram_similarity,
    "changed_ratio": changed_ratio,
    "is_mostly_dark": is_mostly_dark,
    "color_ratio": color_ratio,
    "center_of": center_of,
    "scale_point": scale_point,
    "describe": describe,
    "mask_top": mask_top,
    "mask_top_png": mask_top_png,
}
