"""地图上的格子：在哪、能不能走（发光）、是不是战斗格（标签写着普通 / 极难 / 首领）。

阶段 0 录制里量出来的几何关系（1280×720 坐标）：
- 每列最多 3 格。战斗格标签的中心高度只有五种：240、416、592（一列 3 格），316、516（一列 2 格），
  一列 1 格时在 416。列与列相隔 350。
- 每个格子是一个八边形平台，标签下面露出一条平台前沿。能走的格子整个平台发光（普通是青色，
  极难是品红），前沿很亮；走不了的格子前沿是暗的。前沿的形状不受格子内容和光柱影响，所以用它来找格子。
- 首领格的平台更大，前沿对不上，单独认「首领」标签。
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .pages import PageBook, to_norm

ROW_LY = (240, 316, 416, 516, 592)
ROWS_3, ROWS_2, ROWS_1 = (240, 416, 592), (316, 516), (416,)
COL_DX = 350                # 相邻两列的间距
RIM_DY = 14                 # 平台前沿模板的上边 = 标签中心高度 + 14
RIM_THR = 0.5
GLOW_MIN = 125              # 前沿的平均亮度：发光的在 148～205，不发光的在 60～76
HUE_FRAC = 0.4              # 发光平台的亮像素里，青色（色相 80～108）加品红（135～178）要占四成以上（实测 0.6 以上）；
                            # 你脚下那格也亮，但是蓝紫色（色相 123 左右），青加品红不到 0.2，靠这个排除。
                            # 两种颜色要加在一起算：极难格的品红光柱会照到它上面那一格的前沿，单看青色会把上面那格漏掉


@dataclass
class Tile:
    x: int                  # 格子中心的横坐标
    ly: int                 # 标签中心高度（五种之一）
    score: float
    bright: float
    color: str              # "cyan" / "magenta" / ""（脚下的格子、不发光的格子）
    glow: bool              # 发光 = 现在能走
    label: str | None       # "normal" / "extreme" / "boss" / None（不是战斗格，或者认不出）
    inferred: bool = False  # 前沿被挡住了，是从平台两侧的颜色认出来的
    kind: str | None = None # 格子类型：战斗格 = label；非战斗格看图标 "mark" / "relic" / "event" / "shop"；认不出（或者是你脚下那格）= None

    @property
    def tap_box(self) -> tuple[float, float, float, float]:
        """点这个格子时的落点范围：标签上方的图标一带（录制里你也是点这里）。"""
        return (self.x - 34.0, self.ly - 64.0, 68.0, 42.0)

    @property
    def row_name(self) -> str:
        return {240: "上", 316: "上", 416: "中", 516: "下", 592: "下"}.get(self.ly, "?")


def _glow_color(win: np.ndarray) -> str:
    w = win.reshape(-1, 3).astype(np.int16)
    b = w[w[:, 2] >= 150]
    if len(b) < 60:
        return ""
    h = b[:, 0]
    cyan = float(((h >= 80) & (h <= 108)).mean())
    magenta = float(((h >= 135) & (h <= 178)).mean())
    if cyan + magenta < HUE_FRAC:
        return ""
    return "cyan" if cyan >= magenta else "magenta"


def platform_kind(hsv: np.ndarray, x: int, ly: int) -> str:
    """(x, ly) 这里有没有格子的平台，是哪种：dark 不发光 / lit 你脚下那格 / cyan、magenta 发光 / "" 没有。

    看平台正面左右两端各一小块的颜色（两边要一致）。这两块不会被上面的图标、旁边格子的光柱和底部的按钮挡住，
    所以前沿被挡住的格子也认得出来。数值是在录制里量的：
    不发光 色相 119～122、亮度 103～131；脚下那格 色相一样、亮度 216 以上；青色发光 色相 90～102；品红发光 色相 139～151。
    """
    kinds = []
    for x0 in (x - 70, x + 50):
        if x0 < 0 or x0 + 20 > hsv.shape[1] or ly - 14 < 0 or ly + 10 > hsv.shape[0]:
            return ""
        w = hsv[ly - 14:ly + 10, x0:x0 + 20].reshape(-1, 3)
        h, s, v = float(np.median(w[:, 0])), float(np.median(w[:, 1])), float(np.median(w[:, 2]))
        if 112 <= h <= 128 and 100 <= s <= 140:
            kinds.append("dark" if 96 <= v <= 142 else ("lit" if v >= 205 else ""))
        elif 84 <= h <= 106 and 90 <= s <= 130 and v >= 200:
            kinds.append("cyan")
        elif 134 <= h <= 156 and 88 <= s <= 135 and v >= 160:
            kinds.append("magenta")
        else:
            kinds.append("")
    a, b = kinds
    if not a or not b:
        return ""
    if a == b:
        return a
    return a if {a, b} <= {"cyan", "magenta"} else ""


def _label_at(book: PageBook, gray: np.ndarray, x: int, ly: int) -> str | None:
    best: tuple[float, str | None] = (0.0, None)
    for key, name in (("tile_lbl_normal", "normal"), ("tile_lbl_extreme", "extreme")):
        t = book.tmpl[key]
        y0, x0 = ly - 14 - 6, x - 30 - 8
        roi = gray[max(0, y0):y0 + t.shape[0] + 12, max(0, x0):x0 + t.shape[1] + 16]
        if roi.shape[0] < t.shape[0] or roi.shape[1] < t.shape[1] or float(roi.std()) < 1.0:
            continue
        s = float(cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED).max())
        if s > best[0]:
            best = (s, name)
    return best[1] if best[0] >= 0.75 else None


ICON_KINDS = ("mark", "relic", "event", "shop")
ICON_RECT = (-36, -118, 72, 56)     # 图标模板相对 (x, ly) 的位置
ICON_THR, ICON_GAP = 0.6, 0.25      # 录制里：认对的 ≥0.79，第二名 ≤0.28；战斗格和你脚下那格 ≤0.39


def _icon_at(book: PageBook, gray: np.ndarray, x: int, ly: int) -> str | None:
    """非战斗格的图标是哪一种。发光和不发光各有一张模板，取高的；要求最高分够高、而且比第二名高出一截。"""
    pad = 8
    y0, x0 = ly + ICON_RECT[1] - pad, x + ICON_RECT[0] - pad
    if y0 < 0 or x0 < 0 or x0 + ICON_RECT[2] + 2 * pad > gray.shape[1]:
        return None
    roi = gray[y0:y0 + ICON_RECT[3] + 2 * pad, x0:x0 + ICON_RECT[2] + 2 * pad]
    if float(roi.std()) < 1.0:
        return None
    sc = []
    for k in ICON_KINDS:
        best = 0.0
        for key in (f"tile_ico_{k}", f"tile_icod_{k}"):
            t = book.tmpl.get(key)
            if t is not None and roi.shape[0] >= t.shape[0] and roi.shape[1] >= t.shape[1]:
                best = max(best, float(cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED).max()))
        sc.append((best, k))
    sc.sort(reverse=True)
    return sc[0][1] if sc[0][0] >= ICON_THR and sc[0][0] - sc[1][0] >= ICON_GAP else None


def find_tiles(book: PageBook, img: np.ndarray) -> list[Tile]:
    norm = to_norm(img)
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(norm, cv2.COLOR_BGR2HSV)
    rim = book.tmpl["tile_rim"]
    th, tw = rim.shape
    tiles: list[Tile] = []
    for ly in ROW_LY:
        y0 = ly + RIM_DY - 6
        band = gray[y0:y0 + th + 12]
        if band.shape[0] < th:
            continue
        res = cv2.matchTemplate(band, rim, cv2.TM_CCOEFF_NORMED)
        for _ in range(8):
            _, s, _, loc = cv2.minMaxLoc(res)
            if s < RIM_THR:
                break
            hit = band[loc[1]:loc[1] + th, loc[0]:loc[0] + tw]
            x = loc[0] + tw // 2
            bright = float(hit.mean())
            color = _glow_color(hsv[y0 + loc[1]:y0 + loc[1] + th, loc[0]:loc[0] + tw])
            tiles.append(Tile(x, ly, float(s), bright, color, bright >= GLOW_MIN and color != "", _label_at(book, gray, x, ly)))
            res[:, max(0, loc[0] - 120):loc[0] + 120] = -1.0
    # 前沿被挡住的格子：同一列里按“两格列 / 三格列”该有格子的位置上，再看一眼平台两侧的颜色
    for x, col in columns(list(tiles)):
        rows = {t.ly for t in col}
        two, three = rows & set(ROWS_2), rows & set(ROWS_3)
        if two and three:
            continue
        for ly in (ROWS_2 if two else ROWS_3):
            if ly in rows:
                continue
            kind = platform_kind(hsv, x, ly)
            if kind == "lit":
                tiles.append(Tile(x, ly, 0.0, 255.0, "player", False, None, True))
            elif kind in ("dark", "cyan", "magenta"):
                glow = kind != "dark"
                tiles.append(Tile(x, ly, 0.0, 255.0 if glow else 0.0, kind if glow else "", glow, _label_at(book, gray, x, ly), True))
    for t in tiles:                                  # 前沿认出来的格子里，哪一个是你脚下那格
        if not t.glow and not t.inferred and t.bright >= GLOW_MIN and platform_kind(hsv, t.x, t.ly) == "lit":
            t.color = "player"
    # 首领格
    t = book.tmpl["tile_lbl_boss"]
    res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
    _, s, _, loc = cv2.minMaxLoc(res)
    if s >= 0.75:
        hit = norm[loc[1] - 40:loc[1] + t.shape[0] + 30, loc[0] - 40:loc[0] + t.shape[1] + 40]
        bright = float(cv2.cvtColor(hit, cv2.COLOR_BGR2HSV)[..., 2].mean())
        by = loc[1] + t.shape[0] // 2
        row = min(ROW_LY, key=lambda y: abs(y - by))
        if abs(row - by) <= 10:
            # 首领格是从「首领」标签的位置反推出来的，会比格子行差一两个像素（实测 417，行是 416）。
            # 别处都拿行高当键用（路线、行名），所以这里贴回行上。2026-11-17 真机就是因为这一个像素在首领跟前出错停下的
            by = row
        tiles.append(Tile(loc[0] + t.shape[1] // 2 - 12, by, float(s), bright, "boss", bright >= 150, "boss"))
    for t in tiles:                                  # 格子类型：战斗格看标签，其余看图标
        t.kind = t.label or (None if t.color == "player" else _icon_at(book, gray, t.x, t.ly))
    tiles.sort(key=lambda z: (z.x, z.ly))
    return tiles


def kind_at(book: PageBook, img: np.ndarray, x: int, ly: int) -> str | None:
    """(x, ly) 这个位置上的格子类型：战斗标签（普通 / 极难）或者非战斗格的图标。格子前沿被界面挡住时也能用。"""
    gray = cv2.cvtColor(to_norm(img), cv2.COLOR_BGR2GRAY)
    return _label_at(book, gray, x, ly) or _icon_at(book, gray, x, ly)


def area_number(book: PageBook, img: np.ndarray) -> int:
    """地图顶上的“区域 n/5”。认不出（比如换区域的过场里顶栏还没出来）返回 0。"""
    key, _, sure = book.classify(img, [f"area_{i}" for i in range(1, 6)])
    return int(key[-1]) if key and sure >= 0.3 else 0


def label_at(book: PageBook, img: np.ndarray, x: int, ly: int) -> str | None:
    """(x, ly) 这个位置上的战斗标签（普通 / 极难）。格子前沿被界面挡住时也能用：标签在前沿上面。"""
    return _label_at(book, cv2.cvtColor(to_norm(img), cv2.COLOR_BGR2GRAY), x, ly)


def grid_phase(book: PageBook, img: np.ndarray) -> float | None:
    """各列横坐标对 350 取余（所有列都在同一个余数上）。拖动地图时用它量地图挪了多少。

    只看格子前沿，很快。不发光的格子前沿对比度低，相似度只有 0.55～0.65，所以门槛放在 0.5，
    再用平台两侧的颜色确认一遍；最后取余数最集中的一簇。
    """
    norm = to_norm(img)
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(norm, cv2.COLOR_BGR2HSV)
    rim = book.tmpl["tile_rim"]
    th, tw = rim.shape
    xs: list[tuple[float, float]] = []
    for ly in ROW_LY[:4]:                            # 最下面一行常被界面挡住，不用
        y0 = ly + RIM_DY - 4
        res = cv2.matchTemplate(gray[y0:y0 + th + 8], rim, cv2.TM_CCOEFF_NORMED)
        for _ in range(5):
            _, sc, _, loc = cv2.minMaxLoc(res)
            if sc < 0.5:
                break
            x = loc[0] + tw // 2
            if sc >= 0.72 or platform_kind(hsv, x, ly):
                xs.append((float(x % COL_DX), float(sc)))
            res[:, max(0, loc[0] - 120):loc[0] + 120] = -1.0
    best: tuple[float, float] = (0.0, 0.0)
    for p, _ in xs:
        near = [(q, w) for q, w in xs if min((q - p) % COL_DX, (p - q) % COL_DX) <= 6]
        weight = sum(w for _, w in near)
        if weight > best[0]:
            ang = np.array([q for q, _ in near]) * (2 * np.pi / COL_DX)
            ww = np.array([w for _, w in near])
            best = (weight, float((np.arctan2((np.sin(ang) * ww).sum(), (np.cos(ang) * ww).sum()) % (2 * np.pi)) * COL_DX / (2 * np.pi)))
    return best[1] if best[0] >= 0.5 else None


def phase_step(prev: float, now: float) -> float:
    """两次相位之间地图挪了多少（向左为正）。两次之间挪动不到半列（175 像素）才量得准。"""
    d = (prev - now) % COL_DX
    return d - COL_DX if d > COL_DX / 2 else d


def columns(tiles: list[Tile]) -> list[tuple[int, list[Tile]]]:
    """把格子按列分组：[(列的横坐标, [这一列的格子，从上到下])]，从左到右。"""
    cols: list[list[Tile]] = []
    for t in sorted(tiles, key=lambda z: z.x):
        if cols and abs(t.x - cols[-1][-1].x) <= 40:
            cols[-1].append(t)
        else:
            cols.append([t])
    return [(int(round(float(np.median([t.x for t in c])))), sorted(c, key=lambda z: z.ly)) for c in cols]


def candidate_rows(col: list[Tile]) -> tuple[int, ...]:
    """这一列可能有格子的行。两格的列在 316 / 516，其余在 240 / 416 / 592（只有一格时就是中间那个）。

    格子的前沿可能被界面或旁边的光柱挡住而漏掉，所以这里宁可多给：多出来的行上没有连线，不会被走到。
    """
    rows = {t.ly for t in col}
    if any(t.label == "boss" for t in col):
        return (416,)
    two, three = rows & set(ROWS_2), rows & set(ROWS_3)
    if two and not three:
        return ROWS_2
    if three and not two:
        return ROWS_3
    return ROW_LY


def player_tile(tiles: list[Tile]) -> Tile | None:
    """人物站着的那一格（平台是亮的，但不是青色 / 品红）。没看到返回 None。"""
    cand = [t for t in tiles if t.color == "player"]
    return cand[0] if len(cand) == 1 else None


def reachable(tiles: list[Tile]) -> list[Tile]:
    """现在能走的格子：发光的那些里最靠左的一列。"""
    glow = [t for t in tiles if t.glow]
    if not glow:
        return []
    x0 = min(t.x for t in glow)
    col = [t for t in glow if abs(t.x - x0) <= 40]
    col.sort(key=lambda z: z.ly)
    return col
