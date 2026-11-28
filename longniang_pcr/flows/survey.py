"""看全图：进了新区域先把地图从头拖到尾，记下每一列有哪些格子、哪格是极难、格子之间怎么连，再拖回来。

地图一屏只看得到三列左右，一个区域有 5～7 列，所以要拖两三下。拖的时候边拖边截图：
所有列都隔 350 像素排着，量“列的横坐标对 350 取余”前后差多少，就知道地图实际挪了多少
（拖多远、有没有惯性、是不是到头了，都不用猜）。每停下来一次，就把这一屏看到的格子和连线记进地图。

2026-11-19 真机上在区域 5 的最后一拖停过一次：画面里只剩一格商店和首领的大平台，拖动中的模糊画面上量不出余数
（22 次里丢了 8 次），当时的规矩是“丢得多就停”。现在改成：
  1. 中间丢了几次不要紧，重新量到的时候按丢之前的速度推一下这一段挪了几整列；
  2. 停稳以后拿这一屏看到的列和已经记下的地图对一遍（这一拖之前最右边那列，拖完一定还在画面里）：
     只有一种挪法对得上才往下走，对不上、或者两种都说得通，才停。
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from ..plan import KIND_NAMES, AreaMap
from ..runner import Halt, Runner, Seen
from ..vision import routes as RT
from ..vision import tiles as TL

HOME_X = 290                # 平时人物所在那一列的横坐标
MAX_DRAGS = 7


class Tracker:
    """边拖边量地图挪了多少（向左为正）。"""

    def __init__(self, runner: Runner, img: np.ndarray):
        self.r = runner
        self.phase = TL.grid_phase(runner.book, img)
        self.total = 0.0
        self.lost = 0
        self.ticks = 0
        self.biggest = 0.0
        self.img = img
        self.gap = 0                                 # 连着几次没量出来
        self.rate = 0.0                              # 最近每次大约挪多少（丢了以后拿它推）
        self.patched = 0                             # 有几段是靠推的

    def tick(self) -> float:
        img = self.r.dev.screenshot()
        ph = TL.grid_phase(self.r.book, img)
        self.ticks += 1
        if ph is None or self.phase is None:
            self.lost += 1
            self.gap += 1
            self.phase = ph if ph is not None else self.phase
            return 0.0
        d = TL.phase_step(self.phase, ph)
        if self.gap:                                 # 中间丢了几次：这一段可能挪了不止半列，按丢之前的速度推是几整列
            guess = self.rate * (self.gap + 1)
            d += round((guess - d) / TL.COL_DX) * TL.COL_DX
            self.patched += 1
        else:
            self.biggest = max(self.biggest, abs(d))
            self.rate = d if self.ticks <= 1 else 0.5 * self.rate + 0.5 * d
        self.gap = 0
        self.total += d
        self.phase = ph
        self.img = img
        return d

    def settle(self, timeout: float = 2.5, poll: float = 0.05) -> None:
        """抬手以后等地图停稳：连续三次几乎不动。"""
        still = 0
        end = time.time() + timeout
        while time.time() < end and still < 3:
            self.r.stop.sleep(poll)
            still = still + 1 if abs(self.tick()) < 1.5 else 0


class Survey:
    def __init__(self, runner: Runner, area: int, thr: float = RT.EDGE_THR, mid: bool = False):
        self.r = runner
        self.thr = thr
        self.mid = mid                               # 从区域中途开始看的（接手进行中的一局）：人物左边还有走过的列，那些列不记、对图时也不拿它们当错
        self.map = AreaMap(area=area)
        self.offset = 0.0                            # 地图比开始时往左挪了多少
        self.x0 = HOME_X                             # 开始时第 0 列（出发点 / 人物）的横坐标
        self.starts: list[int] = []                  # 第 1 列里现在能走的行
        self.views = 0

    def _col(self, x: float) -> int:
        return int(round((x + self.offset - self.x0) / TL.COL_DX))

    def _absorb(self, img: np.ndarray) -> tuple[int, int]:
        """把这一屏看到的记进地图。返回（最右一列的横坐标, 它的列号）。"""
        r, m = self.r, self.map
        tiles = TL.find_tiles(r.book, img)
        cols = [(x, tl) for x, tl in TL.columns(tiles) if self._col(x) >= 1]
        cols = self._fill_columns(img, cols)
        mask = RT.line_mask(img)
        info = []
        for x, tl in cols:
            c = self._col(x)
            known = [TL.Tile(x, ly, 1.0, 0.0, "", False, None) for ly in m.seen.get(c, set())]
            rows = TL.candidate_rows(tl + known)
            by_ly = {t.ly: t for t in tl}
            boss = any(t.label == "boss" for t in tl)
            for ly in rows:
                t = by_ly.get(ly)
                label = "boss" if boss else (t.kind if t is not None and t.kind else
                                             (TL.kind_at(r.book, img, x, ly) if 45 <= x <= 1235 else None))
                m.set_tile(c, ly, label, t is not None)
            info.append((x, c, rows, boss))
        for (xa, ca, ra, _), (xb, cb, rb, boss_b) in zip(info, info[1:]):
            if cb != ca + 1 or xb > 1262:
                continue
            if boss_b:                               # 首领前面只有一格商店，直接连上
                m.add_edges(ca, {(la, 416): 1.0 for la in ra})
            else:
                m.add_edges(ca, RT.column_edges(mask, xa, ra, xb, rb))
        for _x, c, _rows, boss in info:
            # 首领前面那一列（只有一格商店）这一屏没被认成格子、但上一屏看过：连线照样补上。暗的格子（商店）的边框有时认不出来——
            # 2026-11-27 一位玩家在区域 5 最后一屏就是这样（只认出了首领），以前会停在“第 6 列和下一列之间的连线没看到”
            if boss and c >= 2 and all(ci != c - 1 for _, ci, _, _ in info) and m.seen.get(c - 1):
                m.add_edges(c - 1, {(la, 416): 1.0 for la in sorted(m.seen[c - 1])})
        self.views += 1
        if not info:
            return 0, 0
        x_r, c_r = info[-1][0], info[-1][1]
        if info[-1][3] or x_r <= 870:                # 右边该有下一列的位置上什么都没有：这就是最后一列
            m.complete, m.last = True, c_r
        r.log.event("survey_view", offset=round(self.offset), cols=[[x, c, list(rows)] for x, c, rows, _ in info], complete=m.complete)
        return x_r, c_r

    def _fill_columns(self, img: np.ndarray, cols: list[tuple[int, list[TL.Tile]]]) -> list[tuple[int, list[TL.Tile]]]:
        """这一屏里前沿一格都没认出来的列：按它该在的横坐标，用平台颜色 + 图标再找一遍（TL.column_at），找到就补进 cols。

        find_tiles 认一列靠的是格子前沿，至少要认出一格。有的列平时只有一格的前沿认得出来（比如 事件 / 印记 / 事件：上面那格被印记的图标挡着、
        下面那格被底部界面挡着，只靠中间印记格，0.59，门槛 0.5），旁边格子图标上的闪光一闪就掉到门槛下面，整列就没了。
        2026-11-27、28 三位玩家的三次“第 [n] 列和下一列之间的连线没看到，地图不完整”都是这样（区域 1 的第 2 或第 4 列）：
        那一列和下一列的连线只有这一屏看得到，列没了连线就没记。——同样的事要是出在一屏的最右边，还会被当成“这就是最后一列”。

        该在哪：每一列隔 350 像素；这一屏有认出来的列，就从最近的那一列推（比累计的挪动量准），没有就按出发点和挪动量算。
        以前看过的列（self.map.seen）拿记下的行和类型去对；没看过的列要至少一格认得出图标 / 战斗标签才算数。
        """
        have = {self._col(x): x for x, _ in cols}

        def where(c: int) -> int:
            if have:
                near = min(have, key=lambda k: abs(k - c))
                return int(round(have[near] + (c - near) * TL.COL_DX))
            return int(round(self.x0 + c * TL.COL_DX - self.offset))

        out = list(cols)
        c = 1
        while where(c) <= 1210:                      # 再靠右，平台的右半边就出画面了
            x = where(c)
            if c not in have and x >= 70:
                seen = self.map.seen.get(c)
                known = {ly: self.map.rows.get(c, {}).get(ly) for ly in seen} if seen else None
                tl = TL.column_at(self.r.book, img, x, known)
                if tl:
                    out.append((x, tl))
                    self.r.log.say(f"      第 {c} 列的格子边框这一屏没认出来，按平台颜色和图标认的："
                                   f"{'、'.join(KIND_NAMES.get(t.kind, '？') for t in tl)}。", detail=True)
                    self.r.log.event("survey_fill", col=c, x=x, rows=[[t.ly, t.kind] for t in tl], known=bool(known))
            c += 1
        out.sort(key=lambda z: z[0])
        return out

    def _realign(self, img: np.ndarray, moved: float, want: float) -> float:
        """拖动中没跟住时用：拿停稳后这一屏看到的列，和已经记下的地图对，定下地图到底挪了多少。
        试“量到的 moved 再加减几整列”这几种挪法：每种挪法下，画面上每一列该是第几列就定了；以前看过的列，格子在哪几行、是什么格子要对得上。
        只有一种挪法对得上（而且至少对上了一列以前看过的）才算数，返回那种挪法；否则停。
        2026-11-27（V1.11）加了两样——一位玩家在区域 5 最后一拖停下：拖动中丢了 8 帧，量到 588（实际 700，差的不是整列）；
        停稳的画面里又只认出了首领那一列，左边的商店（上一屏看过的第 6 列）边框没认出来，于是“没有一种挪法对得上”：
        · 量到的数可能差着不是整列的一截，所以再按“看到的列必须落在整列上”反推几种挪法一起试；
        · 以前看过、按这种挪法该在画面里、这一屏却没被认成格子的列：直接去那个位置看图标（印记 / 遗物 / 事件 / 商店），
          记下的图标都对得上算对上了一列，有一个对不上就不是这种挪法。"""
        r, m = self.r, self.map
        cols = [(x, tl) for x, tl in TL.columns(TL.find_tiles(r.book, img)) if 45 <= x <= 1235 and tl]
        cands = [moved + k * TL.COL_DX for k in (0, 1, -1, 2, -2)]
        if cols:
            base = self.x0 - cols[0][0] - self.offset            # 看到的第一列挪完以后是第 c 列 ⇒ 挪了 c·COL_DX + base
            grid = lambda mv: round((mv - base) / TL.COL_DX) * TL.COL_DX + base      # noqa: E731
            # 量到的那几种：离“整列”不到 60 像素的就贴到整列上（看到的格子比拖动中量的准；也免得同一种挪法算成两种）
            cands = [grid(mv) if abs(grid(mv) - mv) <= 60.0 else mv for mv in cands]
            c0 = int(round((want - base) / TL.COL_DX))
            for c in (c0, c0 - 1, c0 + 1, c0 - 2, c0 + 2):       # 再加上想挪的距离附近的几种整列挪法
                mv = c * TL.COL_DX + base
                if all(abs(mv - o) > 1.0 for o in cands):
                    cands.append(mv)
        cands = [mv for i, mv in enumerate(cands) if all(abs(mv - o) > 1.0 for o in cands[:i])]
        good: list[tuple[int, float]] = []
        for mv in cands:
            if abs(mv - want) > 1.6 * TL.COL_DX or mv * want < -60.0 * abs(want):
                continue
            off = self.offset + mv
            hits, bad = 0, False
            for x, tl in cols:
                pos = (x + off - self.x0) / TL.COL_DX
                c = int(round(pos))
                if self.mid and c < 1 and abs(pos - c) * TL.COL_DX <= 45:
                    continue                         # 走过的列（人物所在的那一列和它左边的）：地图里没记，不比
                if abs(pos - c) * TL.COL_DX > 45 or c < 1:
                    bad = True
                    break
                seen = m.seen.get(c)
                if not seen:
                    continue
                # 以前看过这一列：这次看到的格子得落在那一列的行上（被界面挡住漏看一两格不算错），两次都认出类型的格子类型要一样
                may = set(TL.candidate_rows([TL.Tile(x, ly, 1.0, 0.0, "", False, None) for ly in seen]))
                was = m.rows.get(c, {})
                same = 0
                for t in tl:
                    now_kind = "boss" if t.label == "boss" else t.kind
                    if t.ly not in may or (was.get(t.ly) and now_kind and was[t.ly] != now_kind):
                        bad = True
                        break
                    same += 1 if (was.get(t.ly) and now_kind) or t.ly in seen else 0
                if bad:
                    break
                hits += 1 if same else 0
            shown = {int(round((x + off - self.x0) / TL.COL_DX)) for x, _ in cols}
            for c, rows_seen in (() if bad else sorted(m.seen.items())):
                x = c * TL.COL_DX + self.x0 - off
                if c < 1 or c in shown or not 45 <= x <= 1235:
                    continue
                was = {ly: k for ly, k in m.rows.get(c, {}).items() if ly in rows_seen and k in TL.ICON_KINDS}
                if not was:
                    continue
                now = {ly: TL.kind_at(r.book, img, int(round(x)), ly) for ly in was}
                if any(now[ly] and now[ly] != was[ly] for ly in was):
                    bad = True
                    break
                hits += 1 if all(now[ly] == was[ly] for ly in was) else 0
            if not bad and hits:
                good.append((hits, mv))
        best = max((h for h, _ in good), default=0)
        top = [mv for h, mv in good if h == best]
        r.log.event("survey_realign", moved=round(moved), want=round(want), fits=[[h, round(mv)] for h, mv in good])
        if len(top) != 1:
            raise Halt("拖动地图时没跟住，停稳以后拿看到的格子和记下的地图也对不出挪了多少"
                       + ("（没有一种挪法对得上）" if not top else "（有两种挪法都对得上）") + "，不敢按这次看到的排路线")
        if abs(top[0] - moved) > 1.0:
            r.log.say(f"      拖动中没跟住，量到的是 {moved:.0f} 像素；和记下的地图一对，实际挪了 {top[0]:.0f} 像素。")
        return top[0]

    def _drag(self, seen: Seen, dist: float, label: str) -> tuple[Seen, float] | None:
        """把地图拖 dist 像素（正数 = 往左拖，看右边）。返回（停稳后的画面, 实际挪了多少）。"""
        r = self.r
        rng = r.human.rng
        d = abs(dist)
        if dist > 0:
            sx = rng.uniform(max(d + 90.0, 760.0), 1190.0)
        else:
            sx = rng.uniform(90.0, min(1190.0 - d, 520.0))
        sy = rng.uniform(325.0, 480.0)
        ex, ey = sx - dist, sy + rng.uniform(-28.0, 28.0)
        tr = Tracker(r, seen.img)
        res = r.swipe(seen, (sx, sy), (ex, ey), label, duration=max(0.55, d / rng.uniform(640.0, 820.0)),
                      on_tick=tr.tick, hold_end=rng.uniform(0.16, 0.3))
        if res == "changed":
            return None
        if res == "manual":
            r.log.say("      你来拖的话我量不出挪了多少，这次看图作废。")
            raise Halt("看全图的时候改成了手动拖动，没法继续量")
        tr.settle()
        now = r.look()
        if now.page != "map":
            return None
        moved = tr.total
        bad = tr.lost > max(2, tr.ticks // 3) or tr.biggest > 150.0                 # 以前到这个程度就直接停了
        if bad or tr.patched:                                                     # 没跟住：停稳以后和记下的地图对一遍再定
            r.log.event("survey_track_bad", lost=tr.lost, ticks=tr.ticks, biggest=round(tr.biggest), patched=tr.patched, got=round(tr.total))
            end = TL.grid_phase(r.book, now.img)
            if end is not None and tr.phase is not None:                          # 停稳的画面量得准：把零头对齐到它上面
                moved += TL.phase_step(tr.phase, end)
            try:
                moved = self._realign(now.img, moved, dist)
            except Halt:
                if bad:
                    raise
                # 只丢了一两次（以前这种情况是直接信量到的数）：对不出来就还是信它
        r.log.event("survey_drag", want=round(dist), got=round(moved), ticks=tr.ticks, biggest=round(tr.biggest), lost=tr.lost)
        r.log.say(f"      地图挪了 {moved:.0f} 像素（想挪 {dist:.0f}）", detail=True)
        return now, moved

    def run(self, seen: Seen) -> AreaMap | None:
        """seen 是刚进区域、停稳了的地图。看完会把地图拖回原位。画面中途变了返回 None。"""
        r = self.r
        rc = TL.reachable(TL.find_tiles(r.book, seen.img))
        if not rc:
            return None
        self.x0 = rc[0].x - TL.COL_DX
        self.starts = sorted(t.ly for t in rc)
        r.log.say(f"      先看全图：把这个区域从头拖到尾，记下格子和连线，再拖回来。")
        x_r, _ = self._absorb(seen.img)
        cur = seen
        drags = 0
        while not self.map.complete and drags < MAX_DRAGS:
            want = float(np.clip(x_r - 300.0, 300.0, 880.0))     # 把这一屏最右边那列拖到左边去
            got = self._drag(cur, want, "向左拖动地图，看后面几列")
            drags += 1
            if got is None:
                return None
            cur, moved = got
            self.offset += moved
            if moved < 40.0:                         # 拖不动了：已经到头
                self.map.complete = True
                break
            x_r, _ = self._absorb(cur.img)
        if not self.map.complete:
            raise Halt(f"拖了 {drags} 次还没看到这个区域的尽头")
        back = 0
        while abs(self.offset) > 45.0 and back < MAX_DRAGS:
            want = -float(np.clip(self.offset, -880.0, 880.0))
            got = self._drag(cur, want, "把地图拖回人物所在的位置")
            back += 1
            if got is None:
                return None
            cur, moved = got
            self.offset += moved
            if abs(moved) < 25.0 and abs(self.offset) > 45.0:
                raise Halt(f"地图拖不回原位（还差 {self.offset:.0f} 像素）")
        if abs(self.offset) > 45.0:
            raise Halt(f"地图没拖回原位（还差 {self.offset:.0f} 像素）")
        missing = [c for c in range(1, self.map.last) if c not in self.map.edges]
        r.log.event("survey_done", area=self.map.area, last=self.map.last, views=self.views, drags=drags + back,
                    missing=missing, starts=self.starts,
                    rows={str(c): {str(ly): lab for ly, lab in rr.items()} for c, rr in self.map.rows.items()},
                    edges={str(c): {f"{la}>{lb}": s for (la, lb), s in e.items()} for c, e in self.map.edges.items()})
        if missing:
            raise Halt(f"第 {missing} 列和下一列之间的连线没看到，地图不完整")
        self.final = cur
        return self.map
