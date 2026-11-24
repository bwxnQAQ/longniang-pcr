"""图片读写：一律“先读成字节再解码 / 先编码再写字节”。

OpenCV 的 imread / imwrite 在 Windows 上走的是系统 ANSI 编码的文件接口，路径里
有中文时会读不到文件，或者写出一个文件名乱码的文件。项目里所有图片读写都必须
走这里，不要直接调用 cv2.imread / cv2.imwrite。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def imread(path: str | Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray | None:
    data = np.frombuffer(Path(path).read_bytes(), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def encode(img: np.ndarray, ext: str = ".png", params: list[int] | None = None) -> bytes:
    ok, buf = cv2.imencode(ext, img, params or [])
    if not ok:
        raise ValueError(f"图片编码失败：{ext}")
    return buf.tobytes()


def imwrite(path: str | Path, img: np.ndarray, params: list[int] | None = None) -> int:
    """写图片，返回写入的字节数。格式由扩展名决定。"""
    p = Path(path)
    data = encode(img, p.suffix or ".png", params)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return len(data)


PNG_FAST = [cv2.IMWRITE_PNG_COMPRESSION, 1]
JPG_90 = [cv2.IMWRITE_JPEG_QUALITY, 90]
