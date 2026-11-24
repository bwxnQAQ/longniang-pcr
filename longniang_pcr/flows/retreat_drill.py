"""出发 → 撤退 演练（阶段 1 的验收流程）。

从迷宫首页出发，选公会、关掉出发奖励、去地图，然后点「撤退（无报酬）」回到迷宫首页。
这一趟不打任何战斗，出发时扣的通行证会原样退回（阶段 0 实测），所以零成本，
正好用来检验：截图、页面识别、拟人点击、单步确认、紧急停止、日志。

为了不出岔子，流程里多看了三处：
- 没见到「公会选择确认」就到了地图 → 说明有一局正在进行中，不替你撤退，停下；
- 「结束确认」里没有“将返还迷宫通行证”这行字 → 不点确认，停下；
- 回到迷宫首页后，通行证数字那一小块要和出发前一模一样，否则报出来。
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from ..runner import Halt, NBox, Runner, Seen

# 各页面上要点的位置（1280×720 坐标）。全部对照录制里你手点的位置核对过。
BOX: dict[str, NBox] = {
    "home.adventure": (688, 656, 64, 50),         # 主页底部导航的「冒险」
    "adventure.lab": (1075, 490, 150, 95),        # 冒险页的「黎明界迷宫」
    "lab_home.go": (705, 376, 160, 56),           # 迷宫首页的「出发」
    "guild_confirm.go": (824, 606, 232, 52),      # 公会选择确认的「出发」
    "depart_reward.close": (524, 612, 226, 48),   # 出发奖励的「关闭」
    "pick3.map": (60, 624, 52, 48),               # 角色选择左下角的「地图」
    "map.retreat": (815, 626, 190, 48),           # 地图的「撤退（无报酬）」
    "end.ok": (668, 470, 234, 48),                # 结束确认的「确认」
}
GUILD_BTN_DY = 98          # 公会名下方「选择」按钮中心相对公会名顶边的距离
GUILD_BTN = (140, 42)      # 「选择」按钮里可以点的范围（宽、高）


def guild_button(mark_box: tuple[int, int, int, int]) -> NBox:
    x, y, w, h = mark_box
    cx = x + w / 2
    return (cx - GUILD_BTN[0] / 2, y + GUILD_BTN_DY, GUILD_BTN[0], GUILD_BTN[1])


class RetreatDrill:
    name = "出发→撤退演练"

    def __init__(self, runner: Runner, guild_mark: str = "guild_cile", guild_name: str = "慈乐之音"):
        self.r = runner
        self.guild_mark = guild_mark
        self.guild_name = guild_name
        self.pass_before: np.ndarray | None = None
        self.seen_confirm = False
        self.seen_pick3 = False                      # 见过「角色选择」了：之后的地图才是可以撤退的地图
        self.ended = False                           # 已经在「结束确认」里点了确认
        self.departed = False
        self.result: dict[str, Any] = {}

    def _same_pass(self, img: np.ndarray) -> tuple[bool, float]:
        now = self.r.book.crop(img, "pass_count")
        assert self.pass_before is not None
        diff = float(np.abs(now.astype(np.int16) - self.pass_before.astype(np.int16)).mean())
        return diff < 2.5, diff

    def run(self) -> dict[str, Any]:
        r = self.r
        t_start = time.time()
        t_depart: float | None = None
        repeats: dict[str, int] = {}
        while True:
            s: Seen = r.observe()
            page = s.page
            repeats[page] = repeats.get(page, 0) + 1
            if repeats[page] > 6:
                raise Halt(f"在「{s.res.name}」上已经试了 {repeats[page] - 1} 次还没过去，停下")

            if page == "lab_home":
                if self.departed and self.seen_confirm:
                    same, diff = self._same_pass(s.img)
                    r.log.shot(s.img, "lab_home_after", png=True)
                    self.result = {"ok": same, "pass_diff": round(diff, 2), "taps": r.taps,
                                   "seconds": round(time.time() - t_start, 1),
                                   "cycle_seconds": round(time.time() - t_depart, 1) if t_depart else None}
                    r.log.event("done", **self.result)
                    return self.result
                self.pass_before = r.book.crop(s.img, "pass_count")
                r.log.shot(s.img, "lab_home_before", png=True)
                if r.tap(s, BOX["lab_home.go"], "出发") != "changed":
                    self.departed = True
                    t_depart = t_depart or time.time()
                    r.wait_leave(page)
            elif page == "home" and not self.departed:
                r.tap(s, BOX["home.adventure"], "冒险")
                r.wait_leave(page)
            elif page == "adventure" and not self.departed:
                r.tap(s, BOX["adventure.lab"], "黎明界迷宫")
                r.wait_leave(page)
            elif page == "guild_select" and self.departed:
                score, mbox = r.book.find_mark(s.img, self.guild_mark)
                if score < float(r.book.marks[self.guild_mark].get("thr", 0.8)):
                    raise Halt(f"公会选择页上没找到「{self.guild_name}」（相似度 {score:.2f}）。"
                               f"阶段 1 还不会左右滑动找公会，请先把它滑到看得见的位置")
                r.tap(s, guild_button(mbox), f"{self.guild_name} 的「选择」")
                r.wait_leave(page)
            elif page == "dlg_guild_confirm" and self.departed:
                if r.tap(s, BOX["guild_confirm.go"], "出发（会先扣 1 张通行证，撤退时退回）") != "changed":
                    self.seen_confirm = True
                    r.wait_leave(page)
            elif page == "dlg_depart_reward" and self.seen_confirm:
                r.tap(s, BOX["depart_reward.close"], "关闭")
                r.wait_leave(page)
            elif page == "dlg_pick3" and self.seen_confirm:
                if r.tap(s, BOX["pick3.map"], "地图（不选角色，直接去地图）") != "changed":
                    self.seen_pick3 = True
                r.wait_leave(page)
            elif page == "map":
                if not self.seen_confirm:
                    raise Halt("点了出发就直接到了地图，说明有一局正在进行中。演练不会替你撤退这一局，停下")
                if self.ended:
                    r.wait_leave(page, 20.0)         # 撤退已经确认，地图只是还没切走：等它自己回迷宫首页
                elif not self.seen_pick3:
                    r.wait_leave(page, 4.0)          # 刚出发：出发奖励和角色选择还没弹出来，先不动
                else:
                    r.tap(s, BOX["map.retreat"], "撤退（无报酬）")
                    r.wait_leave(page)
            elif page == "dlg_end" and self.seen_pick3:
                if not r.book.has_mark(s.img, "end_refund"):
                    r.log.shot(s.img, "end_without_refund", png=True)
                    raise Halt("「结束确认」里没看到“将返还迷宫通行证”这行字，不点确认，停下")
                if r.tap(s, BOX["end.ok"], "确认（撤退，退回通行证）") != "changed":
                    self.ended = True
                r.wait_leave(page)
            else:
                r.log.shot(s.img, f"unexpected_{page}", png=True)
                raise Halt(f"这一步没想到会出现「{s.res.name}」，停下")
