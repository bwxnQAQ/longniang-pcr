"""读角色：到游戏的「角色」页，把账号里每个角色现在显示的头像和名字读一遍，记进头像库（chars.py 的 sightings）。

只用来认人，不读技能、不参与策略。新角色上线以后再跑一次就补上了；给某个角色换过头像（显示切换）以后再跑一次，新头像也会记上。

走法：角色一览（列表）→ 点第一张卡 → 「角色强化」页：
      上面蓝色横条里是名字，左下角是这个角色现在显示的方头像（和黎明界里的卡片是同一张图）；
      读完点右边的 ▶ 换下一个角色，一直点到又回到第一个角色为止。
这一趟只点两个地方：列表里的第一张卡、「角色强化」页右边的 ▶。
「角色强化」页上的 品级提升、自动强化、装备、★变更、显示切换里的选项 一律不碰——每次点 ▶ 之前都要先确认名字横条在；不在就停下。

真机上学到的（2026-11-17）：
  - 横条上**只有本名，不带版本**：凯露（夏日）、凯露（新年）的横条上都只写“凯露”。所以这里读到的是“本名 + 头像”，
    是哪个版本要等资料站的头像（菜单 17）来分——chars.resolve_sightings。
  - 横条的宽度跟着名字长短变（“未奏希＆美美＆镜华”的横条比“斑比”的宽一倍），所以先量横条的左右两头再去读里面的字。
  - 名字读不出来、或者读出来的字名单里没有（“碧”读成了“珀”）：不停，头像照记，等头像去认。连续 6 个都这样才停。
  - 是不是换了人、是不是转完一圈回到了第一个：看头像，不看名字（不同版本的名字是一样的）。
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from .. import chars as CH
from .. import ocr
from ..runner import Halt
from ..vision import cards as CD
from ..vision.pages import NORM_H, NORM_W, PageBook, to_norm

TITLE_BOX = (76, 14, 180, 48)            # 左上角的页面标题（“角色一览” / “角色强化”）
BANNER_Y = (100, 128)                    # 名字横条里面的上下范围（真机上量的：横条 y 96～131）
BANNER_MID = 331                         # 横条左右居中在这（“斑比”的横条 x 234～427，“未奏希＆美美＆镜华”的 173～488）
ICON = (98, 568, 0.76)                   # 左下角方头像：中心 x、y，相对黎明界名单卡片的缩放
NEXT_BOX = (1238, 344, 26, 32)           # 右边的 ▶（真机上量的：箭头 x 1232～1268、y 330～390，中心约 (1250, 360)）
FIRST_CARD = (110, 160, 230, 70)         # 列表里第一张卡的中间一块（避开右上角的收藏星和右下角的徽章）
MAX_CHARS = 600
UNREAD_RUN = 6                           # 连续这么多个角色的名字都读不出来：不是个别字的问题，停下


def banner_extent(norm: np.ndarray) -> tuple[int, int] | None:
    """名字的蓝色横条从哪到哪（x0, x1）。横条不在（被对话框盖住、变暗、不是这一页）返回 None。"""
    band = norm[BANNER_Y[0]:BANNER_Y[1]].astype(np.int16)
    b, r = band[..., 0], band[..., 2]
    on = ((r < 125) & (b > 140) & (b - r > 70)).mean(axis=0) >= 0.12        # 这一列有没有横条的蓝色（字盖住的地方蓝的少，但上下还露着一点）
    if not on[BANNER_MID - 30:BANNER_MID + 30].any():
        return None
    xs = np.where(on)[0]
    x0 = x1 = int(xs[np.abs(xs - BANNER_MID).argmin()])
    while True:                                   # 从中间往两边长，字盖住的窄缝（8 像素以内）跨过去
        left = xs[(xs < x0) & (xs >= x0 - 9)]
        right = xs[(xs > x1) & (xs <= x1 + 9)]
        if not len(left) and not len(right):
            break
        x0 = int(left.min()) if len(left) else x0
        x1 = int(right.max()) if len(right) else x1
    if x1 - x0 < 120 or not (x0 <= BANNER_MID <= x1) or abs((x0 + x1) / 2 - BANNER_MID) > 25:
        return None
    return x0, x1


def banner_visible(norm: np.ndarray) -> bool:
    return banner_extent(norm) is not None


def name_box(extent: tuple[int, int]) -> tuple[int, int, int, int]:
    """横条里面读名字的那一块（两头的圆角各让开几个像素）。"""
    return (extent[0] + 6, BANNER_Y[0], extent[1] - extent[0] - 12, BANNER_Y[1] - BANNER_Y[0])


class RosterScan:
    def __init__(self, dev: Any, book: PageBook, human: Any, log: Any, stop: Any, chars: CH.CharBook,
                 max_chars: int = MAX_CHARS, patience: float = 1.0):
        self.dev, self.book, self.human, self.log, self.stop, self.chars = dev, book, human, log, stop, chars
        self.max_chars = max_chars
        self.patience = patience
        self.taps = 0
        self.raw: list[str] = []                 # 最近一次读名字时每种读法读到的字（写进记录）
        self.text = ""                           # 最近一次横条上读到的字（对没对上名单都记着，名单更新以后可以重对）
        self.how: str | None = None              # 上一个名字是哪种读法读对的：下一个先试它
        self.count = 0                           # 这一趟看了多少个角色
        self.seen: list[str] = []                # 每个角色横条上读到的本名（没读出来的是空串）
        self.new = 0                             # 其中头像是第一次见的
        self.unread: list[int] = []              # 第几个角色的名字没读出来（头像照记）

    # ---- 小工具 ----
    def _shot(self) -> np.ndarray:
        self.stop.check()
        img = self.dev.screenshot()
        self.log.keep(img)
        return img

    def _tap(self, box: tuple[float, float, float, float], label: str) -> None:
        w, h = self.dev.size
        sx, sy = w / NORM_W, h / NORM_H
        self.human.wait(self.human.react_delay())
        self.human.tap((box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy), label)
        self.taps += 1
        self.log.event("tap", label=label, box=list(box))

    def _wait(self, seconds: float) -> None:
        self.stop.sleep(seconds * self.patience)

    def _title(self, img: np.ndarray) -> str:
        seen = []
        for _how, text in ocr.label_reads(img, TITLE_BOX, ink=None):
            if "览" in text or "强化" in text:
                return text
            if text:
                seen.append(text)
        return " / ".join(seen)

    def _halt(self, img: np.ndarray, why: str) -> None:
        self.log.shot(img, "roster_stop", png=True)
        raise Halt(why)

    def _read(self, img: np.ndarray, norm: np.ndarray, extent: tuple[int, int]) -> tuple[str, dict | None]:
        """读横条上的本名和左下角的头像。名字是带描边的白字压在蓝条上，几种读法轮着试（见 ocr.label_reads），只认名单里有的本名。"""
        got = self.chars.read_base(img, name_box(extent), prefer=self.how)
        self.raw, self.text = got["raw"], got["text"]
        if got["base"]:
            self.how = got["how"]
        return got["base"], CD.locate_card(self.book, norm, *ICON)

    def _note(self, g_name: str | None, base: str) -> str:
        """这一个角色后面跟的说明：全名定下来了没有。"""
        if not base:
            return f"（读到的是“{self.text}”，名单里没有：头像先记着，等更新名单）" if self.text else "（名字没读出来，头像先记着）"
        n = len(self.chars.bases().get(base, []))
        if g_name:
            return "" if g_name == base and n <= 1 else f"→ {g_name}"
        if n <= 1:
            return "（名单里只有 1 个版本，可已经看到不止一张头像：名单不全，等更新名单）"
        return f"（名单里有 {n} 个版本，等资料站的头像来分）"

    # ---- 主流程 ----
    def run(self) -> dict[str, Any]:
        t0 = time.time()
        if not ocr.available():
            raise Halt("这台电脑上的文字识别（OCR）没装好，读不了名字：" + ocr.why_missing())
        self.log.event("ocr", line=ocr.line_mode())
        entered = tapped_first = False
        done = False                                  # 转了一圈回到第一个角色（或者名单到头了）= 读完了
        # 以前完整读过一遍的（老的库没有这个记号、但读到的不少，也算）：这一次中途停下也不作废——读到的头像是攒着的，只会多不会少。
        # 从来没读完过的：先记成“没读完”，中途停下的话，这份名单不拿来判断“有没有这个角色”
        if not (self.chars.scan.get("done") or (not self.chars.scan and len(self.chars.roster) >= 30)):
            self.chars.scan = {"done": False, "count": 0}
        first: np.ndarray | None = None               # 第一个角色的头像：转一圈回到它就算读完
        prev: np.ndarray | None = None
        last_read: tuple[str, np.ndarray] | None = None
        bad = stuck = noname = unread_run = 0
        while True:
            img = self._shot()
            norm = to_norm(img)
            # 「角色强化」页的记号：名字的蓝色横条在（被别的东西盖住就不在了）。横条不在时才去读左上角的标题，看是不是还在列表上
            extent = banner_extent(norm)
            if extent is None:
                title = self._title(img)
                if "览" in title and not entered and not tapped_first:
                    self.log.say("  现在是：角色一览。点第一张卡进去。")
                    self._tap(FIRST_CARD, "列表里的第一张角色卡")
                    self._wait(1.2)
                    tapped_first, bad = True, 0       # 只点这一次；之后等它切过去
                    continue
                bad += 1
                if bad <= 6:                          # 页面还在切换
                    self._wait(0.5)
                    continue
                where = "读到一半回到了角色列表" if ("览" in title and entered) else f"名字的横条找不到了（左上角读到的是“{title}”）：不是「角色强化」页，或者有东西挡着"
                self._halt(img, f"{where}，停下。请把游戏停在「角色」列表或者某个角色的强化页再来")
            entered = True
            base, icon = self._read(img, norm, extent)
            if icon is None or icon["fp"] is None:
                bad += 1
                if bad <= 4:
                    self._wait(0.4)
                    continue
                self._halt(img, "「角色强化」页上左下角的头像没找到，停下（画面已存下来）")
            fp = icon["fp"]
            if not base and noname < 3:               # 名字没读出来：多半是换角色的过渡还没完，等一下再读几次
                noname += 1
                last_read = None
                self._wait(0.35)
                continue
            # 换角色时有过渡：同一个名字、同一张头像连续读到两次才算数
            if last_read is None or last_read[0] != base or CD.same_card(last_read[1], fp) < 0.9:
                last_read = (base, fp)
                self._wait(0.25)
                continue
            bad = noname = 0
            if prev is not None and CD.same_card(prev, fp) >= 0.9:          # ▶ 点了但还是这个角色（看头像，不看名字）
                stuck += 1
                if stuck >= 3:
                    self.log.say("  点了几次 ▶ 都还是同一个角色：名单只有这些，结束。")
                    done = True
                    break
            else:
                stuck = 0
                if first is not None and CD.same_card(first, fp) >= 0.9:
                    self.log.say("  又回到了第一个角色：全部读完。")
                    done = True
                    break
                self.count += 1
                how = self.chars.add_sighting(base, fp, icon["role"], icon["attr"], text=self.text)
                g = next((x for x in self.chars.sightings if CD.same_card(x["fp"], fp) >= CH.SAME_SIGHT), {})
                self.seen.append(base)
                self.new += how == "new"
                what = f"{CD.ROLE_CN[icon['role']]}/{CD.ATTR_CN[icon['attr']]}"
                self.log.say(f"  [{self.count:3d}] {base or self.text or '？'}　{what}　{self._note(g.get('name'), base)}".rstrip())
                self.log.event("roster", n=self.count, base=base, name=g.get("name"), via=g.get("via"), role=icon["role"], attr=icon["attr"],
                               how=how, read=self.how if base else None, raw=self.raw, box=list(name_box(extent)))
                self.log.shot(ocr.cut(img, (extent[0] - 4, BANNER_Y[0] - 6, extent[1] - extent[0] + 8, BANNER_Y[1] - BANNER_Y[0] + 12)),
                              f"name_{self.count:03d}")          # 【测试】每个角色的名字横条存一小张，读错了回头好查
                if base:
                    unread_run = 0
                else:
                    unread_run += 1
                    self.unread.append(self.count)
                    if len(self.unread) <= 3:
                        self.log.shot(img, f"roster_unread_{self.count}", png=True)
                    if unread_run >= UNREAD_RUN:
                        self._halt(img, f"连续 {UNREAD_RUN} 个角色的名字都没读出来（最后一次读到的是 {self.raw}），不像是个别字的问题，停下")
                if first is None:
                    first = fp
                if self.count % 10 == 0:
                    self.chars.save()
                if self.count >= self.max_chars:
                    self.log.say(f"  已经读了 {self.count} 个，到上限了，结束。")
                    break
            prev = fp
            self._tap(NEXT_BOX, "▶ 下一个角色")
            last_read = None
            self._wait(0.6)
        # 读完一圈了才算数：编队时要靠这份名单分“玩家自己有的角色”和“黎明界借的角色”，只读了一半的话没读到的会被当成没有
        if done:
            self.chars.scan = {"done": True, "count": self.count}
        st = self.chars.resolve_sightings()
        self.chars.save()
        res = {"ok": True, "done": bool(done), "count": self.count, "read": sum(1 for b in self.seen if b), "new": self.new, "unread": len(self.unread),
               "named": st["named"], "split": st["split"], "library": st["total"], "taps": self.taps, "seconds": round(time.time() - t0, 1)}
        self.log.event("done", **res)
        return res
