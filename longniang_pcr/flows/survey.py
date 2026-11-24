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

from ..plan import AreaMap
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
    def __init__(self, runner: Runner, area: int, thr: float = RT.EDGE_THR):
        self.r = runner
        self.thr = thr
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
        self.views += 1
        if not info:
            return 0, 0
        x_r, c_r = info[-1][0], info[-1][1]
        if info[-1][3] or x_r <= 870:                # 右边该有下一列的位置上什么都没有：这就是最后一列
            m.complete, m.last = True, c_r
        r.log.event("survey_view", offset=round(self.offset), cols=[[x, c, list(rows)] for x, c, rows, _ in info], complete=m.complete)
        return x_r, c_r

    def _realign(self, img: np.ndarray, moved: float, want: float) -> float:
        """拖动中没跟住时用：拿停稳后这一屏看到的列，和已经记下的地图对，定下地图到底挪了多少。
        试“量到的 moved 再加减几整列”这几种挪法：每种挪法下，画面上每一列该是第几列就定了；以前看过的列，格子在哪几行、是什么格子要对得上。
        只有一种挪法对得上（而且至少对上了一列以前看过的）才算数，返回那种挪法；否则停。"""
        r, m = self.r, self.map
        cols = [(x, tl) for x, tl in TL.columns(TL.find_tiles(r.book, img)) if 45 <= x <= 1235 and tl]
        good: list[tuple[int, float]] = []
        for k in (0, 1, -1, 2, -2):
            mv = moved + k * TL.COL_DX
            if abs(mv - want) > 1.6 * TL.COL_DX or mv * want < -60.0 * abs(want):
                continue
            off = self.offset + mv
            hits, bad = 0, False
            for x, tl in cols:
                pos = (x + off - self.x0) / TL.COL_DX
                c = int(round(pos))
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
