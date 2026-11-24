"""一个区域的地图和路线规划（纯计算，不碰画面）。

规则只有一条：这个区域里每一列极难都要走到。走不到（有哪一列的极难从现在的位置出发没有路能到，
或者两列极难不能在同一条路上走到）就算“走不满”，由流程决定重开。
极难数相同的路线之间按“这条路上的格子一共值多少分”挑（阶段 3，2026-11-17）；分数也一样再取靠上的。
每种格子值多少分在 ROUTE_VALUES 里，可以在 config/settings.json 的 walk.route_values 里改。
"""
from __future__ import annotations

from dataclasses import dataclass, field

ROW_NAMES = {240: "上", 316: "上", 416: "中", 516: "下", 592: "下"}


def row_name(ly: int) -> str:
    """行高 → 上 / 中 / 下。差一两个像素也照样认（取最近的一行），只用来写日志，不能因为它出错。"""
    return ROW_NAMES[min(ROW_NAMES, key=lambda y: abs(y - ly))]


KIND_NAMES = {"normal": "普通", "extreme": "极难", "boss": "首领", "mark": "印记", "relic": "遗物", "event": "事件", "shop": "商店",
              None: "非战斗"}
# “分数优先”时每种格子大约值多少分（难度 5 的最终分数，已经乘过 2.0）。每格固定的 200 分（格数）各条路一样，不算在内。
# 2026-11-18 按真机 01:19 那一趟（30 格）每一格前后的角色数 / 遗物数 / 金币重算过，金币也折成分数算进去了：
#   普通战 6 场：每场 +1 名角色、金币 1,110～1,260（平均 1,190）；极难 6 场：每场 +1 名角色 +1 个遗物、金币 1,365～1,635（平均 1,455）；
#   印记格 5 个：每个 +3 名角色、没有金币；遗物格 6 个：每个 +1 个遗物、没有金币；事件 3 个：金币 1,000～2,000，其中斗技场那个还 +1 名角色 +1 个遗物。
#   金币怎么折：多出来的金币最后是在商店里花掉的，边上那一笔买的是随机印记（每 1 分 4.5 金币）或 ★2 遗物（5.25），取 COIN_RATE = 5 金币 1 分。
#   普通战 = 战斗 200 + 角色 200 + 金币 1,190 ÷ 5 ≈ 640；极难战 = 战斗 2000 + 角色 200 + 遗物 400 + 金币 1,455 ÷ 5 ≈ 2,890；
#   印记格 = 3 名角色 600；遗物格 = 1 个遗物 400；
#   事件 ≈ 500：十个事件按 data/events.json 的默认选法算期望，平均 480 上下（斗技场选极难 ≈ 940、活动会场 ≈ 800、箱子 / 猜拳 ≈ 455、
#     公会管理协会 ≈ 445、迷路 / 石板 ≈ 400、钓鱼 / 老虎机 ≈ 310、野餐 ≈ 260），真机那 3 个平均 545。所以事件略高于遗物格——
#     两篇高分攻略（note あのあれ、台服《難度5 高分打法》）在“事件或遗物”的那一列也都写的是事件优先或两者皆可；想求稳把它调回 400 以下就先走遗物格。
#   商店：这张表里是 0（不买东西时的值）。会买东西以后它值多少要看手里有多少金币、在第几个区域，走图时由 shop_value() 现算；
#   认不出的格子按 unknown 算。
# 这些数只在“极难数相同的路线”之间起作用。按攻略和真机地图，实际会碰到的二选一只有：印记 / 事件、遗物 / 事件、印记 / 遗物、遗物 / 商店（区域 2）。
COIN_RATE = 5.0
ROUTE_VALUES = {"normal": 640, "extreme": 2890, "boss": 0, "mark": 600, "relic": 400, "event": 500, "shop": 0, "unknown": 250}
SHOP_RATE = 4.4            # 商店里划算的东西（★1 遗物 3.4、随机印记 4.5）平均每 1 分要这么多金币
SHOP_CAP = 13700           # 一家商店连更新两次，划算的东西全买下来大约要这么多金币（三批 × 4,275 + 更新 900）


def shop_value(coins: int | None, area: int = 3) -> float:
    """路过一家商店大约值多少分（排路线用，是估的）：手里的金币在这家店能换成多少分，再按区域打折。

    区域 1、2 打 2.5 折：这时候金币少，而且这些金币留到区域 3 的商店一样花得掉——攻略里区域 2“遗物或商店”那一列走的是遗物，
    只有去极难的路非得过商店时才进（进了就买）；所以早期的商店不该压过遗物格（400）。
    区域 3、4 打对折（这家不花、后面的商店多半也花得掉）；最后一个区域不打折（再不花就带不走了）。金币数没读出来按一个遗物格算。
    例：区域 2 手里 3,700 ≈ 210 分；区域 3 手里 12,000 ≈ 1,360 分；区域 5 手里 20,000 ≈ 3,100 分（一家店最多按 13,700 金币算）。
    """
    if coins is None:
        return 400.0 if area >= 3 else 200.0
    k = 1.0 if area >= 5 else (0.5 if area >= 3 else 0.25)
    v = round(k * min(max(coins, 0), SHOP_CAP) / SHOP_RATE)
    return min(v, 350) if area <= 2 else v               # 区域 1、2 的商店再有钱也排在遗物格（400）后面


def tile_value(kind: str | None, values: dict | None = None) -> float:
    v = dict(ROUTE_VALUES)
    v.update({k: x for k, x in (values or {}).items() if isinstance(x, (int, float))})      # "auto" 这类不是数的不算（由流程先换成数）
    return float(v.get(kind if kind else "unknown", v["unknown"]))


@dataclass
class AreaMap:
    area: int = 0
    rows: dict[int, dict[int, str | None]] = field(default_factory=dict)       # 列号 → {行: 标签}；第 0 列是出发点
    seen: dict[int, set[int]] = field(default_factory=dict)                    # 列号 → 确实看到格子的行
    edges: dict[int, dict[tuple[int, int], float]] = field(default_factory=dict)   # 列号 c → {(c 列的行, c+1 列的行): 得分}
    last: int = 0                                                               # 最后一列的列号
    complete: bool = False                                                      # 看到了区域的尽头

    def set_tile(self, col: int, ly: int, label: str | None, seen: bool) -> None:
        self.rows.setdefault(col, {})
        if label or ly not in self.rows[col]:
            self.rows[col][ly] = label or self.rows[col].get(ly)
        if seen:
            self.seen.setdefault(col, set()).add(ly)
        self.last = max(self.last, col)

    def add_edges(self, col: int, scores: dict[tuple[int, int], float]) -> None:
        cur = self.edges.setdefault(col, {})
        for k, v in scores.items():
            cur[k] = max(v, cur.get(k, 0.0))

    def extreme_cols(self) -> list[int]:
        return sorted(c for c, r in self.rows.items() if "extreme" in r.values())

    def nexts(self, col: int, ly: int, thr: float) -> list[int]:
        return sorted(lb for (la, lb), s in self.edges.get(col, {}).items() if la == ly and s >= thr)

    def describe(self, thr: float) -> list[str]:
        out = []
        for c in range(1, self.last + 1):
            r = self.rows.get(c, {})
            shown = sorted(ly for ly in r if ly in self.seen.get(c, set()) or r[ly]
                           or any(lb == ly and s >= thr for (_, lb), s in self.edges.get(c - 1, {}).items()))
            tiles = "、".join(f"{row_name(ly)}={KIND_NAMES.get(r[ly], '？')}" for ly in shown) or "（没看清）"
            links = "；".join(f"{row_name(la)}→{'/'.join(row_name(lb) for lb in self.nexts(c, la, thr)) or '×'}"
                              for la in shown) if c < self.last else ""
            out.append(f"第 {c} 列：{tiles}" + (f"　｜去下一列：{links}" if links else ""))
        return out


@dataclass
class Plan:
    path: list[tuple[int, int]]            # [(列号, 行)]，从下一列开始
    extremes: int                          # 这条路上的极难数
    wanted: int                            # 从现在的位置往后，有极难的列数
    blocked: list[int]                     # 走不到极难的列
    ok: bool                               # 能走到区域尽头，而且极难一列不落
    value: float = 0.0                     # 这条路上的格子一共值多少分（按 ROUTE_VALUES）
    ties: int = 1                          # 极难数并列第一的路线有几条（包括选中的这条）；>1 说明是靠分数 / 靠上挑出来的

    def row_for(self, col: int) -> int | None:
        for c, ly in self.path:
            if c == col:
                return ly
        return None


def make_plan(m: AreaMap, col: int, starts: list[int], thr: float, values: dict | None = None, extreme: str = "all",
              ban: tuple[str, ...] = ()) -> Plan:
    """现在站在第 col−1 列，starts 是第 col 列里现在能走的行（地图上发光的那些）。

    先比极难数，再比这条路上的格子一共值多少分（values 可以覆盖 ROUTE_VALUES 里的数），最后取靠上的。
    extreme = 这一档对极难的态度（见 tiers.py）："all" 一列不落，有走不到的就算不行（ok = False，由流程决定重开）；
    "most" 能走到几个算几个，只要能走到尽头就行；"avoid" 反过来，挑极难最少的路。
    ban = 不许踩的格子类型（第一档在区域 2 不走商店：ban=("shop",)）；绕不开就和“走不到尽头”一样，返回 ok = False、path 为空。
    """
    sign = -1 if extreme == "avoid" else 1
    wanted_cols = [c for c in m.extreme_cols() if c >= col]
    # (c, ly) → (极难数, 分数, −行高之和, 路径, 极难数相同的走法有几条)
    best: dict[tuple[int, int], tuple[int, float, int, list[tuple[int, int]], int] | None] = {}

    def go(c: int, ly: int) -> tuple[int, float, int, list[tuple[int, int]], int] | None:
        """从 (c, ly) 走到尽头。走不到尽头返回 None。"""
        key = (c, ly)
        if key in best:
            return best[key]
        kind = m.rows.get(c, {}).get(ly)
        if kind in ban:
            best[key] = None
            return None
        gain = sign if kind == "extreme" else 0
        val = 0.0 if kind == "extreme" else tile_value(kind, values)     # 极难已经单独比过了，不再算进分数
        if c >= m.last:
            best[key] = (gain, val, -ly, [(c, ly)], 1)
            return best[key]
        top, ties = None, 0
        for nb in m.nexts(c, ly, thr):
            sub = go(c + 1, nb)
            if sub is None:
                continue
            cand = (sub[0] + gain, sub[1] + val, sub[2] - ly, [(c, ly)] + sub[3], sub[4])
            if top is None or cand[0] > top[0]:
                ties = cand[4]
            elif cand[0] == top[0]:
                ties += cand[4]
            if top is None or cand[:3] > top[:3]:
                top = cand
        best[key] = None if top is None else top[:4] + (ties,)
        return best[key]

    top, ties = None, 0
    for ly in sorted(starts):
        r = go(col, ly)
        if r is None:
            continue
        if top is None or r[0] > top[0]:
            ties = r[4]
        elif r[0] == top[0]:
            ties += r[4]
        if top is None or r[:3] > top[:3]:
            top = r
    if top is None:
        return Plan([], 0, len(wanted_cols), wanted_cols, False)
    on_path = {c for c, ly in top[3] if m.rows.get(c, {}).get(ly) == "extreme"}
    blocked = [c for c in wanted_cols if c not in on_path]
    return Plan(top[3], len(on_path), len(wanted_cols), blocked, (not blocked) if extreme == "all" else True, value=top[1], ties=ties)
