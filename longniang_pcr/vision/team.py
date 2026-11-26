"""读两个选人对话框：「角色选择」（开局三选）和「队伍编组」（每场战斗前）。

位置都是在阶段 0 的录制里量出来的（1280×720 坐标）：
- 名单每行 8 格，格子中心横坐标 146 + 141×列；
  角色选择的两行中心在 252、393；队伍编组的两行中心在 226、373。
- 队伍编组下面「当前的成员」五个位置，中心在 (127 + 146×序号, 606)；空位是一块平的浅灰色。
- 名单里已经上场的角色会变暗，右上角盖一个黄色对勾。

首领战的队伍编组是另一个样子：上面多一排「队伍1 ▸ 队伍2 ▸ 队伍3」页签（当前那个是黄色的），名单能上下滚动，
所以名单里的格子不按固定位置找，改成找每个头像左上角的“等级”两个字；成员栏的位置和普通战斗一样。
右下角的按钮在三个页签上分别是「队伍2」「队伍3」「战斗开始」，位置也和普通战斗的「战斗开始」一样。
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .pages import PageBook, to_norm

COL_X0, COL_DX, COLS = 146, 141, 8
PICK_ROWS = (252, 393)
TEAM_ROWS = (226, 373)
SLOT_X0, SLOT_DX, SLOT_Y, SLOTS = 127, 146, 606, 5
CHECK_X0, CHECK_Y0 = 166, 178           # 第 0 格对勾模板的左上角
HAS_ICON_STD = 12.0                     # 格子里有头像时灰度起伏在 30 以上；空格子是 0


@dataclass
class Cell:
    index: int                          # 从左到右、从上到下数，从 0 开始
    cx: int
    cy: int
    selected: bool = False

    @property
    def tap_box(self) -> tuple[float, float, float, float]:
        return (self.cx - 36.0, self.cy - 30.0, 72.0, 60.0)


# 名单里每张卡左上角那两个字：排序选「等级」时写的是“等级371”。排序选了别的（比如「战力」→“战力112377”）就不是这两个字了，
# 卡片会一张都找不到（2026-11-26 玩家排查包）。用户定的：不去认别的写法（排序方式不止一两种），而是把排序换回「等级」。
LABEL_KEYS = ("team_lv",)


def card_labels(book: PageBook, img: np.ndarray, min_gap: int = 30, max_n: int = 40) -> list[tuple[int, int]]:
    """名单里每张卡左上角“等级”两个字的位置（它的左上角 x, y；1280×720）。同一张卡只算一次。"""
    out: list[tuple[int, int]] = []
    for key in LABEL_KEYS:
        if key not in book.marks:
            continue
        for _, (x, y, _, _) in book.find_all(img, key, min_gap=min_gap, max_n=max_n):
            if not any(abs(x - a) <= 8 and abs(y - b) <= 8 for a, b in out):
                out.append((x, y))
    return out


def list_has_faces(img: np.ndarray) -> bool:
    """名单那一块里是不是明明有头像（第一行第一格那里不是一片平的底色）。找不到卡片时拿它分“名单是空的”和“卡片上的字我不认识”。"""
    gray = cv2.cvtColor(to_norm(img), cv2.COLOR_BGR2GRAY)
    return any(_has_icon(gray, COL_X0, cy) for cy in (*TEAM_ROWS, 250, 300))


# ---- 右上角的排序按钮，和它点开以后的「分类」对话框（2026-11-26 用户发的截图）----
# 排序按钮是一个白色的长圆条：左边写着现在按什么排（“等级”“战力”……），右边三条蓝色横线。普通战的队伍编组里它在 y≈98～135，
# 首领战的多一排页签，它在 y≈190～227；左右位置一样。所以先找那三条横线，再在它左边看写的是不是“等级”。
SORT_LV_MIN = 0.8                       # 按钮上“等级”两个字的相似度：够这个数才算“现在按等级排”
SORT_RADIO = (103, 303)                 # 「分类」里“显示顺序”第一个选项（等级）那个圆点的中心


SORT_ICONS = ("sort_icon", "sort_icon_up")     # 三条横线有两种画法：“从高到低”上长下短，“从低到高”上短下长
SORT_ICON_AT = {False: (1041, 104), True: (1041, 197)}        # 两种画法都没对上时按老位置算：普通战 / 首领战（多一排页签，低 93 像素）


def sort_state(book: PageBook, img: np.ndarray) -> tuple[str | None, tuple[float, float, float, float] | None, float]:
    """队伍编组右上角的排序按钮。返回（状态, 按钮上能点的一块, “等级”两个字的相似度）：
    状态 "lv" = 现在按等级排；"other" = 按别的排；None = 库里没有这几张模板（老的页面库）。
    注意：按别的排不一定就认不出卡片——比如「编组顺序」，卡片左上角写的还是“等级”；「战力」这类才会换成自己的数。"""
    if "sort_lv" not in book.tmpl:
        return None, None, 0.0
    best = None
    for key in SORT_ICONS:
        if key in book.marks:
            score, (x, y, w, h) = book.find_mark(img, key)
            if score >= float(book.marks[key].get("thr", 0.8)) and (best is None or score > best[0]):
                best = (score, x, y, w, h)
    if best is None:
        x, y = SORT_ICON_AT[bool(boss_tab(img))]
        w, h = 32, 28
    else:
        _, x, y, w, h = best
    gray = cv2.cvtColor(to_norm(img), cv2.COLOR_BGR2GRAY)
    t = book.tmpl["sort_lv"]
    x0, y0 = max(0, x - 112), max(0, y - 8)
    roi = gray[y0:y0 + t.shape[0] + 16, x0:x0 + t.shape[1] + 30]
    lv = 0.0
    if roi.shape[0] >= t.shape[0] and roi.shape[1] >= t.shape[1] and float(roi.std()) >= 1.0:
        lv = float(cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED).max())
    box = (x - 96.0, y + 3.0, 112.0, max(12.0, h - 8.0))            # 文字到三条横线之间那一段，整块都在按钮里
    return ("lv" if lv >= SORT_LV_MIN else "other"), box, lv


def sort_lv_selected(img: np.ndarray) -> bool:
    """「分类」对话框里“等级”那个圆点是不是选中的（选中是实心的蓝色，没选中是白的）。"""
    cx, cy = SORT_RADIO
    p = to_norm(img)[cy - 6:cy + 7, cx - 6:cx + 7].astype(np.int16)
    return float((p[..., 0] - p[..., 2]).mean()) > 60.0              # 蓝减红


TAB_X = (129, 287, 444)                 # 首领战三个页签的中心横坐标（y 在 112～128）
LV_TO_CENTER = (60, 59)                 # “等级”两个字的左上角 → 头像中心
LIST_BOTTOM = 492                       # 名单下沿（再往下是成员栏）


@dataclass
class TeamView:
    cells: list[Cell]                   # 名单里有头像的格子
    members: int                        # 当前的成员里已经有几个
    empty_slots: int
    tab: int = 0                        # 0 = 普通战斗；1～3 = 首领战，现在在队伍几

    @property
    def free(self) -> list[Cell]:
        return [c for c in self.cells if not c.selected]


def _has_icon(gray: np.ndarray, cx: int, cy: int) -> bool:
    return float(gray[cy - 40:cy + 40, cx - 40:cx + 40].std()) >= HAS_ICON_STD


def pick_cells(img: np.ndarray) -> list[Cell]:
    """「角色选择」名单里有头像的格子。"""
    gray = cv2.cvtColor(to_norm(img), cv2.COLOR_BGR2GRAY)
    out = []
    for r, cy in enumerate(PICK_ROWS):
        for k in range(COLS):
            cx = COL_X0 + COL_DX * k
            if _has_icon(gray, cx, cy):
                out.append(Cell(r * COLS + k, cx, cy))
    return out


def boss_tab(img: np.ndarray) -> int:
    """首领战的队伍编组现在在第几个页签（1～3）；普通战斗的队伍编组返回 0。黄色的那个页签红减蓝在 75 左右，其余接近 0。"""
    norm = to_norm(img).astype(np.int16)
    vals = []
    for x in TAB_X:
        p = norm[112:128, x - 30:x + 30]
        vals.append(float((p[..., 2] - p[..., 0]).mean()))
    top = int(np.argmax(vals))
    rest = [v for i, v in enumerate(vals) if i != top]
    return top + 1 if vals[top] >= 55 and all(-25 <= v <= 20 for v in rest) else 0


def _read_boss_team(book: PageBook, img: np.ndarray, gray: np.ndarray, tab: int) -> TeamView:
    checks = [(x, y) for _, (x, y, _, _) in book.find_all(img, "team_check", max_n=24)]
    # 已经编进别的队伍的角色没有对勾，只在头像下沿标着“队伍N”：这些也不能再点
    tags = [(x, y) for _, (x, y, _, _) in book.find_all(img, "team_tag", max_n=24)] if "team_tag" in book.marks else []
    cells = []
    for lx, ly in card_labels(book, img, min_gap=30, max_n=24):
        cx, cy = lx + LV_TO_CENTER[0], ly + LV_TO_CENTER[1]
        if cy + 30 > LIST_BOTTOM:                    # 这一行下半截被成员栏挡住，点不准，不用
            continue
        k = round((cx - COL_X0) / COL_DX)
        if abs(cx - (COL_X0 + COL_DX * k)) > 6 or not 0 <= k < COLS:   # 不在列上的不是卡片（右上角排序按钮上也写着“等级”）
            continue
        sel = (any(abs(x - (cx + 20)) <= 30 and abs(y - (cy - 48)) <= 30 for x, y in checks)
               or any(abs(x - (cx - 23)) <= 30 and abs(y - (cy + 41)) <= 30 for x, y in tags))
        cells.append((cy, k, Cell(0, cx, cy, sel)))
    cells.sort(key=lambda c: (c[0] // 40, c[1]))
    out = []
    for i, (_, _, c) in enumerate(cells):
        c.index = i
        out.append(c)
    members = sum(1 for i in range(SLOTS) if _has_icon(gray, SLOT_X0 + SLOT_DX * i, SLOT_Y))
    return TeamView(out, members, SLOTS - members, tab)


def read_team(book: PageBook, img: np.ndarray) -> TeamView:
    """「队伍编组」：名单里有哪些角色、哪些已经上场，成员栏还有几个空位。"""
    gray = cv2.cvtColor(to_norm(img), cv2.COLOR_BGR2GRAY)
    tab = boss_tab(img)
    if tab:
        return _read_boss_team(book, img, gray, tab)
    checked = set()
    for _, (x, y, _, _) in book.find_all(img, "team_check"):
        k = round((x - CHECK_X0) / COL_DX)
        r = round((y - CHECK_Y0) / (TEAM_ROWS[1] - TEAM_ROWS[0]))
        checked.add((r, k))
    cells = []
    for r, cy in enumerate(TEAM_ROWS):
        for k in range(COLS):
            cx = COL_X0 + COL_DX * k
            if _has_icon(gray, cx, cy):
                cells.append(Cell(r * COLS + k, cx, cy, (r, k) in checked))
    members = sum(1 for i in range(SLOTS) if _has_icon(gray, SLOT_X0 + SLOT_DX * i, SLOT_Y))
    return TeamView(cells, members, SLOTS - members)
