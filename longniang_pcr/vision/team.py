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
    for _, (lx, ly, _, _) in book.find_all(img, "team_lv", min_gap=30, max_n=24):
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
