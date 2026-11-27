"""「伤害报告」：打完以后 WIN!（或者「战斗失败」）画面上那个按钮点开的弹窗，上面有我方每个人打了多少伤害。

2026-11-24 用户要的：每场打完看一下输出，哪个输出角色伤害高就调高比重；打输了如果是伤害不够，也看一眼，下一次换人有个依据。

2026-11-24 晚照真机截图把读法对上了（之前没见过这个弹窗，全靠“整张图找字”，而那条路在用户的机器上一个字都没读回来）：
  · 弹窗长什么样是固定的：左边「造成的伤害」最多五行，每行 = 头像 + 站位 + 伤害数字 + 一根橙色的条；下面正中一个「确认」。
    行是按伤害从高到低排的（不是按站位），所以谁是谁要靠头像去对——拿开打前成员栏里每个人的头像，在头像那一列里找同一张脸。
  · 橙色的条的长度 = 这个人的伤害 ÷ 伤害最高的人：不用读字就能知道每个人占几成（量过三张截图，误差不到 1%）。
  · 数字用“单行读法”读（已经知道字在哪，裁出来直接认——这条路在真机上一直是好的），读出来和条对不上就按条算。
  · 弹窗开没开、「确认」在哪：看颜色和固定位置，不靠读字。
老的“整张图找字”的读法留着当后备（弹窗长得不一样的时候用，比如没见过的多队首领战）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from .. import ocr as OCR
from . import team as TM
from .cards import FP_BOX
from .pages import to_norm

BTN_WIN = (1040, 40, 190, 26)            # WIN! 右上角的「伤害报告」（1280×720）；「战斗失败」画面上也在这个位置
BTN_BOSS = (905, 177, 290, 28)           # 首领战的 WIN!：「第 N 战 胜利」那一行右边的蓝色「伤害报告」
TITLE = (340, 44, 220, 26)               # 弹窗标题那一条蓝色（「伤害报告」四个字的左边）
BLANK = (345, 548, 600, 50)              # 弹窗里最后一行下面那块空白（纯白）
CONFIRM = (520, 614, 238, 48)            # 「确认」
ROW_Y, ROW_DY, ROWS = 130, 82, 5         # 第一行头像的上边、行距、最多几行
ICON = (356, 68)                         # 头像的左边、边长
NUM = (466, 18, 172, 32)                 # 伤害数字：（左边, 离行顶多远, 宽, 高）——右对齐，右边到 x≈634
BAR = (438, 55, 190, 10)                 # 橙色的条：（左边, 离行顶多远, 满格的宽, 高）
BAR_CAP = 8.4                            # 条两头是圆的：伤害是 0 也有这么宽
FACE_AREA = (345, 120, 90, 415)          # 头像那一列
FACE_SCALES = (0.5, 0.55, 0.6, 0.45, 0.65, 0.7)
CLOSE_GUESS = (590.0, 624.0, 100.0, 32.0)  # 没读到「关闭」两个字时试着点的地方：这个游戏里只有一个按钮的大弹窗，按钮都在下面正中（魔物详情、出发奖励、宝箱开封结果都是 y≈640）
BTN_READ = (1027, 33, 219, 38)           # 读这一块里有没有“伤害报告”四个字
SCALES = tuple(round(0.40 + 0.05 * i, 2) for i in range(23))      # 弹窗里的头像相对成员栏里的头像可能缩放了多少：0.40～1.50 挨个试
FACE_MIN = 0.62                          # 头像至少这么像才算找到（同一张图缩放以后一般 0.85 以上）
NEAR = 2.5                               # 数字离卡片中心最多这么多个“卡片宽”
CARD_HALF = 68                           # 成员栏里一张卡的半宽（1280×720，缩放前）


@dataclass
class Report:
    close: tuple[int, int, int, int] | None = None       # 「关闭」两个字的位置（1280×720）；None = 没找到
    title: bool = False                                  # 画面上有没有“伤害报告”这几个字
    numbers: list[tuple[int, tuple[int, int, int, int]]] = field(default_factory=list)     # 画面上所有纯数字：（数值, 位置）
    faces: list[tuple[float, tuple[int, int, int, int]] | None] = field(default_factory=list)   # 每个队员的头像找到没有：（相似度, 位置）
    damage: list[int | None] = field(default_factory=list)                                  # 每个队员的伤害（和传进来的头像一一对应）
    scale: float | None = None
    texts: list[str] = field(default_factory=list)
    open: bool = False                                   # 按固定的样子认出了这个弹窗（标题那条蓝色 + 下面的空白）
    rows: list[dict[str, Any]] = field(default_factory=list)   # 每一行：{"i": 第几行, "ratio": 条的长度（0～1）, "number": 伤害, "est": 数字是按条算出来的}
    unit: str = "damage"                                 # damage = 读到了真实的数字；bar = 一个数字都没读到，damage 里是按条的长度折的相对值（最高 = 10000）

    @property
    def matched(self) -> int:
        return sum(1 for d in self.damage if d is not None)


def parse_number(text: str) -> int | None:
    """「1,234,567」「123.4万」「1.2亿」→ 整数；不是一个数就返回 None。"""
    t = text.strip().replace(",", "").replace("，", "").replace(" ", "").replace("O", "0").replace("o", "0")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(万|亿)?", t)
    if not m:
        return None
    v = float(m.group(1)) * {"万": 1e4, "亿": 1e8, None: 1}[m.group(2)]
    return int(round(v))


BTN_KEY, BTN_THR = "btn_report", 0.70    # 按钮上“伤害报告”四个字的模板（从 2026-11-24 真机的 WIN! 截图上裁的）


def has_button(img: np.ndarray, book: Any = None) -> bool:
    """这个 WIN! 画面右上角有没有「伤害报告」按钮（只有第一张有，「获得道具」那张没有）。先拿模板比，比不上再让 OCR 读一下那一块。"""
    return button_seen(img, book)[0]


def button_seen(img: np.ndarray, book: Any = None) -> tuple[bool, str]:
    """（有没有按钮, 怎么判断的——写进记录里方便排查）。"""
    norm = to_norm(img)
    note = ""
    tmpl = getattr(book, "tmpl", {}).get(BTN_KEY) if book is not None else None
    if tmpl is not None:
        x, y, w, h = BTN_READ
        roi = cv2.cvtColor(norm[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)
        if roi.shape[0] >= tmpl.shape[0] and roi.shape[1] >= tmpl.shape[1] and float(roi.std()) > 1.0:
            score = float(cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED).max())
            note = f"模板 {score:.2f}"
            if score >= BTN_THR:
                return True, note
    text = OCR.read_region(norm, BTN_READ)
    return ("伤害" in text or "报告" in text), (note + "；" if note else "") + f"读到「{text}」"


def member_faces(img: np.ndarray, n: int = TM.SLOTS) -> list[np.ndarray | None]:
    """「队伍编组」成员栏里每个位置的头像中间那一块（开打前截下来，打完去伤害报告里找）。空位是 None。"""
    norm = to_norm(img)
    gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
    dx, dy, w, h = FP_BOX
    out: list[np.ndarray | None] = []
    for i in range(n):
        cx, cy = TM.SLOT_X0 + TM.SLOT_DX * i, TM.SLOT_Y
        patch = gray[cy + dy:cy + dy + h, cx + dx:cx + dx + w]
        out.append(patch.copy() if patch.shape == (h, w) and float(patch.std()) >= TM.HAS_ICON_STD else None)
    return out


def find_faces(gray: np.ndarray, faces: list[np.ndarray | None], scales: tuple[float, ...] | None = None) -> tuple[float | None, list[tuple[float, tuple[int, int, int, int]] | None]]:
    """在一张图里找这几张脸。大家缩放的比例是一样的：挑“每张脸最像的地方加起来最高”的那个比例。"""
    have = [f for f in faces if f is not None]
    if not have:
        return None, [None] * len(faces)
    best_scale, best_sum, best = None, -1.0, []
    for sc in (scales or SCALES):
        found, total = [], 0.0
        for f in faces:
            if f is None:
                found.append(None)
                continue
            t = cv2.resize(f, (max(8, int(round(f.shape[1] * sc))), max(8, int(round(f.shape[0] * sc)))), interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_LINEAR)
            if t.shape[0] >= gray.shape[0] or t.shape[1] >= gray.shape[1]:
                found.append(None)
                continue
            res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(res)
            found.append((float(score), (int(loc[0]), int(loc[1]), int(t.shape[1]), int(t.shape[0]))))
            total += float(score)
        if total > best_sum:
            best_scale, best_sum, best = sc, total, found
    return best_scale, [x if x is not None and x[0] >= FACE_MIN else None for x in best]


def is_open(norm: np.ndarray) -> bool:
    """伤害报告的弹窗现在开着吗（只看颜色：标题那一条是蓝的，最后一行下面是一片纯白）。"""
    x, y, w, h = TITLE
    b, g, r = norm[y:y + h, x:x + w].reshape(-1, 3).mean(0)
    x, y, w, h = BLANK
    blank = norm[y:y + h, x:x + w]
    return bool(b > 170 and b - r > 90 and 80 < g < 180 and float(blank.mean()) > 248 and float(blank.std()) < 4)


def result_row_box(team: int) -> tuple[int, int, int, int]:
    x, y, w, h = BTN_BOSS
    return x, y + 162 * (team - 1), w, h


def boss_button(norm: np.ndarray, team: int = 1) -> bool:
    """首领战 WIN! 上「第 N 战 胜利」那一行右边有没有蓝色的「伤害报告」按钮（看颜色：蓝底、中间有一截白字）。"""
    x, y, w, h = result_row_box(team)
    roi = norm[y:y + h, x:x + w].astype(np.int32)
    b, g, r = roi.reshape(-1, 3).mean(0)
    white = ((roi.min(axis=2) > 215).mean(axis=0) > 0.2)          # 哪几列有白字
    return bool(b > 170 and b - r > 60 and 0.05 < float(white.mean()) < 0.6)


def boss_result(norm: np.ndarray, team: int) -> str | None:
    """只在报告按钮亮起时读同一行的金色胜利或蓝色失败字样。"""
    if not boss_button(norm, team):
        return None
    y = 221 + 162 * (team - 1)
    b, g, r = norm[y:y + 40, 133:222].astype(np.int16).transpose(2, 0, 1)
    gold = ((r > 175) & (r - b > 65) & (g - b > 30)).sum()
    blue = ((b - r > 22) & (g - r > 12)).sum()
    if gold > 400 and blue < 100:
        return "win"
    if blue > 400 and gold < 100:
        return "lose"
    return None


def bar_ratio(norm: np.ndarray, i: int) -> float | None:
    """第 i 行那根条有多长（0～1；1 = 伤害最高的那个人）。这一行没有条（没有这个人）返回 None。"""
    x, dy, w, h = BAR
    y = ROW_Y + ROW_DY * i + dy
    hsv = cv2.cvtColor(norm[y:y + h, x:x + w], cv2.COLOR_BGR2HSV)
    orange = (hsv[..., 0] >= 8) & (hsv[..., 0] <= 28) & (hsv[..., 1] > 120) & (hsv[..., 2] > 180)
    frame = orange | ((hsv[..., 2] < 130) & (hsv[..., 1] < 130))          # 条没填满的部分是深灰的
    if int((frame.sum(axis=0) >= 3).sum()) < w * 0.8:
        return None
    cols = np.where(orange.sum(axis=0) >= 3)[0]
    if cols.size == 0:
        return 0.0
    return float(min(1.0, max(0.0, (int(cols.max()) + 1 - BAR_CAP) / (w - BAR_CAP))))


def read_number(norm: np.ndarray, i: int) -> int | None:
    """第 i 行的伤害数字（单行读法；几种读法轮着试，读成一个数就用）。读不出来返回 None。"""
    x, dy, w, h = NUM
    for _how, text in OCR.label_reads(norm, (x, ROW_Y + ROW_DY * i + dy, w, h), ink="dark"):
        digits = re.sub(r"[^0-9]", "", text.replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1"))
        if digits and len(digits) >= len(re.sub(r"\s", "", text)) - 2:      # 读出来的基本都是数字才算（混进一堆别的字的不要）
            return int(digits)
    return None


RATIO_TOL = 0.035                        # 数字之比和条的长度最多差这么多，才信读出来的数字


def settle_numbers(rows: list[dict[str, Any]]) -> str:
    """拿条的长度核对读出来的数字：对不上的（或者没读出来的）按条算。返回 "damage"（有真实数字）或 "bar"（一个都没读到，只有相对值）。"""
    if not rows:
        return "bar"
    top = rows[0]
    guess = sorted(r["number"] / r["ratio"] for r in rows[1:] if r.get("number") and r["ratio"] > 0.08)
    est0 = guess[len(guess) // 2] if guess else None                      # 别的行反推出来的“最高那个人是多少”
    n0 = top.get("number")
    if n0 and est0 and abs(n0 / est0 - 1.0) > 0.08 and len(guess) >= 2:   # 第一行读错了（别的行至少两个都说不是这个数）
        n0 = None
    if not n0:
        if est0 is None:
            for r in rows:
                r["number"], r["est"] = int(round(r["ratio"] * 10000)), True
            return "bar"
        n0, top["est"] = int(round(est0)), True
    top["number"] = int(n0)
    for r in rows[1:]:
        n = r.get("number")
        if not n or abs(n / n0 - r["ratio"]) > RATIO_TOL or n > n0:
            r["number"], r["est"] = int(round(r["ratio"] * n0)), True
    return "damage"


def find_in_rows(gray: np.ndarray, faces: list[np.ndarray | None], rows: int) -> tuple[float | None, list[tuple[float, tuple[int, int, int, int]] | None], list[int | None]]:
    """在头像那一列里找这几张脸，返回（缩放比例, 每张脸找到的地方, 每张脸在第几行）。一行只认一张脸（两张脸抢同一行时留最像的）。"""
    ax, ay, aw, ah = FACE_AREA
    area = gray[ay:ay + ah, ax:ax + aw]
    scale, found = None, [None] * len(faces)
    for scales in (FACE_SCALES, SCALES):             # 真机上量出来是 0.55 倍；对不上再把所有比例试一遍
        scale, found = find_faces(area, faces, scales)
        if any(f is not None for f in found):
            break
    found = [(f[0], (f[1][0] + ax, f[1][1] + ay, f[1][2], f[1][3])) if f is not None else None for f in found]
    row_of: list[int | None] = [None] * len(faces)
    best: dict[int, tuple[float, int]] = {}
    for k, f in enumerate(found):
        if f is None:
            continue
        cy = f[1][1] + f[1][3] / 2.0
        i = int(round((cy - (ROW_Y + ICON[1] / 2.0)) / ROW_DY))
        if 0 <= i < rows and abs(cy - (ROW_Y + ICON[1] / 2.0 + ROW_DY * i)) <= ICON[1] / 2.0 and (i not in best or f[0] > best[i][0]):
            best[i] = (f[0], k)
    for i, (_sc, k) in best.items():
        row_of[k] = i
    return scale, found, row_of


def read_report(img: np.ndarray, faces: list[np.ndarray | None], numbers: bool = True) -> Report:
    """读一张打开了的伤害报告。faces = 开打前成员栏里每个人的头像（member_faces 的结果，顺序就是 damage 的顺序）。
    numbers=False：不读数字，只量条（等弹窗稳下来的时候用，快）。弹窗不是固定的那个样子就交给老读法。"""
    norm = to_norm(img)
    if not is_open(norm):
        return read_generic(img, faces)
    rep = Report(damage=[None] * len(faces), faces=[None] * len(faces), open=True, title=True, close=CONFIRM)
    for i in range(ROWS):
        y = ROW_Y + ROW_DY * i
        if float(norm[y:y + ICON[1], ICON[0]:ICON[0] + ICON[1]].std()) < 12:      # 这一行没有头像：到头了
            break
        ratio = bar_ratio(norm, i)
        if ratio is None:
            break
        rep.rows.append({"i": i, "ratio": round(ratio, 4), "number": read_number(norm, i) if numbers and OCR.available() else None, "est": False})
    if not rep.rows:
        return rep
    rep.unit = settle_numbers(rep.rows)
    rep.numbers = [(int(r["number"]), (NUM[0], ROW_Y + ROW_DY * r["i"] + NUM[1], NUM[2], NUM[3])) for r in rep.rows]
    rep.scale, rep.faces, row_of = find_in_rows(cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY), faces, len(rep.rows))
    for k, i in enumerate(row_of):
        if i is not None:
            rep.damage[k] = int(rep.rows[i]["number"])
    return rep


def read_generic(img: np.ndarray, faces: list[np.ndarray | None]) -> Report:
    """老读法（后备）：整张图找字，数字离哪张脸近就是谁的。弹窗不是固定的那个样子时才用。"""
    norm = to_norm(img)
    rep = Report(damage=[None] * len(faces), faces=[None] * len(faces))
    items = OCR.read_items(norm)
    rep.texts = [t for t, _b, _s in items]
    for text, box, _score in items:
        clean = text.replace(" ", "")
        if ("关闭" in clean or clean in ("确认", "确定", "OK")) and rep.close is None:
            rep.close = box
        if "伤害报告" in clean or "伤害报" in clean:
            rep.title = True
        v = parse_number(clean)
        if v is not None:
            rep.numbers.append((v, box))
    if not rep.numbers:
        return rep
    rep.scale, rep.faces = find_faces(cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY), faces)
    # 每张脸配离它最近的数字（一个数字只配一张脸）：先配最近的那一对
    sc = rep.scale or 1.0
    half = CARD_HALF * sc
    centers = {i: (f[1][0] - FP_BOX[0] * sc, f[1][1] - FP_BOX[1] * sc) for i, f in enumerate(rep.faces) if f is not None}   # 每张卡的中心（头像那一块在卡片中心的左上方）
    on_card = {j for j, (_v, (x, y, w, h)) in enumerate(rep.numbers)                                                   # 落在某张卡里面的数字是“等级 368”、星数，不是伤害
               if any(abs(x + w / 2.0 - cx) <= half and abs(y + h / 2.0 - cy) <= half for cx, cy in centers.values())}
    pairs: list[tuple[float, int, int]] = []
    for i, (cx, cy) in centers.items():
        for j, (_v, (x, y, w, h)) in enumerate(rep.numbers):
            if j in on_card:
                continue
            dist = ((x + w / 2.0 - cx) ** 2 + (y + h / 2.0 - cy) ** 2) ** 0.5
            if dist <= NEAR * 2 * half:
                pairs.append((dist, i, j))
    used_i: set[int] = set()
    used_j: set[int] = set()
    for _d, i, j in sorted(pairs):
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        rep.damage[i] = rep.numbers[j][0]
    return rep


def as_event(rep: Report) -> dict[str, Any]:
    return {"close": list(rep.close) if rep.close else None, "title": rep.title, "scale": rep.scale, "matched": rep.matched,
            "numbers": [[v, list(b)] for v, b in rep.numbers][:40], "faces": [[round(f[0], 2), list(f[1])] if f else None for f in rep.faces],
            "damage": list(rep.damage), "texts": rep.texts[:60], "open": rep.open, "unit": rep.unit, "rows": list(rep.rows)}
