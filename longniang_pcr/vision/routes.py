"""格子之间的连线：哪一格能走到下一列的哪一格。

地图上相邻两列的格子之间画着连线（灰紫色的带子，深色描边）。只有从你脚下那格出发的连线会发亮，其余都是同一种暗色。
这里认的是暗色的那种：先按颜色做出“连线像素”的蒙版，再沿着两格之间该有连线的位置量一遍，
一路上大部分都是连线像素才算有。

连线的位置是在 2026-11-16 那局录制上量出来的（1280×720 坐标）：
- 连线中心比格子的标签中心高 21 像素；
- 斜线不是严格的“中心连中心”：在离开左边格子 80 像素处，比中心连中心低 0.205×高度差；
  在离右边格子 80 像素处，高 0.155×高度差。在这附近 ±12 像素找最贴合的位置。
在那局录制的 46 对“走过才知道答案”的格子上核对：有连线的得分都在 0.89 以上，没有的都在 0.54 以下。
"""
from __future__ import annotations

import cv2
import numpy as np

from .pages import to_norm

LINE_DY = 21
X_IN = 80                   # 平台半宽：只量两个平台之间的那一段
EDGE_THR = 0.72
_KERNEL = np.ones((5, 5), np.uint8)


def line_mask(img: np.ndarray) -> np.ndarray:
    norm = to_norm(img)
    b = norm[..., 0].astype(np.int16)
    g = norm[..., 1].astype(np.int16)
    r = norm[..., 2].astype(np.int16)
    m = (np.abs(b - 128) <= 16) & (g >= 40) & (g <= 122) & (r >= 55) & (r <= 132) & (b - g >= 12) & (b - r >= 8)
    return cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, _KERNEL)


def _seg_score(mask: np.ndarray, p0: tuple[float, float], p1: tuple[float, float], half: int = 5) -> float:
    length = int(np.hypot(p1[0] - p0[0], p1[1] - p0[1]))
    if length < 20:
        return 0.0
    t = np.linspace(0.0, 1.0, length)
    ux, uy = (p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length
    xs = p0[0] + (p1[0] - p0[0]) * t
    ys = p0[1] + (p1[1] - p0[1]) * t
    h, w = mask.shape
    ks = np.arange(-half, half + 1)[:, None]
    xi = np.rint(xs[None, :] - uy * ks).astype(int)
    yi = np.rint(ys[None, :] + ux * ks).astype(int)
    ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
    acc = (mask[np.clip(yi, 0, h - 1), np.clip(xi, 0, w - 1)] * ok).sum(axis=0)
    return float((acc >= 0.7 * (2 * half + 1)).mean())


def pair_score(mask: np.ndarray, a: tuple[int, int], b: tuple[int, int], tol: int = 12, step: int = 4) -> float:
    """a=(x, 标签中心高度) 到右边一列的 b 之间有连线的把握（0～1）。"""
    dy = b[1] - a[1]
    ma, mb = 0.205 * dy, -0.155 * dy
    ax, bx = a[0] + X_IN, b[0] - X_IN
    best = 0.0
    for oa in range(-tol, tol + 1, step):
        for ob in range(-tol, tol + 1, step):
            s = _seg_score(mask, (ax, a[1] - LINE_DY + ma + oa), (bx, b[1] - LINE_DY + mb + ob))
            if s > best:
                best = s
    return best


def column_edges(mask: np.ndarray, xa: int, rows_a: tuple[int, ...], xb: int, rows_b: tuple[int, ...]) -> dict[tuple[int, int], float]:
    """相邻两列之间每一对格子的连线得分。最上和最下之间从来不连，直接跳过。"""
    out: dict[tuple[int, int], float] = {}
    for la in rows_a:
        for lb in rows_b:
            if abs(lb - la) > 300:
                continue
            out[(la, lb)] = round(pair_score(mask, (xa, la), (xb, lb)), 3)
    return out
