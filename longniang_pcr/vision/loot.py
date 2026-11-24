"""读战利品（2026-11-24）：打通结算以后「获得道具」那张清单上每一行写的名字和数量。

清单长这样（2026-11-16 手动打通那一局的录制，第 13518、13530 帧）：标题「获得道具」，一句“收取了以下道具。”，下面一行一样东西——
图标、名字、橙色的“×数量”（比如 星幽光球（风）×500、特别装备炼成点数 ×20000、女神的秘石 ×5），一屏三行半，能往上拖；最下面是「关闭」。
饰品（EX 装备）是红宝箱里开出来的，难度 5 平均一局不到一件，所以到现在还没有带饰品的「获得道具」截图。

认饰品（2026-11-24 晚，用户录了十个公会的「可以获得的报酬」以后重做）：
  - 目录在 accessories.py：十个公会各一个系列 × 五种属性 = 50 件，名字是“黎明火轮 α 赞颂”这种；
  - 每一行两条路一起认：文字识别读名字（accessories.identify，不看中间那个 α），图标拿 50 张模板比（accicon.find）；
    两边说的是同一件 → 认准了；只有一边认出来 → 按那一边；两边说的不一样 → 按图标（图标是游戏画的，不会“读错字”），日志里写明；
  - 没有读字的组件时只靠图标：数量按 1 件算（图标上没写数量）。
「公会详情」里的清单和这张清单是同一种排法，所以拿那段录制当假画面测过；真的「获得道具」里出饰品的样子还没见过。
"""
from __future__ import annotations

import re
from typing import Any

import cv2
import numpy as np

from dataclasses import dataclass

from .. import accessories as AC
from .. import ocr as OCR
from . import accicon as AI
from .pages import to_norm

LIST_X = (300.0, 980.0)        # 清单在画面中间这一段（1280×720）
LIST_Y = (95.0, 600.0)         # 标题栏以下、「关闭」以上
SCROLL = ((640.0, 430.0), (640.0, 250.0))      # 把清单往上拖一截（从清单中间拖，一次差不多一行半）
MAX_SCROLLS = 12
ICON_NEAR = 36.0               # 一行字和一个图标的中心高度差在这以内，算同一行
HOW = {"name": "名字", "guild": "名字（系列名没读准，按这一局的公会补的）", "half": "名字（系列名只读对一个字）", "greek": "名字（系列名没读出来，按写的是 α 还是“阿尔法”分的）"}
SKIP = ("获得道具", "收取了以下", "关闭", "确认")
ROW = re.compile(r"^(.*?)[×xX✕＊*]\s*([\d,，.．]+)$")


def _clean(t: str) -> str:
    return t.replace(" ", "").replace("　", "").replace("(", "（").replace(")", "）")


def lines_of(items: list[tuple[str, tuple[int, int, int, int], float]]) -> list[tuple[str, tuple[float, float, float, float]]]:
    """把文字识别读到的一块块字按行并起来（一行东西常被读成“名字”“×500”两三块）。返回 [(这一行的字, 位置)]，从上到下。"""
    boxes = [(t, b) for t, b, s in items if s >= 0.4 and _clean(t)
             and LIST_X[0] <= b[0] + b[2] / 2.0 <= LIST_X[1] and LIST_Y[0] <= b[1] + b[3] / 2.0 <= LIST_Y[1]]
    boxes.sort(key=lambda x: x[1][1] + x[1][3] / 2.0)
    rows: list[list[tuple[str, tuple[int, int, int, int]]]] = []
    for t, b in boxes:
        cy = b[1] + b[3] / 2.0
        if rows:
            last = rows[-1]
            ly = sum(x[1][1] + x[1][3] / 2.0 for x in last) / len(last)
            lh = max(x[1][3] for x in last)
            if abs(cy - ly) <= 0.6 * max(lh, b[3]):
                last.append((t, b))
                continue
        rows.append([(t, b)])
    out = []
    for row in rows:
        row.sort(key=lambda x: x[1][0])
        x0, y0 = min(b[0] for _, b in row), min(b[1] for _, b in row)
        x1, y1 = max(b[0] + b[2] for _, b in row), max(b[1] + b[3] for _, b in row)
        out.append(("".join(_clean(t) for t, _ in row), (float(x0), float(y0), float(x1 - x0), float(y1 - y0))))
    return out


def parse_rows(items: list[tuple[str, tuple[int, int, int, int], float]]) -> list[tuple[str, int]]:
    """文字识别的结果 → [(名字, 数量)]。读不成“名字 × 数字”的行不要（被上下边缘切掉半行的、标题、按钮）。"""
    out: list[tuple[str, int]] = []
    for text, _box in lines_of(items):
        if any(k in text for k in SKIP):
            continue
        m = ROW.match(text)
        if not m:
            continue
        name = m.group(1).strip("·.。:：、，, ")
        digits = re.sub(r"\D", "", m.group(2))
        if len(name) < 2 or not digits or re.fullmatch(r"[\d,，.]+", name):
            continue
        out.append((name, int(digits)))
    return out


@dataclass(frozen=True)
class Row:
    """清单上的一行。"""
    name: str                   # 饰品是目录里的标准名字（黎明火轮α赞颂），别的东西是读到的名字
    count: int
    acc: AC.Acc | None = None   # 是饰品的话，是哪一件
    how: str = ""               # 饰品是怎么认出来的（给日志）
    raw: str = ""               # 这一行读到的原话


def _split(text: str) -> tuple[str, int | None]:
    """一行字 → （名字, 数量）。读不成“名字 × 数字”的，数量是 None。"""
    m = ROW.match(text)
    if not m:
        return text, None
    digits = re.sub(r"\D", "", m.group(2))
    return m.group(1).strip("·.。:：、，, "), (int(digits) if digits else None)


def rows_from(items: list[tuple[str, tuple[int, int, int, int], float]], hits: list[AI.Hit], guild: str | None = None) -> list[Row]:
    """文字识别的结果 + 图标比对的结果 → 这一屏的每一行。"""
    out: list[Row] = []
    free = list(hits)
    for text, box in lines_of(items):
        if any(k in text for k in SKIP):
            continue
        cy = box[1] + box[3] / 2.0
        name, count = _split(text)
        acc, how = AC.identify(name, guild)
        near = min(free, key=lambda h: abs(h.cy - cy), default=None)
        hit = near if near is not None and abs(near.cy - cy) <= ICON_NEAR else None
        if hit is not None:
            free.remove(hit)
        if hit is not None and acc is not None:
            if hit.acc == acc:
                how = "名字和图标都对上了"
            else:
                how, acc = f"图标（名字读成了「{acc.name}」，和图标对不上，按图标）", hit.acc
        elif hit is not None:
            acc, how = hit.acc, "图标（这一行的名字没读准）"
        elif acc is not None:
            how = HOW.get(how, "名字") + ("" if not hits and not AI.available() else "，图标没对上")
        if acc is not None:
            out.append(Row(acc.name, count or 1, acc, how, text))
        elif count is not None and len(name) >= 2 and not re.fullmatch(r"[\d,，.]+", name):
            out.append(Row(name, count, None, "", text))
    for hit in free:                                     # 图标认出来了，但这一行一个字都没读到（或者根本没有读字的组件）
        out.append(Row(hit.acc.name, 1, hit.acc, "图标（这一行的字没读出来，数量按 1 件算）", ""))
    return out


def read_rows(img: np.ndarray, guild: str | None = None) -> tuple[list[Row], list[str]]:
    """读现在画面上这一屏清单。返回（每一行, 读到的所有字——存进记录，读错了好查）。读字的组件和图标模板都没有就返回空。"""
    norm = to_norm(img)
    items = OCR.read_items(norm) if OCR.available() else []
    hits = AI.find(norm) if AI.available() else []
    return rows_from(items, hits, guild), [t for t, _b, _s in items][:60]


def read_list(img: np.ndarray, guild: str | None = None) -> tuple[list[tuple[str, int]], list[str]]:
    """老接口：[(名字, 数量)]。"""
    rows, texts = read_rows(img, guild)
    return [(r.name, r.count) for r in rows], texts


def can_read() -> bool:
    return OCR.available() or AI.available()


def moved(before: np.ndarray, after: np.ndarray) -> bool:
    """拖了一下以后清单动没动（没动 = 已经到底了）。只比清单那一块；角上飘的小光点不算动。"""
    a, b = (cv2.cvtColor(to_norm(x)[int(LIST_Y[0]):int(LIST_Y[1]), int(LIST_X[0]):int(LIST_X[1])], cv2.COLOR_BGR2GRAY) for x in (before, after))
    a, b = (cv2.resize(x, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA).astype(np.int16) for x in (a, b))
    return float(np.abs(a - b).mean()) > 2.0


def merge(found: dict[str, int], rows: list[Any]) -> int:
    """把新读到的一屏并进去。返回新出现了几样。rows 可以是 Row，也可以是 (名字, 数量)。
    拖动时同一行会被读到好几次，所以同名的取“一屏里看到的最多的那一次”；同一屏里同名的有两行（两件一样的饰品分两行列）就加起来。"""
    screen: dict[str, int] = {}
    for r in rows:
        name, n = (r.name, r.count) if isinstance(r, Row) else r
        screen[name] = screen.get(name, 0) + int(n)
    new = 0
    for name, n in screen.items():
        if name not in found:
            new += 1
            found[name] = n
        else:
            found[name] = max(found[name], n)
    return new


def as_event(found: dict[str, int], screens: int, texts: list[str]) -> dict[str, Any]:
    return {"items": dict(found), "screens": screens, "texts": texts[:60]}
