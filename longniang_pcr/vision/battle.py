"""战斗画面上的东西：右上角的计时器。

为什么要读它：记录里“打了多少秒”是现实时间，而游戏是 4 倍速在跑，放 UB 动画时计时器又是停的
（2026-11-16 的手动录制：一场打满 90 秒的战斗，现实 91 秒，其中七成在播 UB 动画）——现实秒数主要是在数 UB 动画，
拿它当“打得快不快”会错得离谱。计时器上剩多少秒才是真的。

计时器是 M:SS，白底深灰字，一套单独的数字模板（dig_b_*，做法见 tools/dev/scratch/mktimer.py）。
被特效盖住、读不全就返回 None，不猜。
"""
from __future__ import annotations

import cv2
import numpy as np

from . import hud as HUD
from .pages import PageBook, to_norm

TIMER_BOX = (1072, 22, 49, 23)       # 1280×720 下计时器数字所在的一小块（整块都在白底里面）
TIMER_THR = 0.80                     # 一位数字至少这么像（录制里读对的最低 0.9 左右）
LIMIT = 90                           # 一场战斗的时限（秒）


def read_timer_gray(gray: np.ndarray, tmpls: dict[str, np.ndarray]) -> int | None:
    x, y, w, h = TIMER_BOX
    if len(tmpls) < 10:
        return None
    text, _low = HUD._decode(gray[y:y + h, x:x + w], tmpls, TIMER_THR)
    if len(text) != 3 or int(text[1:]) >= 60 or int(text[0]) > 1:
        return None
    left = int(text[0]) * 60 + int(text[1:])
    return left if left <= LIMIT else None


def read_timer(book: PageBook, img: np.ndarray) -> int | None:
    """战斗画面右上角还剩多少秒；读不出来返回 None。"""
    tm = {d: book.tmpl[f"dig_b_{d}"] for d in "0123456789" if f"dig_b_{d}" in book.tmpl}
    if len(tm) < 10:
        return None
    return read_timer_gray(cv2.cvtColor(to_norm(img), cv2.COLOR_BGR2GRAY), tm)
