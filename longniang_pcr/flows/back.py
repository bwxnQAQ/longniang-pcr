"""回迷宫首页：从现在的画面（标题画面、登录奖励、主页、冒险页……）自己走回「迷宫首页」。

挂机时游戏换日、掉线以后走的就是这段路（afk.Recovery + 主页 / 冒险页那两下）。那一段的真画面还没在真机上见过，
所以单独拿出来做成一项测试：不用等到每天 5 点，在游戏主菜单里点「回到标题画面」，再跑这一项，就能看它走不走得回来。
每一步都存截图；路上只点「确认」「重试」「跳过」「关闭」「冒险」「黎明界迷宫」和画面中间；到了迷宫首页就停，不点「出发」。
"""
from __future__ import annotations

import time
from typing import Any

from ..runner import Halt, Runner, Seen
from .walk import BOX

IN_RUN = ("map", "battle", "battle_ready", "dlg_team", "dlg_pick3", "dlg_move", "win", "win_next", "defeat", "event", "dlg_shop",
          "recruit_pick", "relic_pick", "result", "dlg_chest_result")


class Back:
    name = "回迷宫首页"

    def __init__(self, runner: Runner):
        self.r = runner

    def run(self) -> dict[str, Any]:
        r = self.r
        if r.recovery is None:
            raise Halt("没有挂上“挂机恢复”，这一项做不了")
        if not r.recovery.can_see():
            raise Halt("这台电脑上读字的组件没装好：走回迷宫的路上全靠读画面上的字（见到密码、验证码、支付这些字要停），看不见就不走。在界面上点一次「准备运行环境」再试")
        r.recovery.begin("试一次：从现在的画面走回迷宫首页")
        t0, last, same, trail = time.time(), "", 0, []
        while True:
            s: Seen = r.observe()
            page = s.page
            same = same + 1 if page == last else 1
            last = page
            if not trail or trail[-1] != page:
                trail.append(page)
            if same > 4:
                r.log.shot(s.img, f"stuck_{page}", png=True)
                raise Halt(f"在「{s.res.name}」上点了 {same - 1} 次画面都没变，停下")
            if page == "lab_home":
                r.recovery.done(s.res.name)
                r.log.shot(s.img, "lab_home_reached", png=True)
                out = {"ok": True, "trail": trail, "taps": r.taps, "acts": r.recovery.acts, "pokes": r.recovery.pokes, "seconds": round(time.time() - t0, 1)}
                r.log.event("done", **out)
                return out
            if page == "dlg_daychange":
                if r.tap(s, BOX["daychange.ok"], "确认（日期变更：游戏会回到标题画面）") != "changed":
                    r.wait_leave(page)
            elif page in ("home", "adventure") and same >= 2 and r.recovery.nudge(s):
                r.pause(0.8)                         # 点了没反应：上面多半盖着弹窗，先把它弄掉
                last, same = "", 0
            elif page == "home":
                if r.tap(s, BOX["home.adventure"], "冒险") != "changed":
                    r.wait_leave(page)
            elif page == "adventure":
                if r.tap(s, BOX["adventure.lab"], "黎明界迷宫") != "changed":
                    r.wait_leave(page)
            elif page in IN_RUN:
                r.log.shot(s.img, f"in_run_{page}", png=True)
                raise Halt(f"游戏现在在一局里面（{s.res.name}）。这一项只管从游戏外面走回迷宫首页，不动一局里面的东西，停下")
            else:
                r.log.shot(s.img, f"unexpected_{page}", png=True)
                raise Halt(f"走回迷宫首页的路上没想到会出现「{s.res.name}」，停下（截图存了，把记录给我就能补上）")
