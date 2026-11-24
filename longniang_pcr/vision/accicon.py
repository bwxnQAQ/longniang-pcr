"""按图标认饰品（2026-11-24）。【正式】

为什么要有：战利品清单上的名字是文字识别读的，名字中间那个 α 常常读不准，“火 / 水 / 风 / 光 / 暗”又只有一个字——
读错一个字就成了另一件。图标是游戏自己画的，同一件饰品在哪儿都是同一张图，拿它再对一遍，名字和图标对得上才算认准。

模板：50 件饰品每件一张，从用户 2026-11-24 20:00 那段录制的「公会详情 → 可以获得的报酬」里裁的（tools/dev/scratch/mkaccicons.py），
存在 assets/accessories/icons.npz。图标在清单里是 80×80（1280×720 的画面），模板只取里面 64×52 的一块：避开左上角每件都一样的「EX」角标和外框。
「获得道具」和「公会详情」两张清单是同一种排法：图标一样大，只是「获得道具」的整体靠左几个像素（旧录制里的「特别装备炼成点数」图标对过）。

认法：在清单左边图标那一竖条里，拿 50 张模板挨个比（比的是彩色图，所以同一个系列里五种属性靠颜色分得开）；
某个位置上最像的那张够像（SCORE）、而且比第二像的“另一件”明显更像（MARGIN），才算。被清单上下边缘切掉一截的图标不认。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .. import accessories as AC
from .. import paths

ICON = 80                               # 图标边长
INNER = (8, 20, 64, 52)                 # 模板 = 图标里的这一块（左、上、宽、高）
X_RANGE = (352, 380)                    # 图标左边缘可能落在的 x（获得道具 ≈ 363，公会详情 ≈ 368）
Y_RANGE = (118, 600)                    # 清单的上下范围（标题、说明那一行以下，「关闭」以上）
SCORE = 0.75                            # 至少这么像（真机画面挪位置、压成 JPEG 以后最低 0.90；不是饰品的画面最高 0.44）
MARGIN = 0.05                           # 比第二像的另一件至少高这么多（实测最少高 0.10）
FILE = Path("assets") / "accessories" / "icons.npz"

_CACHE: dict[str, dict[str, np.ndarray]] = {}


@dataclass(frozen=True)
class Hit:
    acc: AC.Acc
    score: float
    second: float                       # 第二像的另一件有多像
    box: tuple[int, int, int, int]      # 整个图标的位置（1280×720）

    @property
    def cy(self) -> float:
        return self.box[1] + self.box[3] / 2.0


def load(path: str | Path | None = None) -> dict[str, np.ndarray]:
    """读模板。文件不在（或者坏了）返回空——那就只靠名字认。"""
    p = Path(path) if path else paths.PROJECT_ROOT / FILE
    key = str(p)
    if key not in _CACHE:
        out: dict[str, np.ndarray] = {}
        try:
            with np.load(p) as z:
                for k in z.files:
                    if k in AC.BY_KEY and z[k].shape == (INNER[3], INNER[2], 3):
                        out[k] = np.ascontiguousarray(z[k])
        except Exception:  # noqa: BLE001
            out = {}
        _CACHE[key] = out
    return _CACHE[key]


def available(path: str | Path | None = None) -> bool:
    return len(load(path)) > 0


def inner_of(norm: np.ndarray, x: int, y: int) -> np.ndarray:
    """图标左上角在 (x, y)：把当模板用的那一块裁出来。"""
    dx, dy, w, h = INNER
    return norm[y + dy:y + dy + h, x + dx:x + dx + w].copy()


def find(norm: np.ndarray, tpls: dict[str, np.ndarray] | None = None, score: float = SCORE, margin: float = MARGIN) -> list[Hit]:
    """在一屏清单（1280×720）里找饰品图标。从上到下返回。"""
    tpls = load() if tpls is None else tpls
    if not tpls or norm is None or norm.shape[0] < Y_RANGE[1] or norm.shape[1] < X_RANGE[1] + ICON:
        return []
    dx, dy, w, h = INNER
    x0, x1 = X_RANGE[0] + dx, X_RANGE[1] + dx + w
    y0, y1 = Y_RANGE[0], Y_RANGE[1]
    strip = np.ascontiguousarray(norm[y0:y1, x0:x1])
    keys = list(tpls)
    maps = np.stack([cv2.matchTemplate(strip, tpls[k], cv2.TM_CCOEFF_NORMED) for k in keys])      # (件数, 竖直位置, 水平位置)
    per_y = maps.max(axis=2)                    # 每件饰品在每个竖直位置上最像的程度
    top = per_y.max(axis=0)
    hits: list[Hit] = []
    used = np.zeros(top.shape[0], bool)
    for y in np.argsort(-top):
        if top[y] < score:
            break
        if used[max(0, y - ICON // 2):y + ICON // 2].any():
            continue
        used[max(0, y - ICON // 2):y + ICON // 2] = True
        lo, hi = max(0, y - 3), y + 4
        local = per_y[:, lo:hi].max(axis=1)      # 这个位置附近每件有多像
        order = np.argsort(-local)
        best, second = int(order[0]), float(local[order[1]]) if len(order) > 1 else 0.0
        if local[best] - second < margin:
            continue
        x = int(maps[best, y].argmax())
        hits.append(Hit(AC.BY_KEY[keys[best]], float(local[best]), second, (x0 + x - dx, y0 + int(y) - dy, ICON, ICON)))
    return sorted(hits, key=lambda t: t.box[1])
