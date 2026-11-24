"""按“战斗估算”挑队：把名单里能凑出来的队一队队推演，挑估算下来能赢、而且赢得最快的。

用户定的方向（2026-11-19 夜，两次）：按敌我双方的数值、技能、公式算，每场上算出来最好的一队；
“之前定的每场战斗选人规则都推倒，按新的模拟来”。所以极难和区域 3 首领（估算认得敌人和角色的时候）：
  · 规则排出来的几队只当搜索的起点，不再是限制——带不带坦克、带不带奶、物理队还是法队、谁站最前面，都由推演的结果决定；
  · 从最好的两个起点出发，一个位置一个位置地换成名单里别的人再推演，有更好的就换（ROUNDS 轮，整个名单都能换进来）；
  · 每一队都推演两遍——“照常”和“敌人更疼、我方更弱”（PESSIMISTIC）——两遍都能赢的排在前面，再比谁快、谁倒的人少；
  · 只留两条不是“选人规则”的限制：同一个角色的不同版本不能同时上场（游戏不让）；这一局真机上刚输过的队不再上。
  · 真机输过几次，就把敌人的伤害再往上估一档（估算已经被证明偏乐观了）；这一局真机赢过的人略微优先。
估算不了的战斗（普通小怪、敌人没认出来、名单里认得的人不够）还是照 strategy.py 的规则排。

时间：估算里的“秒”是游戏里的秒（战斗画面右上角计时器走的秒）。真机是 4 倍速，放 UB 动画时计时器停着，
所以记录里的现实秒数主要是在数 UB 动画，不能拿来和估算比——2026-11-19 那两版校准都栽在这上面（先当成 1 倍、又当成 2 倍）。
11-24 起每场战斗读计时器（vision/battle.py），记录里的 game 才是真的用时。
估算有多准见 tools/dev/开发环境说明.md：它是拿公开的技能数据粗算的，不是把游戏跑一遍。
"""
from __future__ import annotations

import time
from typing import Any, Callable, Iterable, Sequence

from . import battle as BT

# 2026-11-24：修掉“第一次才有的效果每次都给”那一类错以后，什么系数都不加（都是 1）时胜负对得最好——真机 31 场对上 26 场。
# 用时还没法校（以前记的是现实秒，见上）；等攒够带计时器读数的战斗再说。
HP_MULT = 1.0                                       # 我方血量乘多少
OUT_MULT = 1.0                                      # 我方输出乘多少
HIT_CAP, HIT_SOFT = 1_500_000.0, 0.3              # 难度效果「伤害衰减」的近似：我方一下打出去超过 150 万的部分只算三成（估的）
PESSIMISTIC = {"enemy_out": 1.4, "out": 0.75}      # 保守的那一遍：敌人伤害 ×1.4、我方输出 ×0.75
RETRY_STEP = 0.4                                    # 真机每输一次，敌人的伤害多估这么多
ROUNDS = 2                                          # 从起点出发换人推演几轮（每轮每个位置都把名单里别的人试一遍）
STARTS = 2                                          # 从最好的几个起点出发
BUDGET = 12.0                                       # 一场战斗挑队最多花这么多秒推演，到点就用当时最好的
PROVEN = 2.0                                        # 这一局真机上赢过的人：每赢一场加这么多（最多算 3 场）——估算差不多时沿用赢过的队
# 遗物系列每一点大概值多少（同一系列的五种遗物各占五分之一来平均；工具现在只知道每个系列有几点，不知道具体是哪件）
SERIES = {"power": {"atk_pct": 6.0, "def_pct": 2.0, "buff_pct": 6.0}, "weaken": {"enemy_atk_pct": -2.0, "enemy_def_pct": -2.0},
          "crit": {"cdmg_pct": 8.0, "crit_add": 2.0, "normal_pct": 6.0}, "guard": {"hp_pct": 2.0}, "speed": {"haste": 0.02}}


def mods_for(series: dict[str, int] | None, attempt: int = 0) -> dict[str, float]:
    m: dict[str, float] = {"hp_mult": HP_MULT, "out": OUT_MULT, "enemy_out": 1.0 + RETRY_STEP * max(0, attempt), "hit_cap": HIT_CAP, "hit_soft": HIT_SOFT}
    for name, n in (series or {}).items():
        for k, per in SERIES.get(name, {}).items():
            m[k] = m.get(k, 0.0) + per * float(n or 0)
    g = float((series or {}).get("guard", 0) or 0)
    if g:
        m["regen"] = 100.0 * g * g                 # 再生腕轮：每秒回【守备】数 ×500，有它的概率按五分之一算
    return m


def worse(m: dict[str, float]) -> dict[str, float]:
    p = dict(m)
    p["enemy_out"] = p.get("enemy_out", 1.0) * PESSIMISTIC["enemy_out"]
    p["out"] = p.get("out", 1.0) * PESSIMISTIC["out"]
    return p


def value(nom: BT.Result, pes: BT.Result) -> float:
    """越大越好。两遍都赢 > 只有照常那遍赢 > 都输；赢的比快、比倒的人少；输的比敌人剩得少。"""
    v = 0.0
    if nom.win:
        v += 1000.0 - nom.time - 4.0 * len(nom.deaths)
    else:
        v += -1000.0 * nom.left + 0.5 * nom.time
    if pes.win:
        v += 2000.0 - 0.3 * pes.time - 2.0 * len(pes.deaths)
    else:
        v += -300.0 * pes.left
    return v


def brief(r: BT.Result) -> dict[str, Any]:
    return {"win": r.win, "sec": r.time, "left": r.left, "deaths": [[n, t] for n, t in r.deaths], "enemy_ub": r.enemy_ub[:3]}


def say(r: BT.Result) -> str:
    """一句话说一次推演的结果。秒是游戏里的秒（计时器走的秒，不是现实时间）。"""
    if r.win:
        return f"游戏里 {r.time:.0f} 秒打完" + (f"，中途倒 {len(r.deaths)} 个（最早 {r.deaths[0][0]} 第 {r.deaths[0][1]:.0f} 秒）" if r.deaths else "，没人倒")
    if r.alive == 0:
        return f"游戏里第 {r.time:.0f} 秒全倒，敌人还剩 {r.left * 100:.0f}%" + (f"（最早 {r.deaths[0][0]} 第 {r.deaths[0][1]:.0f} 秒）" if r.deaths else "")
    return f"打不完，90 秒到了敌人还剩 {r.left * 100:.0f}%" + (f"，倒 {len(r.deaths)} 个" if r.deaths else "")


class Advisor:
    def __init__(self, data: BT.Data):
        self.data = data

    def knows(self, name: str | None) -> bool:
        return bool(name) and name in self.data.units

    def stage(self, enemy: str | None, area: int | None) -> str | None:
        return self.data.stage_key(enemy, area) if enemy else None

    def run(self, names: Sequence[str], stage: str, mods: dict[str, float]) -> tuple[float, BT.Result, BT.Result]:
        nom = BT.simulate(self.data, list(names), stage, mods)
        pes = BT.simulate(self.data, list(names), stage, worse(mods))
        return value(nom, pes), nom, pes

    def search(self, units: Sequence[Any], stage: str, mods: dict[str, float], seeds: Iterable[Sequence[Any]], lost: Sequence[Sequence[str]] = (),
               wins: dict[str, int] | None = None) -> dict[str, Any] | None:
        """units = 名单（strategy.Unit）；seeds = 搜索的起点（规则排出来的几队）。返回 {"team": [Unit…], "value", "nom", "pes", "tried", "seeds": [...]}；一队都推演不了返回 None。"""
        can = [u for u in units if self.knows(u.name)]
        lost_sets = [frozenset(t) for t in lost if t]
        seen: dict[frozenset, tuple[float, BT.Result, BT.Result]] = {}

        def ok(team: Sequence[Any]) -> bool:
            names = [u.name for u in team]
            if len(set(names)) != len(names) or frozenset(names) in lost_sets or not all(self.knows(n) for n in names):
                return False
            bases = [getattr(u, "base", None) or u.name for u in team]
            return len(set(bases)) == len(bases)

        def score(team: Sequence[Any]) -> tuple[float, BT.Result, BT.Result]:
            key = frozenset(u.name for u in team)
            if key not in seen:
                v, nom, pes = self.run(sorted(key), stage, mods)
                seen[key] = (v + PROVEN * sum(min(3, int((wins or {}).get(n, 0) or 0)) for n in key), nom, pes)
            return seen[key]

        starts = []
        for s in seeds:
            s = list(s)
            if s and ok(s):
                starts.append((score(s)[0], s))
        if not starts:
            return None
        starts.sort(key=lambda z: -z[0])
        report = [{"names": [u.name for u in s], "value": round(v, 1), "nom": brief(score(s)[1]), "pes": brief(score(s)[2])} for v, s in starts]
        pool_list = list(can)                       # 整个名单都能换进来：谁上谁下由推演说了算，不按职能、强度档、是不是竞技场角色筛
        best_v, best = starts[0]
        t_end = time.time() + BUDGET
        for start_v, start in starts[:STARTS]:
            cur_v, cur = start_v, list(start)
            for _ in range(ROUNDS):
                improved = False
                for i in range(len(cur)):
                    for u in pool_list:
                        if any(u is x for x in cur):
                            continue
                        cand = cur[:i] + [u] + cur[i + 1:]
                        if not ok(cand):
                            continue
                        v = score(cand)[0]
                        if v > cur_v + 1.0:
                            cur_v, cur, improved = v, cand, True
                    if time.time() > t_end:
                        break
                if not improved or time.time() > t_end:
                    break
            if cur_v > best_v:
                best_v, best = cur_v, cur
        v, nom, pes = score(best)
        return {"team": best, "value": v, "nom": nom, "pes": pes, "tried": len(seen), "seeds": report}


def load(data_dir: Any) -> Advisor | None:
    """读 data/battle.json；没有这个文件、或者读不了，就没有估算（照旧按规则排队）。"""
    try:
        from pathlib import Path
        p = Path(data_dir) / "battle.json"
        return Advisor(BT.Data(p)) if p.exists() else None
    except Exception:  # noqa: BLE001
        return None
