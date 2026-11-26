"""角色卡、印记、遗物上的小图标：职能（8 种）、属性（5 种）、遗物系列（5 种）。

阶段 3 的编队、招募、选印记、选遗物都靠它。位置在 2026-11-16 的录制里量的（1280×720 坐标）：

- 角色卡（队伍编组的名单和成员栏、开局「角色选择」）：卡片中心 (cx, cy) 时，右下角白底小条里
  左边是职能图标 (cx+12, cy+37)，右边是属性图标 (cx+38, cy+37)，都是 24×24。
  左下角那一小块会在“星级”和“三个小圆点”之间来回切换，不稳定，所以不读它。
- 「角色加入奖励」三选一：卡片大 1.2 倍，属性图标左上角在 (317 + 370×i, 366)，职能在它左边 31 像素。
- 「获得道具的机会」是连结印记时：属性徽标大约 1.55 倍，左上角在 (308 + 370×i, 356) 附近。
- 「获得道具的机会」是迷宫遗物时：物品图左下角有系列徽标 (192 + 370×i, 329)，44×44；左上角有 1～3 颗星。
  “【削弱+2】”里的数字就是星数：★★ 的遗物让这个系列一次升 2 级。
- 「战斗准备」：敌人等级右边“弱点”后面是一个属性图标，没有弱点时是一条横线。

模板是彩色的（颜色本身就是信息：增益是橙色的上箭头，减益是蓝色的下箭头）。认不准就返回 None，由上层按“不知道”处理。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .pages import PageBook, to_norm
from .team import card_labels

ROLES = ("tank", "heal", "attack", "break", "support", "buff", "debuff", "jam")
ATTRS = ("fire", "water", "wind", "light", "dark")
SERIES = ("weaken", "guard", "speed", "power", "crit")
ROLE_CN = {"tank": "坦克", "heal": "治疗", "attack": "攻击", "break": "破防", "support": "强化", "buff": "增益", "debuff": "减益",
           "jam": "干扰", None: "？"}
ATTR_CN = {"fire": "火", "water": "水", "wind": "风", "light": "光", "dark": "暗", None: "？"}
SERIES_CN = {"weaken": "削弱", "guard": "守备", "speed": "加速", "power": "强化", "crit": "暴击", None: "？"}

ROLE_OFF, ATTR_OFF, ICON = (12, 37), (38, 37), 24
ICON_THR, ICON_GAP = 0.60, 0.08          # 录制里认对的 ≥0.9；最像的另一种 ≤0.6
LV_TO_CENTER = (60, 59)                  # “等级”两个字的左上角 → 卡片中心
LIST_BOTTOM = 492                        # 名单下沿（再往下是成员栏）
SLOT_X0, SLOT_DX, SLOT_Y, SLOTS = 127, 146, 606, 5
PICK_X0, PICK_DX, PICK_ROWS, COLS = 146, 141, (252, 393), 8
RECRUIT_ATTR = (317, 366, 370, 1.2)      # 第 0 张的属性图标左上角 x、y，每张间隔，放大倍数
RECRUIT_CARD = (271, 322, 370, 1.26)     # 第 0 张大头像的中心 x、y，每张间隔，相对名单卡片的放大倍数（和「角色加入」的小头像对出来的）
RECRUIT_NAME = (112, 440, 318, 72)       # 第 0 张下面那两行名字的范围（每张再加 370×i）
JOIN_ROW = (383, 263, 94, 0.48)          # 「角色加入」：第 0 行小头像的中心 x、y，行距，放大倍数
JOIN_NAME = (418, 244, 500, 38)          # 第 0 行名字的范围（每行再加 94×行号）
JOIN_ROWS = 3
MARK_ATTR = (308, 356, 370, 1.55)
RELIC_BADGE = (192, 329, 370)
RELIC_STARS = (192, 222, 108, 32)        # 星星那一条：x、y、宽、高（每个选项再加 370×i）
WEAK_ROI = (790, 372, 80, 44)            # 「战斗准备」里“弱点”后面那个图标可能在的范围
# 队伍编组上面那排页签（全部 / 火 / 水 / 风 / 光 / 暗 / 有效效果）的中心横坐标；普通战斗 y=119，首领战多一排队伍页签，y=209
TAB_X = {"all": 99, "fire": 197, "water": 293, "wind": 390, "light": 487, "dark": 585, "effect": 680}
TAB_Y = {False: 119, True: 209}


@dataclass
class Card:
    cx: int
    cy: int
    role: str | None = None
    attr: str | None = None
    selected: bool = False               # 名单里：已经在当前队伍里（盖着对勾）
    busy: bool = False                   # 首领战：已经编进别的队伍（标着“队伍N”），不能再点
    index: int = 0
    role_s: float = 0.0
    attr_s: float = 0.0
    fp: np.ndarray | None = field(default=None, repr=False, compare=False)     # 头像指纹（见 fingerprint）

    @property
    def tap_box(self) -> tuple[float, float, float, float]:
        return (self.cx - 36.0, self.cy - 30.0, 72.0, 60.0)

    @property
    def text(self) -> str:
        return f"{ROLE_CN[self.role]}/{ATTR_CN[self.attr]}"


def _classify(book: PageBook, norm: np.ndarray, x: float, y: float, prefix: str, names: tuple[str, ...],
              scale: float = 1.0, pad: int = 4, size: int = ICON) -> tuple[str | None, float]:
    """(x, y) 是图标左上角（画面坐标）。scale ≠ 1 时先把那一小块缩回模板的大小再比。返回（哪一种 / None，相似度）。"""
    s = float(scale)
    x0, y0 = int(round(x - pad * s)), int(round(y - pad * s))
    x1, y1 = int(round(x + (size + pad) * s)), int(round(y + (size + pad) * s))
    if x0 < 0 or y0 < 0 or x1 > norm.shape[1] or y1 > norm.shape[0]:
        return None, 0.0
    roi = norm[y0:y1, x0:x1]
    if s != 1.0:
        roi = cv2.resize(roi, (size + 2 * pad, size + 2 * pad), interpolation=cv2.INTER_AREA)
    scores = []
    for n in names:
        t = book.tmpl.get(f"{prefix}{n}")
        if t is None or roi.shape[0] < t.shape[0] or roi.shape[1] < t.shape[1]:
            continue
        scores.append((float(cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED).max()), n))
    if not scores:
        return None, 0.0
    scores.sort(reverse=True)
    best, second = scores[0], (scores[1] if len(scores) > 1 else (0.0, ""))
    if best[0] >= ICON_THR and best[0] - second[0] >= ICON_GAP:
        return best[1], best[0]
    return None, best[0]


FP_BOX = (-52, -38, 68, 64)              # 头像中间一块（相对卡片中心的 x、y、宽、高）：避开左上角的“等级”、右上角的对勾、下沿的图标
FP_SAME = 0.85                           # 两张卡的指纹相似度到这个数就是同一个角色（录制里同一个角色 ≥0.98，不同角色 ≤0.80）


def fingerprint(norm: np.ndarray, cx: float, cy: float, scale: float = 1.0) -> np.ndarray | None:
    """卡片头像的指纹：同一个角色在不同页签、选中（变暗）没选中、PNG / JPG 里都几乎一样，不同角色差得远。

    scale = 这张卡相对名单里的卡放大了多少（「角色加入」里的小头像 0.48，招募页的大头像 1.26）：先按比例取同一块再比，
    大小不同的头像之间也对得上（录制里同一个角色 0.93～1.0）。
    """
    dx, dy, w, h = FP_BOX
    if scale == 1.0:
        x0, y0 = int(cx) + dx, int(cy) + dy
        if x0 < 0 or y0 < 0 or x0 + w > norm.shape[1] or y0 + h > norm.shape[0]:
            return None
        patch = norm[y0:y0 + h, x0:x0 + w]
    else:
        x0, y0 = cx + dx * scale, cy + dy * scale
        if x0 < 0 or y0 < 0 or x0 + w * scale > norm.shape[1] or y0 + h * scale > norm.shape[0]:
            return None
        m = np.float32([[scale, 0, x0], [0, scale, y0]])
        patch = cv2.warpAffine(norm, m, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    g = cv2.resize(patch, (17, 16), interpolation=cv2.INTER_AREA).astype(np.float32)
    g -= g.mean(axis=(0, 1), keepdims=True)
    n = float(np.linalg.norm(g))
    return g / n if n > 1e-3 else None


def same_card(a: np.ndarray | None, b: np.ndarray | None) -> float:
    return float((a * b).sum()) if a is not None and b is not None else 0.0


def icons_at(book: PageBook, norm: np.ndarray, cx: int, cy: int) -> tuple[str | None, float, str | None, float]:
    """普通大小的角色卡：读右下角的职能和属性。"""
    role, rs = _classify(book, norm, cx + ROLE_OFF[0], cy + ROLE_OFF[1], "ico_role_", ROLES)
    attr, as_ = _classify(book, norm, cx + ATTR_OFF[0], cy + ATTR_OFF[1], "ico_attr_", ATTRS)
    return role, rs, attr, as_


def _card(book: PageBook, norm: np.ndarray, cx: int, cy: int, **kw) -> Card:
    role, rs, attr, as_ = icons_at(book, norm, cx, cy)
    return Card(cx, cy, role, attr, role_s=rs, attr_s=as_, fp=fingerprint(norm, cx, cy), **kw)


def list_cards(book: PageBook, img: np.ndarray) -> list[Card]:
    """「队伍编组」名单里现在看得见的角色卡（普通战斗和首领战通用）。

    不按固定格子找，而是找每张卡左上角的“等级”两个字——名单被滑动过也照样对得上。
    右上角的排序要是「等级」才行：选了别的（比如「战力」），那里写的就不是“等级”了。
    """
    norm = to_norm(img)
    checks = [(x, y) for _, (x, y, _, _) in book.find_all(img, "team_check", max_n=24)]
    tags = [(x, y) for _, (x, y, _, _) in book.find_all(img, "team_tag", max_n=24)] if "team_tag" in book.marks else []
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)

    def make(cx: int, cy: int) -> Card:
        sel = any(abs(x - (cx + 20)) <= 30 and abs(y - (cy - 48)) <= 30 for x, y in checks)
        busy = any(abs(x - (cx - 23)) <= 30 and abs(y - (cy + 41)) <= 30 for x, y in tags)
        return _card(book, norm, cx, cy, selected=sel, busy=busy)

    found: list[Card] = []
    for lx, ly in card_labels(book, img, min_gap=30, max_n=40):
        cx, cy = lx + LV_TO_CENTER[0], ly + LV_TO_CENTER[1]
        k = round((cx - PICK_X0) / PICK_DX)
        if abs(cx - (PICK_X0 + PICK_DX * k)) > 6 or not 0 <= k < COLS:     # 不在列上的不是卡片（右上角排序按钮上也写着“等级”）
            continue
        if cy + 62 > LIST_BOTTOM + 4 or cy - 50 < 0:           # 下半截被成员栏挡住：图标看不见，也点不准
            continue
        found.append(make(cx, cy))
    # “等级”两个字偶尔会漏认一张（压在很亮的头像上时）：同一行的其他列上如果确实有一张读得出图标的卡，补上
    for cy in sorted({c.cy for c in found}):
        row = [c for c in found if abs(c.cy - cy) <= 3]
        for k in range(COLS):
            cx = PICK_X0 + PICK_DX * k
            if any(abs(c.cx - cx) <= 6 for c in row) or any(abs(c.cx - cx) <= 6 and abs(c.cy - cy) <= 3 for c in found):
                continue
            if float(gray[cy - 40:cy + 40, cx - 40:cx + 40].std()) < 12.0:
                continue
            c = make(cx, cy)
            if c.attr is not None or c.busy:
                found.append(c)
    found.sort(key=lambda c: (c.cy // 40, c.cx))
    for i, c in enumerate(found):
        c.index = i
    return found


DEFEAT_HP = (305, 117, 95, 264, 269)     # 首领战失败页面“第 N 战 失败”那一栏：第一个人血条的左边、每个人的间隔、血条宽、血条的上下沿


def defeat_hp(img: np.ndarray) -> list[float]:
    """首领战的失败页面上，上场的五个位置各还剩多少血（0～1，绿色那一段有多长）。空位和倒下的人都是 0。
    只有首领战的失败页面有这一栏（普通战的失败页面是一张提示图），是不是那种页面由调用的人先判断。"""
    norm = to_norm(img)
    x0, dx, w, y0, y1 = DEFEAT_HP
    out = []
    for i in range(SLOTS):
        p = norm[y0:y1, x0 + dx * i:x0 + dx * i + w].astype(np.int16)
        b, g, r = p[..., 0], p[..., 1], p[..., 2]
        green = (g > 150) & (r < 190) & (b < 140) & (g - r > 30)
        out.append(round(float((green.sum(axis=0) >= 3).mean()), 2))
    return out


BATTLE_HP = (261, 160, 120, 666, 674)       # 战斗画面底下那排头像的血条：最左边那格的 x、每格间隔、血条宽、上下两行（1280×720）


def battle_hp(img: np.ndarray, n: int = SLOTS) -> list[float]:
    """战斗中底下那排头像各还剩多少血（0～1），按“最前面的人 → 最后面的人”排。n = 这一队上了几个人。
    画面上那排头像是靠右对齐的，最右边是站在最前面的人（2026-11-16 录制：五人队最右边是坦克；三人队占右边三格）。
    放 UB、切画面的时候这一排不在，调用的人要先确认现在是「战斗中」的页面。"""
    norm = to_norm(img)
    x0, dx, w, y0, y1 = BATTLE_HP
    n = max(1, min(SLOTS, int(n)))
    out = []
    for i in range(SLOTS - 1, SLOTS - 1 - n, -1):
        p = norm[y0:y1, x0 + dx * i:x0 + dx * i + w].astype(np.int16)
        b, g, r = p[..., 0], p[..., 1], p[..., 2]
        green = (g > 150) & (r < 190) & (b < 140) & (g - r > 30)
        out.append(round(float((green.sum(axis=0) >= 3).mean()), 2))
    return out


def page_size(boss: bool) -> int:
    """「队伍编组」的名单一屏能完整看到几张卡：普通战两行 16 张；首领战上面多一栏「对首领的有效效果」，只放得下一行 8 张。"""
    return COLS if boss else 2 * COLS


def member_cards(book: PageBook, img: np.ndarray) -> list[Card | None]:
    """成员栏五个位置：有人的返回卡片（带职能、属性），空位返回 None。"""
    norm = to_norm(img)
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
    out: list[Card | None] = []
    for i in range(SLOTS):
        cx, cy = SLOT_X0 + SLOT_DX * i, SLOT_Y
        if float(gray[cy - 40:cy + 40, cx - 40:cx + 40].std()) < 12.0:
            out.append(None)
        else:
            out.append(_card(book, norm, cx, cy, index=i, selected=True))
    return out


def pick_cards(book: PageBook, img: np.ndarray) -> list[Card]:
    """开局「角色选择」名单里的角色卡。"""
    norm = to_norm(img)
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
    out = []
    for r, cy in enumerate(PICK_ROWS):
        for k in range(COLS):
            cx = PICK_X0 + PICK_DX * k
            if float(gray[cy - 40:cy + 40, cx - 40:cx + 40].std()) >= 12.0:
                out.append(_card(book, norm, cx, cy, index=r * COLS + k))
    return out


def recruit_cards(book: PageBook, img: np.ndarray) -> list[Card]:
    """「角色加入奖励」三选一：三张卡的职能和属性（认不出的那一项是 None）。"""
    norm = to_norm(img)
    x0, y0, dx, s = RECRUIT_ATTR
    out = []
    for i in range(3):
        ax = x0 + dx * i
        attr, as_ = _classify(book, norm, ax, y0, "ico_attr_", ATTRS, scale=s)
        role, rs = _classify(book, norm, ax - 26 * s, y0, "ico_role_", ROLES, scale=s)
        cx0, cy0, cdx, cs = RECRUIT_CARD
        out.append(Card(int(ax - 38 * s), int(y0 - 37 * s), role, attr, index=i, role_s=rs, attr_s=as_,
                        fp=fingerprint(norm, cx0 + cdx * i, cy0, cs)))
    return out


def locate_card(book: PageBook, norm: np.ndarray, cx: float, cy: float, scale: float, slack: int = 8) -> dict | None:
    """在 (cx, cy) 附近找一张放大倍数是 scale 的方头像：靠右下角的属性图标把位置对准到 1 像素以内。

    返回 {"cx", "cy", "role", "attr", "fp", "score"}；属性图标没找到（这里不是角色头像）返回 None。
    指纹对位置很敏感（偏 2 像素相似度就掉到 0.85 上下），所以不能直接用量出来的固定坐标。
    """
    size = max(8, int(round(ICON * scale)))
    ax0, ay0 = cx + ATTR_OFF[0] * scale, cy + ATTR_OFF[1] * scale
    x0, y0 = int(round(ax0)) - slack, int(round(ay0)) - slack
    if x0 < 0 or y0 < 0 or x0 + size + 2 * slack > norm.shape[1] or y0 + size + 2 * slack > norm.shape[0]:
        return None
    roi = norm[y0:y0 + size + 2 * slack, x0:x0 + size + 2 * slack]
    best: tuple[float, str | None, int, int] = (0.0, None, 0, 0)
    for a in ATTRS:
        t = book.tmpl.get(f"ico_attr_{a}")
        if t is None:
            continue
        tt = cv2.resize(t, (size, size), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        res = cv2.matchTemplate(roi, tt, cv2.TM_CCOEFF_NORMED)
        _, v, _, loc = cv2.minMaxLoc(res)
        if v > best[0]:
            best = (float(v), a, x0 + loc[0], y0 + loc[1])
    if best[1] is None or best[0] < ICON_THR:
        return None
    ax, ay = best[2], best[3]
    ccx, ccy = ax - ATTR_OFF[0] * scale, ay - ATTR_OFF[1] * scale
    role, _rs = _classify(book, norm, ax - (ATTR_OFF[0] - ROLE_OFF[0]) * scale, ay, "ico_role_", ROLES, scale=scale)
    return {"cx": ccx, "cy": ccy, "role": role, "attr": best[1], "fp": fingerprint(norm, ccx, ccy, scale), "score": best[0]}


def recruit_name_box(i: int) -> tuple[int, int, int, int]:
    x, y, w, h = RECRUIT_NAME
    return (x + RECRUIT_ATTR[2] * i, y, w, h)


def join_rows(img: np.ndarray) -> list[dict]:
    """「角色加入」对话框里的每一行：小头像的指纹 + 名字那一条在哪。空行不返回。

    每个角色进队都会弹这个对话框（开局 3 人、招募、印记格、商店买的），所以它是“头像 → 名字”最全的来源。
    """
    norm = to_norm(img)
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
    cx, cy0, dy, sc = JOIN_ROW
    nx, ny, nw, nh = JOIN_NAME
    out = []
    for r in range(JOIN_ROWS):
        cy = cy0 + dy * r
        if float(gray[cy - 24:cy + 24, cx - 24:cx + 24].std()) < 14.0:        # 这一行没有头像
            continue
        out.append({"row": r, "fp": fingerprint(norm, cx, cy, sc), "name_box": (nx, ny + dy * r, nw, nh)})
    return out


def mark_attrs(book: PageBook, img: np.ndarray) -> list[str | None]:
    """「获得道具的机会」是连结印记时：三个选项各是什么属性。不是印记页（是遗物）时三个都是 None。"""
    norm = to_norm(img)
    x0, y0, dx, s = MARK_ATTR
    out = []
    for i in range(3):
        best: tuple[str | None, float] = (None, 0.0)
        for sc in (s - 0.05, s, s + 0.05):                   # 这个徽标的大小量得没那么准，前后各试一档
            a, v = _classify(book, norm, x0 + dx * i, y0, "ico_attr_", ATTRS, scale=sc, pad=5)
            if a is not None and v > best[1]:
                best = (a, v)
        out.append(best[0])
    return out


def _stars(norm: np.ndarray, i: int) -> int:
    x, y, w, h = RELIC_STARS
    p = norm[y:y + h, x + RELIC_BADGE[2] * i:x + RELIC_BADGE[2] * i + w].astype(np.int16)
    yellow = ((p[..., 2] > 215) & (p[..., 1] > 170) & (p[..., 0] < 130)).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(yellow, connectivity=8)
    return int(sum(1 for k in range(1, n) if st[k][4] >= 60))     # 一颗星大约 150～200 个黄像素


def relic_options(book: PageBook, img: np.ndarray) -> list[tuple[str | None, int]]:
    """「获得道具的机会」是迷宫遗物时：三个选项各是（系列, 星数）。认不出系列的是 (None, 星数)。"""
    norm = to_norm(img)
    x0, y0, dx = RELIC_BADGE
    out = []
    for i in range(3):
        ser, _ = _classify(book, norm, x0 + dx * i, y0, "ico_series_", SERIES, pad=5, size=44)
        out.append((ser, _stars(norm, i)))
    return out


def weak_attr(book: PageBook, img: np.ndarray) -> str | None:
    """「战斗准备」：敌人的弱点属性。没有弱点（一条横线）或者认不出，返回 None。"""
    norm = to_norm(img)
    x, y, w, h = WEAK_ROI
    roi = norm[y:y + h, x:x + w]
    best: tuple[float, str | None] = (0.0, None)
    for s in (1.0, 1.1, 1.2, 1.3):
        r = roi if s == 1.0 else cv2.resize(roi, None, fx=1 / s, fy=1 / s, interpolation=cv2.INTER_AREA)
        for a in ATTRS:
            t = book.tmpl.get(f"ico_attr_{a}")
            if t is None or r.shape[0] < t.shape[0] or r.shape[1] < t.shape[1]:
                continue
            v = float(cv2.matchTemplate(r, t, cv2.TM_CCOEFF_NORMED).max())
            if v > best[0]:
                best = (v, a)
    return best[1] if best[0] >= 0.75 else None


def active_tab(img: np.ndarray, boss: bool = False) -> str | None:
    """名单上面那排页签现在选中的是哪一个（选中的是蓝底白字，其余白底）。"""
    norm = to_norm(img)
    y = TAB_Y[bool(boss)]
    best = (0.0, None)
    for name, x in TAB_X.items():
        p = norm[y - 10:y + 10, x - 40:x + 40].astype(np.int16)     # 整个页签：选中的那个是蓝底（红色分量低），其余是白底
        blue = float(((p[..., 2] < 150) & (p[..., 0] - p[..., 2] > 40)).mean())
        if blue > best[0]:
            best = (blue, name)
    return best[1] if best[0] >= 0.5 else None


def tab_box(name: str, boss: bool = False) -> tuple[float, float, float, float]:
    return (TAB_X[name] - 30.0, TAB_Y[bool(boss)] - 9.0, 60.0, 18.0)
