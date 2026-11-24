"""商店页面（黎明界迷宫里用阿尔法金币买东西的那个）。只看画面，不点。

版面（1280×720 坐标）：商品一行 3 件；普通商店 2 行 6 件，卖 ★3 / ★4 遗物的那种 3 行 9 件（2026-11-18 真机截图上滚动条短了一截）。
卖掉的盖上“已售罄”排到最后，没卖的往前补。列表能上下拖：停在最上面时只有第一行看得到价格，一眼最多看全两行的价格。
所以不认固定位置：先找每件商品价格框左边的金币图标（发灰的已售罄也找得到），再按它算这件商品其余各处在哪。

每件商品读四样：
- 是什么：图标右下角有职能徽章的是「××型职能的随机印记 / 选择印记」（多一名角色；金色底的是“选择”）；
  图标左上角有星星、或左下角有系列徽章的是迷宫遗物；都不是就当不认识（流程里不买）。
- 价格：深色字白边的数字，单独一套模板（钱不够时是红字、已售罄时发灰，照样读得出）。不同公会的商店打不打折都按读到的算。
- 现在能不能买：看「购买」按钮——亮蓝 = 能买，暗蓝 + 红色价格 = 钱不够，卡片上盖着红章 = 已售罄。
- 「购买」按钮在哪。
另外读右下角“持有阿尔法金币”，和「用×××更新」按钮亮不亮（一家商店只能更新两次：第一次 300、第二次 600，
用完或钱不够时按钮是暗的——2026-11-16 那局录制里两家商店都是这样）。

两个对话框里的数字也在这里读：购买确认（持有 → 买完剩多少）、更新确认（所需、持有）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from . import cards as CD
from . import hud as HUD
from .pages import PageBook, to_norm

COL_X, COL_DX, COLS = 68, 384, 3         # 金币图标左上角的 x：第 0 列、每列间隔
ROW_DY = 254                             # 两行之间隔多少
ROW_TOP, ROW_BOTTOM = 330, 514           # 列表停在最上面时第一行金币图标的 y；拖到底时最后一行的 y（真机、录制都是 513～514）
LIST_TOP, LIST_BOTTOM = 137, 585         # 商品列表的上下沿（出了这个范围的部分被挡住）
ANCHOR_THR = 0.85                        # 金币图标至少这么像（录制和真机上都 ≥0.99，发灰的已售罄也是）
# 下面都是相对金币图标左上角 (ax, ay) 的位置：x, y, w, h
PRICE = (52, -4, 112, 42)                # 价格数字
BUY_TAP = (192, 3, 136, 28)              # 点「购买」时落在这里面（按钮本身是 172, -3, 177, 43）
BUY_LIT = (185, 4, 150, 28)              # 量「购买」按钮亮不亮的那一块
ICON = (-1, -119, 100, 100)              # 商品图标
STARS = (-2, -121, 72, 24)               # 图标左上角那一排星星
STAR_X, STAR_DX, STAR_AREA = 8.0, 13.5, 30   # 第一颗星的黄像素块在这一条里的 x、每颗间隔、一颗至少多少个黄像素（实测 38～63）
SERIES_ROI, SERIES_SIZES = (-8, -56, 44, 46), (28, 29, 30)     # 系列徽章可能在的范围、大小（模板是 44 像素的，缩到这么大再比）
ROLE_ROI, ROLE_SIZES = (62, -58, 44, 46), (22, 23, 24, 25)     # 职能徽章（模板是 24 像素的）
BADGE_THR = 0.70                         # 徽章至少这么像（认对的 0.81～0.92；没有徽章时最高 0.43）
STAMP = (0, -125, 350, 115)              # “已售罄”红章盖在这一块上
COINS = (780, 634, 160, 34)              # 右下角“持有阿尔法金币”后面的数字
REFRESH_LIT = (345, 634, 205, 30)        # 「用×××更新」按钮
DIGIT_THR = 0.72                         # 对话框里的数字每一位至少这么像（蓝色的“买完剩多少”认对的最低 0.73）
PRICE_THR = 0.80                         # 价格的每一位至少这么像（录制和真机截图上认对的最低 0.98，钱不够的红字、已售罄的灰字都算上）
# 对话框里的数字：x, y, w, h
BUY_HAVE, BUY_LEFT = (640, 490, 110, 35), (820, 490, 110, 35)          # 购买确认：持有 → 买完剩多少
REFRESH_COST, REFRESH_HAVE = (820, 362, 110, 34), (820, 400, 110, 36)  # 更新确认：所需、持有

KIND_CN = {"relic": "迷宫遗物", "random": "随机印记", "choose": "选择印记", None: "不认识的东西"}
STATE_CN = {"buy": "能买", "poor": "钱不够", "sold": "已售罄", "unknown": "看不清"}


@dataclass
class Item:
    row: int                             # 这一眼看到的第几行（0 = 靠上的那一行）
    col: int
    kind: str | None                     # "relic" 迷宫遗物 / "random" 随机印记 / "choose" 选择印记 / None 不认识
    stars: int = 0                       # 遗物几星（看不到星星时是 0）
    series: str | None = None            # 遗物的系列
    role: str | None = None              # 印记是哪种职能
    price: int | None = None
    state: str = "unknown"               # "buy" / "poor" / "sold" / "unknown"
    box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)     # 点「购买」的范围

    @property
    def text(self) -> str:
        if self.kind == "relic":
            what = f"{'★' * self.stars if self.stars else '★?'}遗物" + (f"（{CD.SERIES_CN[self.series]}）" if self.series else "")
        elif self.kind in ("random", "choose"):
            what = f"{CD.ROLE_CN.get(self.role, '？')}型{KIND_CN[self.kind]}"
        else:
            what = KIND_CN[None]
        return f"{what} {self.price if self.price is not None else '?'}"

    def as_list(self) -> list:
        return [self.kind, self.stars, self.series, self.role, self.price, self.state]


@dataclass
class ShopView:
    items: list[Item] = field(default_factory=list)
    rows: list[int] = field(default_factory=list)       # 看得到价格的那几行，金币图标的 y
    coins: int | None = None
    refresh: bool = False                               # 「更新」按钮是亮的

    @property
    def full(self) -> bool:
        """两行的价格和「购买」都看得到（列表拖到底了）。"""
        return len(self.rows) >= 2


def _digits(book: PageBook, fam: str) -> dict[str, np.ndarray]:
    return {d: book.tmpl[f"dig_{fam}_{d}"] for d in "0123456789" if f"dig_{fam}_{d}" in book.tmpl}


def read_number(book: PageBook, gray: np.ndarray, box: tuple[int, int, int, int], thr: float = DIGIT_THR, fam: str = "t") -> int | None:
    """读一块区域里的一串数字。fam："t" = 顶栏金币那种字体（右下角的金币、对话框里的数字），"p" = 商品价格那种。读不出返回 None，不猜。"""
    tm = _digits(book, fam)
    x, y, w, h = box
    x0, y0, x1, y1 = max(0, x), max(0, y), min(gray.shape[1], x + w), min(gray.shape[0], y + h)
    if len(tm) < 10 or x1 - x0 < 16 or y1 - y0 < 20:
        return None
    text, _ = HUD._decode(gray[y0:y1, x0:x1], tm, thr)
    if not text or len(text) > 6 or (len(text) > 1 and text[0] == "0"):
        return None
    return int(text)


def find_rows(book: PageBook, gray: np.ndarray) -> list[int]:
    """看得到价格的那几行：每行金币图标左上角的 y（从上到下）。"""
    t = book.tmpl.get("shop_coin")
    if t is None:
        return []
    strip = gray[LIST_TOP:LIST_BOTTOM, COL_X - 8:COL_X + t.shape[1] + 8]
    if strip.shape[0] < t.shape[0] or float(strip.std()) < 1.0:
        return []
    col = cv2.matchTemplate(strip, t, cv2.TM_CCOEFF_NORMED).max(axis=1)
    ys = [int(y) + LIST_TOP for y in range(len(col)) if col[y] >= ANCHOR_THR and col[y] >= col[max(0, y - 8):y + 9].max() - 1e-9]
    out: list[int] = []
    for y in ys:                                         # 同一行不会有两个；挨得太近的只留一个
        if not out or y - out[-1] > 40:
            out.append(y)
    return out[:2]


def _badge(book: PageBook, norm: np.ndarray, ax: int, ay: int, roi: tuple[int, int, int, int], prefix: str,
           names: tuple[str, ...], sizes: tuple[int, ...]) -> tuple[str | None, float]:
    x, y, w, h = ax + roi[0], ay + roi[1], roi[2], roi[3]
    if y < LIST_TOP - 2 or x < 0 or y + h > norm.shape[0] or x + w > norm.shape[1]:
        return None, 0.0
    patch = norm[y:y + h, x:x + w]
    best: tuple[float, str | None] = (0.0, None)
    for n in names:
        t = book.tmpl.get(prefix + n)
        if t is None:
            continue
        for sz in sizes:
            res = cv2.matchTemplate(patch, cv2.resize(t, (sz, sz), interpolation=cv2.INTER_AREA), cv2.TM_CCOEFF_NORMED)
            sc = float(res.max())
            if sc > best[0]:
                best = (sc, n)
    return (best[1], best[0]) if best[0] >= BADGE_THR else (None, best[0])


def _stars(norm: np.ndarray, ax: int, ay: int) -> int:
    x, y, w, h = ax + STARS[0], ay + STARS[1], STARS[2], STARS[3]
    if y < LIST_TOP:                                     # 星星那一排被列表上沿挡住了
        return 0
    p = norm[y:y + h, x:x + w].astype(np.int16)
    yellow = ((p[..., 2] > 215) & (p[..., 1] > 170) & (p[..., 0] < 130)).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(yellow, connectivity=8)
    xs = [float(st[k][0]) for k in range(1, n) if st[k][4] >= STAR_AREA]
    count = 0
    while count < 5 and any(abs(v - (STAR_X + STAR_DX * count)) <= 3.5 for v in xs):     # 从左数，一颗挨一颗；图案里别的黄块不算
        count += 1
    return count


def _state(norm: np.ndarray, ax: int, ay: int) -> str:
    x, y, w, h = ax + STAMP[0], max(LIST_TOP, ay + STAMP[1]), STAMP[2], STAMP[3]
    c = norm[y:ay + STAMP[1] + h, x:x + w].astype(np.int16)
    stamp = int(((c[..., 2] > 200) & (c[..., 1] < 110) & (c[..., 0] < 130)).sum())
    if stamp >= 1800:                                    # 红章 3,500 上下；没盖章的最多几百（图案里的红色）
        return "sold"
    x, y, w, h = ax + BUY_LIT[0], ay + BUY_LIT[1], BUY_LIT[2], BUY_LIT[3]
    v = float(cv2.cvtColor(norm[y:y + h, x:x + w], cv2.COLOR_BGR2HSV)[..., 2].mean())
    if v >= 215.0:                                       # 亮的 238；钱不够 162；已售罄 174
        return "buy"
    x, y, w, h = ax + PRICE[0], ay + PRICE[1], PRICE[2], PRICE[3]
    d = norm[y:y + h, x:x + w].astype(np.int16)
    red = int(((d[..., 2] > 180) & (d[..., 1] < 110) & (d[..., 0] < 110)).sum())
    return "poor" if v < 200.0 and red >= 40 else "unknown"


def _gold(norm: np.ndarray, ax: int, ay: int) -> float:
    x, y, w, h = ax + ICON[0], ay + ICON[1], ICON[2], ICON[3]
    hsv = cv2.cvtColor(norm[max(LIST_TOP, y):y + h, x:x + w], cv2.COLOR_BGR2HSV)
    if hsv.size == 0:
        return 0.0
    return float(((hsv[..., 0] > 15) & (hsv[..., 0] < 35) & (hsv[..., 1] > 90) & (hsv[..., 2] > 180)).mean())


def read_shop(book: PageBook, img: np.ndarray) -> ShopView:
    norm = to_norm(img)
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
    view = ShopView(rows=find_rows(book, gray))
    view.coins = read_number(book, gray, COINS, 0.80)
    x, y, w, h = REFRESH_LIT
    view.refresh = float(cv2.cvtColor(norm[y:y + h, x:x + w], cv2.COLOR_BGR2HSV)[..., 2].mean()) >= 205.0   # 亮 228，暗 155
    for r, ay in enumerate(view.rows):
        for c in range(COLS):
            ax = COL_X + COL_DX * c
            it = Item(r, c, None, state=_state(norm, ax, ay),
                      box=(float(ax + BUY_TAP[0]), float(ay + BUY_TAP[1]), float(BUY_TAP[2]), float(BUY_TAP[3])))
            it.price = read_number(book, gray, (ax + PRICE[0], ay + PRICE[1], PRICE[2], PRICE[3]), PRICE_THR, "p")
            role, _ = _badge(book, norm, ax, ay, ROLE_ROI, "ico_role_", CD.ROLES, ROLE_SIZES)
            if role is not None:
                it.kind, it.role = ("choose" if _gold(norm, ax, ay) >= 0.06 else "random"), role      # 金色底：选择 0.12～0.13，随机 0
            else:
                it.stars = _stars(norm, ax, ay)
                it.series, _ = _badge(book, norm, ax, ay, SERIES_ROI, "ico_series_", CD.SERIES, SERIES_SIZES)
                if it.stars or it.series:
                    it.kind = "relic"
            view.items.append(it)
    return view


def read_buy(book: PageBook, img: np.ndarray) -> tuple[int | None, int | None]:
    """「购买确认」：持有多少、买完剩多少。"""
    gray = cv2.cvtColor(to_norm(img), cv2.COLOR_BGR2GRAY)
    return read_number(book, gray, BUY_HAVE), read_number(book, gray, BUY_LEFT)


def read_refresh(book: PageBook, img: np.ndarray) -> tuple[int | None, int | None]:
    """「更新确认」：这次要花多少、手里有多少。"""
    gray = cv2.cvtColor(to_norm(img), cv2.COLOR_BGR2GRAY)
    return read_number(book, gray, REFRESH_COST, 0.80), read_number(book, gray, REFRESH_HAVE, 0.80)
