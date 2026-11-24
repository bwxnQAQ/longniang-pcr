"""地图画面上的四个数字：左下角的“角色”数、“迷宫遗物”数，顶栏的宝箱数、金币数。

算当前分数（角色、遗物进分数公式）和以后在商店花钱都要用。数字很小（720p 下 13 像素高），做法是：
每个数字一张模板（连同描边），在那一小块区域里滑动匹配，再挑一组互不重叠、总分最高的，从左到右连成数。
读不出来（某一位不够像，或者一位都没找到）就返回 None，不猜。
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .pages import PageBook, to_norm

# 名字 → （区域 x, y, w, h，字体："s" 左下角白字黑边 / "t" 顶栏深色字白边）
FIELDS = {"chars": ((70, 650, 56, 32), "s"), "relics": ((162, 650, 56, 32), "s"),
          "chests": ((905, 16, 64, 34), "t"), "coins": ((1040, 16, 132, 34), "t")}
DIGIT_THR = {"s": 0.72, "t": 0.80}   # 一位数字至少这么像。录制里认对的最低：左下角 0.78，顶栏 0.84；别的数字套上去最高 0.57。
                                     # 顶栏不能再低：0.72 时“1”会被更宽的“4”模板抢走（14,180 读成 44,180）
OVERLAP = 5               # 相邻两位的模板可以重叠这么多像素（模板带着 2 像素描边，挨着的数字描边是贴在一起的）


@dataclass
class Hud:
    chars: int | None = None
    relics: int | None = None
    chests: int | None = None
    coins: int | None = None

    def as_dict(self) -> dict:
        return {"chars": self.chars, "relics": self.relics, "chests": self.chests, "coins": self.coins}


def _decode(roi: np.ndarray, tmpls: dict[str, np.ndarray], thr: float) -> tuple[str, float]:
    """在一小块灰度图里读一串数字：返回（数字串, 其中最低的一位相似度）。读不出返回 ("", 0)。"""
    cands: list[tuple[int, int, float, str]] = []          # (左, 右, 相似度, 数字)
    for d, t in tmpls.items():
        if roi.shape[0] < t.shape[0] or roi.shape[1] < t.shape[1]:
            continue
        res = cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED)
        best = res.max(axis=0)                             # 每个横向位置上（任意高度）最高的相似度
        for x in range(best.shape[0]):
            s = float(best[x])
            if s >= thr and s >= best[max(0, x - 2):x + 3].max() - 1e-6:
                cands.append((x, x + t.shape[1], s, d))
    if not cands:
        return "", 0.0
    cands.sort(key=lambda c: c[1])
    # 带权区间调度：挑互不重叠（允许 OVERLAP 像素）的一组，使 Σ (相似度 − 0.5)×宽度 最大。
    # 减掉 0.5 是为了让“很像的窄数字”赢过“勉强像的宽数字”
    score = [0.0] * len(cands)
    prev = [-1] * len(cands)
    for i, (l, r, s, d) in enumerate(cands):
        w = (s - 0.5) * (r - l)
        score[i] = w
        for j in range(i):
            if cands[j][1] - OVERLAP <= l and cands[j][0] < l and score[j] + w > score[i]:
                score[i], prev[i] = score[j] + w, j
    i = int(np.argmax(score))
    picked = []
    while i >= 0:
        picked.append(cands[i])
        i = prev[i]
    picked.reverse()
    return "".join(c[3] for c in picked), min(c[2] for c in picked)


def read_field(book: PageBook, gray: np.ndarray, name: str) -> tuple[int | None, float]:
    (x, y, w, h), fam = FIELDS[name]
    tm = {d: book.tmpl[f"dig_{fam}_{d}"] for d in "0123456789" if f"dig_{fam}_{d}" in book.tmpl}
    if len(tm) < 10:
        return None, 0.0
    text, low = _decode(gray[y:y + h, x:x + w], tm, DIGIT_THR[fam])
    if not text or len(text) > 6 or (len(text) > 1 and text[0] == "0"):
        return None, low
    return int(text), low


def read_hud(book: PageBook, img: np.ndarray) -> Hud:
    """读地图上的四个数字。只在画面确实是地图时调用；哪个读不出来哪个就是 None。"""
    gray = cv2.cvtColor(to_norm(img), cv2.COLOR_BGR2GRAY)
    return Hud(**{name: read_field(book, gray, name)[0] for name in FIELDS})
