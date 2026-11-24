"""页面识别。

思路（来自阶段 0 的两段录制）：
- 所有画面先缩到 1280×720 再比对，规则和模板都按这个尺寸写；返回给外面的坐标换算回
  设备分辨率（1920×1080）。
- 对话框：游戏里的对话框都水平居中，顶上有一条蓝色标题栏。先找标题栏，再把标题栏里的
  白字抠成黑白图，和存好的各个标题比。
- 整页画面：每个页面有 1～3 个“标志”（固定位置的一小块图），全部对上才算。
- 认不出来就老实说 unknown，由上层决定等一等还是停下。
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

NORM_W, NORM_H = 1280, 720

# 标题栏：左右两段取样窗口（避开中间的标题文字）
_SIDE_L = (350, 480)
_SIDE_R = (800, 930)
_BAR_MIN, _BAR_MAX = 28, 48
_BAR_Y_MAX = 430
TITLE_X0, TITLE_X1 = 430, 850          # 标题文字所在的列范围（居中 420 像素）
TITLE_H = 38
WHITE_THR = 200
DIM_LO, DIM_HI = 0.85, 1.18             # 标志区域的亮度和模板相比允许的范围
MIN_TITLE_PX = 120                     # 标题白字至少这么多像素（实测最少 171）


def to_norm(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    if (w, h) == (NORM_W, NORM_H):
        return img
    interp = cv2.INTER_AREA if w > NORM_W else cv2.INTER_LINEAR
    return cv2.resize(img, (NORM_W, NORM_H), interpolation=interp)


def _blue(a: np.ndarray) -> np.ndarray:
    b = a[..., 0].astype(np.int16)
    g = a[..., 1].astype(np.int16)
    r = a[..., 2].astype(np.int16)
    return (b > 150) & (b - r > 60) & (g > 60) & (g < 185) & (r < 130)


def find_title_bar(norm: np.ndarray) -> int | None:
    """返回最上层对话框标题栏第一行的 y；没有对话框返回 None。

    被上层对话框压住的对话框，标题栏会变暗；这里只认最亮的那一条，
    而且颜色要落在实测的标题栏颜色范围内（阶段 0 录制里 795 帧的统计）。
    """
    top = norm[:_BAR_Y_MAX]
    blue = _blue(top)
    left = blue[:, _SIDE_L[0]:_SIDE_L[1]].mean(axis=1)
    right = blue[:, _SIDE_R[0]:_SIDE_R[1]].mean(axis=1)
    ok = (left >= 0.6) & (right >= 0.6)
    n = len(ok)
    best: tuple[float, int] | None = None
    y = 0
    while y < n:
        if not ok[y]:
            y += 1
            continue
        y2 = y
        while y2 + 1 < n and (ok[y2 + 1] or (y2 + 2 < n and ok[y2 + 2])):
            y2 += 1
        if _BAR_MIN <= y2 - y + 1 <= _BAR_MAX:
            band = top[y:y2 + 1]
            both = np.concatenate([band[:, _SIDE_L[0]:_SIDE_L[1]].reshape(-1, 3),
                                   band[:, _SIDE_R[0]:_SIDE_R[1]].reshape(-1, 3)])
            b, g, r = both.mean(axis=0)
            if b >= 190 and 105 <= g <= 152 and 58 <= r <= 105 and float(both.std(axis=0).mean()) <= 28:
                if best is None or b > best[0]:
                    best = (float(b), y)
        y = y2 + 1
    return None if best is None else best[1]


def title_mask(norm: np.ndarray, bar_y: int) -> np.ndarray:
    """标题栏里的白字 → 0/1 图（38×420）。"""
    strip = norm[bar_y:bar_y + TITLE_H, TITLE_X0:TITLE_X1]
    if strip.shape[0] < TITLE_H:
        strip = cv2.copyMakeBorder(strip, 0, TITLE_H - strip.shape[0], 0, 0, cv2.BORDER_CONSTANT)
    return (strip.min(axis=2) > WHITE_THR).astype(np.uint8)


def mask_distance(a: np.ndarray, b: np.ndarray, max_shift: tuple[int, int] = (3, 2)) -> float:
    """两张 0/1 图的差异（0 = 一样，1 = 完全不同），允许小幅错位。"""
    best = 1.0
    sx, sy = max_shift
    h, w = a.shape
    for dy in range(-sy, sy + 1):
        for dx in range(-sx, sx + 1):
            ax0, ax1 = max(0, dx), min(w, w + dx)
            ay0, ay1 = max(0, dy), min(h, h + dy)
            aa = a[ay0:ay1, ax0:ax1]
            bb = b[ay0 - dy:ay1 - dy, ax0 - dx:ax1 - dx]
            union = int(np.count_nonzero(aa | bb))
            if union < 40:
                continue
            d = int(np.count_nonzero(aa ^ bb)) / union
            if d < best:
                best = d
    return best


def _chan_min(a: np.ndarray) -> np.ndarray:
    b, g, r = cv2.split(a)                   # 比 a.min(axis=2) 快几十倍
    return cv2.min(cv2.min(b, g), r)


def _chan_max(a: np.ndarray) -> np.ndarray:
    b, g, r = cv2.split(a)
    return cv2.max(cv2.max(b, g), r)


def _prep(norm: np.ndarray, mode: str) -> np.ndarray:
    if mode == "color":                                          # 彩色小图标（职能、属性、遗物系列）：颜色本身就是信息，不转灰度
        return norm
    if mode == "white":
        return ((_chan_min(norm) > WHITE_THR).astype(np.uint8)) * 255
    if mode == "dark":                                           # 白底上的深色字：只看字的笔画，相近的两行字也分得开
        return ((cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY) < 150).astype(np.uint8)) * 255
    if mode == "yellow":                                         # WIN! 这类黄色大字：只看黄色部分，不受背景影响
        b = norm[..., 0].astype(np.int16)
        g = norm[..., 1].astype(np.int16)
        r = norm[..., 2].astype(np.int16)
        return (((r > 190) & (g > 130) & (b < 150) & (r - b > 80)).astype(np.uint8)) * 255
    return cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)


@dataclass
class Anchor:
    key: str
    rect: tuple[int, int, int, int]          # x, y, w, h（1280×720 坐标）
    mode: str = "gray"                       # gray = 灰度比对；white = 只看白字
    thr: float = 0.80
    search: int = 6                          # 允许的位置偏差（像素）


@dataclass
class PageDef:
    id: str
    name: str
    anchors: list[list[Anchor]] = field(default_factory=list)   # 每组里对上一个即可，各组都要对上
    dark: bool = False                       # 要求左侧和上方边缘是黑的（加载中；中间可能有四格漫画）
    black: bool = False                      # 整个画面全黑（过场）
    wait: bool = False                       # 这个页面上什么都不用做，等它自己过去


@dataclass
class PageResult:
    page: str                                # 页面 id；认不出是 "unknown"
    name: str
    kind: str                                # dialog / page / unknown
    score: float = 0.0
    busy: bool = False                       # 右上角有“正在进行数据连接”
    bar_y: int | None = None
    hits: dict[str, tuple[float, tuple[int, int]]] = field(default_factory=dict)
    note: str = ""
    wait: bool = False                       # 等待类页面（加载中、黑屏、数据连接、胜利演出）

    @property
    def known(self) -> bool:
        return self.kind != "unknown"


class PageBook:
    """页面规则 + 模板。assets/pages/pages.json 和 templates.npz 由 tools/dev/build_pages.py 生成。"""

    def __init__(self, folder: str | Path):
        folder = Path(folder)
        spec = json.loads((folder / "pages.json").read_text(encoding="utf-8"))
        with open(folder / "templates.npz", "rb") as f:          # 用 Python 打开，中文路径没问题
            npz = np.load(io.BytesIO(f.read()))
            self.tmpl: dict[str, np.ndarray] = {k: npz[k] for k in npz.files}
        self.spec = spec
        self.title_thr: float = float(spec.get("title_thr", 0.40))
        self.titles: list[tuple[str, str, np.ndarray]] = []       # (页面 id, 中文名, 0/1 图)
        for t in spec["titles"]:
            for k in t["keys"]:
                self.titles.append((t["id"], t["name"], self.tmpl[k]))
        self.pages: list[PageDef] = []
        for p in spec["pages"]:
            groups = [[Anchor(a["key"], tuple(a["rect"]), a.get("mode", "gray"),
                              float(a.get("thr", 0.8)), int(a.get("search", 6))) for a in g]
                      for g in p["anchors"]]
            self.pages.append(PageDef(p["id"], p["name"], groups, bool(p.get("dark", False)), bool(p.get("black", False)), bool(p.get("wait", False))))
        b = spec.get("busy")
        self.busy: Anchor | None = (Anchor(b["key"], tuple(b["rect"]), b.get("mode", "white"),
                                           float(b.get("thr", 0.6)), int(b.get("search", 6))) if b else None)
        self.names: dict[str, str] = {t["id"]: t["name"] for t in spec["titles"]}
        self.names.update({p["id"]: p["name"] for p in spec["pages"]})
        self.names.update({"busy": "数据连接中", "unknown": "认不出的画面"})
        # 小标记：流程里要在画面上找的东西（公会名、“将返还迷宫通行证”等）
        self.marks: dict[str, dict[str, Any]] = {m["key"]: m for m in spec.get("marks", [])}
        self.regions: dict[str, tuple[int, int, int, int]] = {k: tuple(v) for k, v in spec.get("regions", {}).items()}

    # ---- 单个标志 ----
    def match_anchor(self, prepped: dict[str, np.ndarray], norm: np.ndarray, a: Anchor) -> tuple[float, tuple[int, int]]:
        if a.mode not in prepped:
            prepped[a.mode] = _prep(norm, a.mode)
        img = prepped[a.mode]
        t = self.tmpl[a.key]
        x, y, w, h = a.rect
        x0, y0 = max(0, x - a.search), max(0, y - a.search)
        x1, y1 = min(NORM_W, x + w + a.search), min(NORM_H, y + h + a.search)
        roi = img[y0:y1, x0:x1]
        if roi.shape[0] < t.shape[0] or roi.shape[1] < t.shape[1]:
            return 0.0, (x, y)
        if float(roi.std()) < 1.0 or float(t.std()) < 1.0:       # 纯色区域没法做相关
            return 0.0, (x, y)
        res = cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        score = float(score)
        if a.mode == "gray" and score >= a.thr:
            # 相关系数不看明暗：页面被别的东西压暗时照样能对上。所以再比一下亮度，暗了就不算。
            hit = roi[loc[1]:loc[1] + t.shape[0], loc[0]:loc[0] + t.shape[1]]
            ratio = (float(hit.mean()) + 1.0) / (float(t.mean()) + 1.0)
            if not DIM_LO <= ratio <= DIM_HI:
                score = min(score, a.thr - 0.01)
        return score, (x0 + loc[0], y0 + loc[1])

    # ---- 整张画面 ----
    def recognize(self, img: np.ndarray) -> PageResult:
        norm = to_norm(img)
        prepped: dict[str, np.ndarray] = {}
        busy = False
        if self.busy is not None:
            s, _ = self.match_anchor(prepped, norm, self.busy)
            busy = s >= self.busy.thr

        if busy:
            # 右上角有“正在进行数据连接”时游戏不接受操作，下面是什么页面都只能等。
            # （2026-11-16 离线测试：原图上有几帧变暗的商店会被认成“商店”，所以让它优先。）
            return PageResult("busy", "数据连接中", "page", 1.0, True, None, wait=True)

        bar = find_title_bar(norm)
        m = title_mask(norm, bar) if bar is not None else None
        if m is not None and int(m.sum()) < MIN_TITLE_PX:        # 蓝条里没有字：不是对话框
            bar, m = None, None
        if bar is not None:
            rough = sorted(((mask_distance(m, ref, (0, 0)), i) for i, (_, _, ref) in enumerate(self.titles)))
            fine: dict[str, tuple[float, str]] = {}                # 页面 id → (差异, 名字)
            for _, i in rough[:4]:
                pid, name, ref = self.titles[i]
                d = mask_distance(m, ref)
                if pid not in fine or d < fine[pid][0]:
                    fine[pid] = (d, name)
            ranked = sorted((d, pid, name) for pid, (d, name) in fine.items())
            best = ranked[0]
            second = ranked[1][0] if len(ranked) > 1 else 1.0
            if best[0] <= self.title_thr and second - best[0] < 0.08:   # 两个标题差不多像：拿不准就不认
                return PageResult("unknown", "不认识的对话框", "unknown", 1.0 - best[0], busy, bar,
                                  note=f"「{best[2]}」和「{ranked[1][2]}」分不清")
            if best[0] <= self.title_thr:
                return PageResult(best[1], best[2], "dialog", 1.0 - best[0], busy, bar)
            if busy:
                return PageResult("busy", "数据连接中", "page", 1.0, True, bar, wait=True)
            return PageResult("unknown", "不认识的对话框", "unknown", 1.0 - best[0], busy, bar,
                              note=f"最像「{best[2]}」，差异 {best[0]:.2f}")

        # 整页画面：按 pages.json 里的先后顺序，第一个所有标志都对上的就是它
        for p in self.pages:
            if p.black:
                mx = _chan_max(norm)
                if float(mx.mean()) < 6.0 and int(mx.max()) < 60:
                    return PageResult(p.id, p.name, "page", 1.0, busy, wait=True)
                continue
            if p.dark and (float(norm[0:90, 0:400].mean()) > 12.0 or float(norm[630:720, 0:880].mean()) > 12.0):
                continue
            hits: dict[str, tuple[float, tuple[int, int]]] = {}
            ok = True
            for group in p.anchors:
                gbest: tuple[float, float, tuple[int, int], Anchor] | None = None
                for a in group:
                    s, loc = self.match_anchor(prepped, norm, a)
                    if gbest is None or s - a.thr > gbest[0]:
                        gbest = (s - a.thr, s, loc, a)
                assert gbest is not None
                hits[gbest[3].key] = (gbest[1], gbest[2])
                if gbest[0] < 0:
                    ok = False
                    break
            if ok:
                return PageResult(p.id, p.name, "page", min(v[0] for v in hits.values()), busy, None, hits,
                                  wait=p.wait)
        if busy:        # 数据连接时整个画面会暗两成，别的都认不出来，这是正常的等待状态
            return PageResult("busy", "数据连接中", "page", 1.0, True, None, wait=True)
        return PageResult("unknown", "认不出的画面", "unknown", 0.0, busy, None)

    # ---- 在画面上找一个小标记 ----
    def find_mark(self, img: np.ndarray, key: str) -> tuple[float, tuple[int, int, int, int]]:
        """返回 (相似度, 找到的位置 x,y,w,h)，坐标是 1280×720 的。相似度低于标记的 thr 就当没找到。"""
        m = self.marks[key]
        norm = to_norm(img)
        mode = m.get("mode", "gray")
        prepped = _prep(norm, mode)
        t = self.tmpl[key]
        rx, ry, rw, rh = m["region"]
        roi = prepped[ry:ry + rh, rx:rx + rw]
        if roi.shape[0] < t.shape[0] or roi.shape[1] < t.shape[1] or float(roi.std()) < 1.0:
            return 0.0, (0, 0, 0, 0)
        res = cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        box = (rx + loc[0], ry + loc[1], t.shape[1], t.shape[0])
        score = float(score)
        if mode == "gray":
            hit = roi[loc[1]:loc[1] + t.shape[0], loc[0]:loc[0] + t.shape[1]]
            ratio = (float(hit.mean()) + 1.0) / (float(t.mean()) + 1.0)
            if not DIM_LO <= ratio <= DIM_HI:
                score = min(score, 0.0)
        return score, box

    def classify(self, img: np.ndarray, keys: list[str]) -> tuple[str | None, float, float]:
        """在几个长得很像的标记里判断是哪一个（比如“战斗格子（普通）”和“战斗格子（极难）”只差两个字）。

        先各自比一遍；最像的两个再只比它们不一样的那些像素，这样两行字哪怕九成相同也分得开。
        返回 (标记, 相似度, 把握)：相似度不到该标记的 thr 时标记为 None；把握是 0～1，越大越确定。
        """
        norm = to_norm(img)
        gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
        found = []
        for k in keys:
            m = self.marks[k]
            t = self.tmpl[k]
            rx, ry, rw, rh = m["region"]
            roi = gray[ry:ry + rh, rx:rx + rw]
            if roi.shape[0] < t.shape[0] or roi.shape[1] < t.shape[1] or float(roi.std()) < 1.0:
                continue
            res = cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED)
            _, sc, _, loc = cv2.minMaxLoc(res)
            hit = roi[loc[1]:loc[1] + t.shape[0], loc[0]:loc[0] + t.shape[1]]
            found.append((float(sc), k, hit, t))
        if not found:
            return None, 0.0, 0.0
        found.sort(key=lambda f: -f[0])
        best = found[0]
        if best[0] < float(self.marks[best[1]].get("thr", 0.8)):
            return None, best[0], 0.0
        if len(found) == 1 or found[1][0] < 0.6 or found[1][3].shape != best[3].shape:
            return best[1], best[0], 1.0
        a, b = found[0], found[1]
        diff = (cv2.absdiff(a[3], b[3]) > 50).astype(np.uint8)
        diff = cv2.dilate(diff, np.ones((3, 3), np.uint8)) > 0
        if int(diff.sum()) < 20:
            return best[1], best[0], 0.0
        ea = float(cv2.absdiff(a[2], a[3])[diff].mean())
        eb = float(cv2.absdiff(b[2], b[3])[diff].mean())
        win, lose = (a, b) if ea <= eb else (b, a)
        sure = abs(ea - eb) / (max(ea, eb) + 1e-6)
        return win[1], win[0], sure

    def find_all(self, img: np.ndarray, key: str, min_gap: int = 60, max_n: int = 12) -> list[tuple[float, tuple[int, int, int, int]]]:
        """同一个标记在画面上出现的所有位置（比如几个「选择」按钮）。"""
        m = self.marks[key]
        norm = to_norm(img)
        prepped = _prep(norm, m.get("mode", "gray"))
        t = self.tmpl[key]
        rx, ry, rw, rh = m["region"]
        roi = prepped[ry:ry + rh, rx:rx + rw]
        if roi.shape[0] < t.shape[0] or roi.shape[1] < t.shape[1] or float(roi.std()) < 1.0:
            return []
        res = cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED)
        thr = float(m.get("thr", 0.8))
        out: list[tuple[float, tuple[int, int, int, int]]] = []
        while True:
            _, sc, _, loc = cv2.minMaxLoc(res)
            if sc < thr or len(out) >= max_n:
                break
            out.append((float(sc), (rx + loc[0], ry + loc[1], t.shape[1], t.shape[0])))
            x0, y0 = max(0, loc[0] - min_gap), max(0, loc[1] - t.shape[0])
            res[y0:loc[1] + t.shape[0], x0:loc[0] + min_gap] = -1.0
        out.sort(key=lambda o: o[1][0])
        return out

    def has_mark(self, img: np.ndarray, key: str) -> bool:
        return self.find_mark(img, key)[0] >= float(self.marks[key].get("thr", 0.8))

    def crop(self, img: np.ndarray, region: str) -> np.ndarray:
        x, y, w, h = self.regions[region]
        return to_norm(img)[y:y + h, x:x + w].copy()

    # ---- 坐标换算 ----
    @staticmethod
    def to_device(pt: tuple[float, float], size: tuple[int, int] = (1920, 1080)) -> tuple[int, int]:
        return int(round(pt[0] * size[0] / NORM_W)), int(round(pt[1] * size[1] / NORM_H))
