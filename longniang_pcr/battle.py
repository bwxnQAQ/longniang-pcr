"""战斗估算：按公主连结的战斗公式和主数据库里的技能动作，推演一队人打一关会怎样——谁在第几秒倒、多久打完。

这不是逐帧还原游戏：出手的时间只用了数据库里有的“前摇”（skill_cast_time / normal_atk_cast_time），动作本身占的时间是估的（ANIM）；
暴击按期望值算；认不得的技能动作类型会跳过（skipped 里记着）。所以结果是“大概会怎样”，要拿真机记录校。

公式（社区公开的）：
  伤害 = (v1 + v2×技能等级 + (v3 + v4×技能等级)×攻击力) ÷ (1 + 防御 ÷ 100)，暴击 ×2，暴击率 = 暴击值 × 0.05% × 攻方等级 ÷ 守方等级；
  普通攻击 = 攻击力 ÷ (1 + 防御 ÷ 100)；
  TP：每次行动 +90 ×(1 + TP上升%)；挨打 + 500 × 伤害 ÷ 最大生命 ×(1 + TP上升%)；满 1000 放 UB，放完剩 1000 × TP消耗减轻%；
  回复 = (v2 + v3×等级 + (v4 + v5×等级)×攻击力) × (1 + 回复量上升%)；吸血 = 伤害 × 吸血值 ÷ (吸血值 + 守方等级 + 100)。
和现成的开源模拟器 PCRCalculator（GitHub acygen/PCRCalculator，公开的是 2020 年 8 月的脚本）对过：防御、暴击率、每次行动 +90、
挨打 500 × 伤害 ÷ 最大生命、行动的节奏（等前摇 → 出手 → 再等下一个动作的前摇，加速时前摇除以倍率）都一样；开场固定等 2.5 秒是照它改的。

这里的“秒”是游戏里的秒（战斗画面右上角计时器走的秒），一场最多 90 秒。
真机是 4 倍速，而且放 UB 动画时计时器是停的，所以现实时间和它对不上：一场 90 秒的战斗现实里可以是 25 秒，也可以是 90 多秒（全看放了多少次 UB）。
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ANIM_ATTACK = 0.6          # 普通攻击出手以后到下一个动作开始前摇之间占的时间（估的）
ANIM_SKILL = 1.0           # 技能的
ANIM_UB = 0.3              # UB 的（跳过动画时很短）
ANIM_ENEMY = 1.0           # 敌人的：两次出手之间除了前摇还隔多久（估的；拿真机 31 场的胜负对过，见 advisor.py 开头）
FIRST_WAIT = 2.5           # 开场到第一个动作之间的固定等待（现成的模拟器项目 PCRCalculator 里是 2.5 秒）
FIRST_PLUS_CAST = True     # 第一个动作是不是还要再等它自己的前摇（和真机对下来，算上更接近）
TP_ACTION = 90.0
TP_HIT = 500.0
MOB_TP_RATE = 0.2          # 小怪说明里写的“造成伤害带来的 TP 回复量下降 80%”
ALL_RANGE = 2160
AURA = {1: "atk", 2: "pdef", 3: "matk", 4: "mdef", 5: "dodge", 6: "crit", 7: "mcrit", 8: "tpup", 9: "ls", 11: "cdmg", 12: "mcdmg", 13: "acc",
        14: "taken_crit", 15: "taken", 16: "taken_p", 17: "taken_m", 18: "dealt_p", 19: "dealt_m"}
CC_IMMUNE_BOSS = True
ENEMY_REACH = 50.0         # 敌人打“某个人和她周围”的技能：范围外再多够得到这么远（真机上 335 打得到、362 打不到，见 _targets）


@dataclass
class Actor:
    side: int
    name: str
    lv: int
    st: dict[str, float]
    atk_type: str
    range: float
    cast: float
    pats: list[dict[str, Any]]
    sk: dict[str, Any]
    slv: dict[str, int] | None = None                 # 敌人：每个技能的等级；我方 None = 都等于自己的等级
    boss: bool = False
    x: float = 0.0
    hp: float = 0.0
    max_hp: float = 0.0
    tp: float = 0.0
    idx: int = 0
    next_time: float = 0.0
    next_code: Any = None
    dead_at: float | None = None
    stun_until: float = 0.0
    invuln_until: float = 0.0
    taunt_until: float = 0.0
    buffs: list[list[Any]] = field(default_factory=list)      # [属性, 数值, 是不是百分比, 到期时间]
    barriers: list[list[Any]] = field(default_factory=list)   # [phys/magic/both, 剩余量, 到期时间]
    dots: list[list[Any]] = field(default_factory=list)       # [每秒伤害, 到期时间, 是不是回复]
    speeds: list[list[float]] = field(default_factory=list)   # [倍率, 到期时间]
    cuts: list[list[Any]] = field(default_factory=list)       # [phys/magic/all, 减伤%, 到期时间]
    dealt: float = 0.0
    taken: float = 0.0
    healed: float = 0.0
    ub_count: int = 0
    haste: float = 0.0                                # 可以叠加的加速（遗物给的），直接加在倍率上
    hastes: list[list[float]] = field(default_factory=list)   # 技能给的“额外”加速（动作 83）：[加多少, 到期时间, 是哪个动作给的]
    counters: dict[int, int] = field(default_factory=dict)    # 技能计数（动作 45 加一；“第一次放才有的效果”靠它判断）
    marks: dict[int, list[float]] = field(default_factory=dict)   # 特殊标记（动作 35）：标记编号 → [层数, 到期时间]
    base_max: float = 0.0                             # 原本的最大生命（没被降的时候）
    hp_downs: list[list[float]] = field(default_factory=list)  # 被降了多少最大生命：[降多少, 到期时间]
    uid: int = 0                                      # 角色编号（“队里有某某时”这种条件要用）

    @property
    def alive(self) -> bool:
        return self.dead_at is None

    def stat(self, key: str, t: float) -> float:
        base = float(self.st.get(key, 0.0))
        add = pct = 0.0
        for k, v, is_pct, until in self.buffs:
            if k == key and until > t:
                if is_pct:
                    pct += v
                else:
                    add += v
        val = base * (1 + pct / 100.0) + add
        # 攻击力被降到 0 以下按 0 算（游戏里不会是负的）。以前没有这一条：带降魔攻的角色打幽灵领主时，推演里它的魔攻成了 -23080，
        # “按魔攻加成的比例伤害”跟着变成负数，等于它的 UB 完全不疼
        return max(0.0, val) if key in ("atk", "matk") else val

    def mod(self, key: str, t: float) -> float:
        """taken / dealt 这类“百分比修正”的合计（%）。"""
        return sum(v for k, v, _p, until in self.buffs if k == key and until > t)

    def speed(self, t: float) -> float:
        up, down = 1.0, 1.0                              # 同类的加速 / 减速不叠加：取最大的加速、最狠的减速
        for m, until in self.speeds:
            if until > t:
                if m >= 1:
                    up = max(up, m)
                else:
                    down = min(down, m)
        return max(0.1, up * down + self.haste + sum(h[0] for h in self.hastes if h[1] > t))

    def level_of(self, code: str) -> int:
        if self.slv is None:
            return self.lv
        return int(self.slv.get(code) or self.slv.get("ub") or self.lv)


@dataclass
class Result:
    win: bool
    time: float                       # 打完用的秒数（没打完 = 时限）
    deaths: list[tuple[str, float]]   # 我方谁在第几秒倒下
    left: float                       # 敌人还剩多少血（占总血量的比例）
    alive: int                        # 我方最后还站着几个
    dealt: dict[str, float]           # 我方每个人打出的伤害
    taken: dict[str, float]           # 我方每个人挨的伤害（扣完防御）
    enemy_ub: list[float]             # 敌人每次放 UB 的时间
    skipped: dict[int, int]           # 没推演的动作类型 → 次数
    note: str = ""

    @property
    def lost(self) -> bool:
        return not self.win


class Data:
    def __init__(self, src: Path | str | dict[str, Any]):
        d = src if isinstance(src, dict) else json.loads(Path(src).read_text(encoding="utf-8"))
        self.units: dict[str, Any] = d["units"]
        self.eunits: dict[str, Any] = d["eunits"]
        self.stages: dict[str, Any] = d["stages"]
        self.level: int = d.get("level", 0)

    def stage_key(self, enemy: str, area: int | None = None) -> str | None:
        """对策表里的名字 + 现在在第几个区域 → 关卡。首领只有一份；极难按区域 1～5。"""
        for k in ((f"{enemy}|a{area}" if area else None), f"{enemy}|d5", f"{enemy}|a3", f"{enemy}|a1", f"{enemy}|hard"):
            if k and k in self.stages:
                return k
        return None


def _code_kind(code: Any) -> str:
    return "ub" if code in ("ub", "sp_ub") else "attack" if code == 1 else "skill"


UNLISTED_RATIOS = {"hp": 0.625, "atk": 0.616, "matk": 0.616, "pdef": 0.745, "mdef": 0.739, "crit": 0.648, "mcrit": 0.648}
UNLISTED_MEASURED = {
    "大和": {"hp": 92370, "atk": 26951, "matk": 20, "pdef": 2086, "mdef": 1859, "crit": 626, "mcrit": 0,
           "dodge": 21, "whp": 890, "wtp": 233},
    "克莉丝提娜（狂野）": {"hp": 37919, "atk": 45789, "matk": 0, "pdef": 703, "mdef": 597, "crit": 1960, "mcrit": 0,
                    "dodge": 20, "whp": 2045, "wtp": 255, "ls": 9, "hprec": 20, "tpup": 40, "tpred": 15, "acc": 62},
}


class Battle:
    def __init__(self, data: Data, team: list[str], stage: str, mods: dict[str, float] | None = None, limit: float = 90.0, seed: int = 7):
        self.data, self.limit = data, limit
        self.mods = dict(mods or {})
        self.rng = random.Random(seed)
        self.env: dict[int, float] = {}               # 环境效果（动作 105）：编号 → 到期时间
        self.unit_out: dict[str, float] = dict(self.mods.pop("unit_out", None) or {})     # 按真机伤害校出来的：某个角色打出的伤害乘多少
        self.t = 0.0
        self.skipped: dict[int, int] = {}
        self.enemy_ub: list[float] = []
        self.ours: list[Actor] = []
        self.foes: list[Actor] = []
        hp_pct, atk_pct, def_pct = self.mods.get("hp_pct", 0.0), self.mods.get("atk_pct", 0.0), self.mods.get("def_pct", 0.0)
        for n in team:
            u = data.units[n]
            st = dict(u["st"])
            if n in self.mods.get("unlisted", ()):
                st.update({key: round(st[key] * ratio) for key, ratio in UNLISTED_RATIOS.items() if key in st})
                st.update(UNLISTED_MEASURED.get(n, {}))
                st.update(lv=320, rank=34, star=3)
            st["hp"] = st.get("hp", 1) * (1 + hp_pct / 100.0) * self.mods.get("hp_mult", 1.0)
            for k in ("atk", "matk"):
                st[k] = st.get(k, 0) * (1 + atk_pct / 100.0)
            for k in ("pdef", "mdef"):
                st[k] = st.get(k, 0) * (1 + def_pct / 100.0)
            a = Actor(0, n, int(st.get("lv", data.level)), st, u["atk"], float(u["range"]), float(u["cast"]), u["pat"], u["sk"], uid=int(u.get("id") or 0))
            a.x = -a.range
            a.haste = self.mods.get("haste", 0.0)
            self.ours.append(a)
        sg = data.stages[stage]
        e_atk, e_def = self.mods.get("enemy_atk_pct", 0.0), self.mods.get("enemy_def_pct", 0.0)
        # 敌人的血量乘多少（平时是 1）。判断“秒不秒得掉”时用：真机上的用时是推演的几倍，就把敌人的血乘几倍再推演一遍——
        # 打得久了，敌人的 TP 照常涨，该放的大招就会放出来。（试过把我方输出除以倍数：有“单下伤害封顶”在，用时并不跟着成倍变长）
        e_hp = max(0.01, float(self.mods.get("enemy_hp", 1.0) or 1.0))
        rmin = None
        for e in sg["enemies"]:
            eu = data.eunits[str(e["unit"])]
            st = {"hp": e["hp"] * e_hp, "atk": e["atk"] * (1 + e_atk / 100.0), "matk": e["matk"] * (1 + e_atk / 100.0), "pdef": max(0.0, e["pdef"] * (1 + e_def / 100.0)),
                  "mdef": max(0.0, e["mdef"] * (1 + e_def / 100.0)), "dodge": e.get("dodge", 0), "acc": e.get("acc", 0), "tpup": e.get("tpup", 0)}
            a = Actor(1, e["jp"], int(e["lv"]), st, eu["atk"], float(eu["range"] or 0), float(eu["cast"] or 2.0), eu["pat"], eu["sk"], slv=e["slv"], boss=bool(e.get("boss")))
            if not a.boss:
                rmin = a.range if rmin is None else min(rmin, a.range)
            self.foes.append(a)
        for a in self.foes:
            a.x = 0.0 if a.boss else max(0.0, a.range - (rmin or 0.0))
        for a in self.ours + self.foes:
            a.max_hp = a.hp = a.base_max = float(a.st["hp"])
            a.next_code = self._peek(a)
            a.next_time = FIRST_WAIT + (self._cast(a, a.next_code) if FIRST_PLUS_CAST else 0.0)
        for a in self.ours:
            a.tp = min(1000.0, self.mods.get("start_tp", 0.0))
        self.total_foe_hp = sum(a.max_hp for a in self.foes)
        self.deaths: list[tuple[str, float]] = []
        self.next_tick = 1.0
        self.trace: list[tuple[float, str, str, float]] | None = None      # 调试用：打开以后记每一下伤害（时间、谁、打谁、多少）

    # ---------- 出手顺序 ----------
    def _peek(self, a: Actor) -> Any:
        if a.tp >= 1000.0 and "ub" in a.sk:
            return "ub"
        if not a.pats:
            return 1
        p = a.pats[0]
        seq = p["seq"]
        if not seq:
            return 1
        i = a.idx
        if i >= len(seq) or i >= p["end"]:
            start = max(1, int(p["start"])) - 1
            span = max(1, min(len(seq), int(p["end"])) - start)
            i = start + (a.idx - start) % span
        code = seq[i]
        return code if code == 1 or str(code) in a.sk else 1

    def _cast(self, a: Actor, code: Any) -> float:
        base = a.cast if code == 1 else float(a.sk[str(code)].get("cast") or 0.0)
        return base / a.speed(self.t)

    def _others(self, a: Actor) -> list[Actor]:
        return [x for x in (self.foes if a.side == 0 else self.ours) if x.alive]

    def _mates(self, a: Actor) -> list[Actor]:
        return [x for x in (self.ours if a.side == 0 else self.foes) if x.alive]

    # ---------- 选目标 ----------
    def _targets(self, a: Actor, act: dict[str, Any], done: dict[int, list[Actor]]) -> list[Actor]:
        tt, ta = act.get("tt", 3), act.get("ta", 1)
        if tt == 7:
            return [a]
        pool = self._mates(a) if ta == 2 else self._others(a)
        if not pool:
            return []
        dep = done.get(act.get("dep") or -1)
        origin = a
        tc, tn, rg = int(act.get("tc") or 1), int(act.get("tn") or 0), float(act.get("rg") or -1)
        if dep:
            dep = [x for x in dep if x.alive]
            if dep and dep[0].side == pool[0].side:
                if tc <= 1:
                    return dep[:1]
                origin = dep[0]
        if 0 < rg < ALL_RANGE:
            if a.side == 0 and ta != 2:
                if origin is a:                            # 从自己往前够得到多远：最前面的敌人总是够得到的
                    inside = [x for x in pool if x.boss or (x.x - a.x) <= max(rg, a.range) + 50]
                else:                                      # 以某个目标为中心的一片
                    inside = [x for x in pool if x.boss or abs(x.x - origin.x) <= rg + 50]
            elif a.side == 1 and ta != 2:
                front = min(pool, key=lambda z: -z.x) if origin is a else origin
                # 2026-11-27 拿真机记录核的（幽灵领主的 UB，范围 300）：离最前面的人 335 的被打到了，362、380 的没有——和我方一样按“范围 + 50”算
                inside = [x for x in pool if abs(x.x - front.x) <= rg + ENEMY_REACH]
            else:
                inside = [x for x in pool if abs(x.x - origin.x) <= rg + 50]
            pool = inside or ([min(pool, key=lambda z: abs(z.x - origin.x))] if ta != 2 else [])
        key = lambda z: abs(z.x - a.x)                                 # noqa: E731
        taunters = [x for x in pool if x.taunt_until > self.t]
        if tt in (5, 25, 36):
            pool = sorted(pool, key=lambda z: z.hp / z.max_hp)
        elif tt in (6, 26, 35):
            pool = sorted(pool, key=lambda z: -z.hp / z.max_hp)
        elif tt == 4:
            pool = sorted(pool, key=key, reverse=True)
        elif tt in (2, 8):
            pool = sorted(pool, key=key)
            self.rng.shuffle(pool)
        elif tt in (12, 27, 37):
            pool = sorted(pool, key=lambda z: -z.tp)
        elif tt in (13, 28):
            pool = sorted(pool, key=lambda z: z.tp)
        elif tt in (14, 29, 38, 43):
            pool = sorted(pool, key=lambda z: -max(z.st.get("atk", 0), z.st.get("matk", 0)) if tt in (38, 43) else -z.st.get("atk", 0))
        elif tt in (16, 31):
            pool = sorted(pool, key=lambda z: -z.st.get("matk", 0))
        elif tt == 20:
            pool = sorted([x for x in pool if x.atk_type == "phys"] or pool, key=key)
        elif tt == 21:
            pool = sorted([x for x in pool if x.atk_type == "magic"] or pool, key=key)
        elif tt == 34:
            pool = sorted([x for x in pool if x is not a], key=key)
        else:
            pool = sorted(pool, key=key)
            if taunters and ta != 2:
                pool = taunters + [x for x in pool if x not in taunters]
        return pool[tn:tn + max(1, tc)] if tn < len(pool) else pool[-1:]

    # ---------- 伤害 / 回复 ----------
    def _hurt(self, src: Actor | None, tgt: Actor, amount: float, kind: str, tp_rate: float = 1.0, pierce: bool = False) -> float:
        """amount = 已经除过防御的伤害。屏障、减伤、无敌在这里结算。返回实际掉的血。"""
        if not tgt.alive or amount <= 0:
            return 0.0
        t = self.t
        if tgt.invuln_until > t:
            return 0.0
        if src is not None and src.side == 0 and self.unit_out:
            amount *= self.unit_out.get(src.name, 1.0)
        if not pierce:
            cut = sum(v for k, v, until in tgt.cuts if until > t and k in (kind, "all"))
            amount *= max(0.0, 1 - cut / 100.0)
            amount *= max(0.0, 1 + (tgt.mod("taken", t) + tgt.mod("taken_p" if kind == "phys" else "taken_m", t)) / 100.0)
            if tgt.side == 0:
                amount *= max(0.0, 1 - self.mods.get("dmg_cut", 0.0) / 100.0)
            for b in tgt.barriers:
                if amount <= 0:
                    break
                if b[2] > t and b[1] > 0 and b[0] in (kind, "both"):
                    used = min(b[1], amount)
                    b[1] -= used
                    amount -= used
        if amount <= 0:
            return 0.0
        amount = min(amount, tgt.hp)
        tgt.hp -= amount
        tgt.taken += amount
        if self.trace is not None:
            self.trace.append((round(t, 2), src.name if src is not None else "-", tgt.name, round(amount)))
        if src is not None:
            src.dealt += amount
        tgt.tp = min(1000.0, tgt.tp + TP_HIT * amount / tgt.max_hp * (1 + tgt.stat("tpup", t) / 100.0) * tp_rate)
        if tgt.hp <= 0.5:
            tgt.hp = 0.0
            tgt.dead_at = t
            if tgt.side == 0:
                self.deaths.append((tgt.name, round(t, 1)))
            if src is not None and src.alive:
                src.tp = min(1000.0, src.tp + 200.0 * (1 + src.stat("tpup", t) / 100.0))
        return amount

    def _heal(self, src: Actor, tgt: Actor, amount: float) -> None:
        if not tgt.alive or amount <= 0:
            return
        amount *= max(0.0, 1 + self.mods.get("heal_pct", 0.0) / 100.0) if tgt.side == 0 else 1.0
        got = min(amount, tgt.max_hp - tgt.hp)
        tgt.hp += got
        tgt.healed += got
        src.healed += 0.0

    def _damage(self, a: Actor, tgt: Actor, act: dict[str, Any], lv: int, scale: dict[int, float], tp_rate: float) -> None:
        v, d = act["v"], act["d"]
        t = self.t
        magic = d[0] == 2
        power = a.stat("matk" if magic else "atk", t)
        v3 = (v[2] + v[3] * lv) * scale.get(3, 1.0)
        base = (v[0] + v[1] * lv) * scale.get(1, 1.0) + v3 * power
        self._strike(a, tgt, base, "magic" if magic else "phys", crit_rate=float(v[5] or 0), sure=(d[0] == 3), tp_rate=tp_rate)

    def _strike(self, a: Actor, tgt: Actor, base: float, kind: str, crit_rate: float = 0.0, sure: bool = False, tp_rate: float = 1.0) -> None:
        t = self.t
        if base <= 0:
            return
        crit = a.stat("mcrit" if kind == "magic" else "crit", t)
        chance = min(1.0, max(0.0, crit * 0.05 * (a.lv / max(1, tgt.lv)) / 100.0))
        if a.side == 0:
            chance = min(1.0, max(0.0, chance + self.mods.get("crit_add", 0.0) / 100.0))
        cmult = 2.0 * (crit_rate if crit_rate > 0 else 1.0) + (self.mods.get("cdmg_pct", 0.0) / 100.0 if a.side == 0 else 0.0) + a.stat("mcdmg" if kind == "magic" else "cdmg", t) / 100.0
        base *= 1 + chance * (cmult - 1)
        if kind == "phys" and not sure:
            gap = tgt.stat("dodge", t) - a.stat("acc", t)
            if gap > 0:
                base *= 1 - 1 / (1 + 100.0 / gap)
        key = "mdef" if kind == "magic" else "pdef"
        dfn = max(0.0, tgt.stat(key, t))
        if tgt.side == 1:                                 # 难度效果「防御力（降不掉的）上升」：敌人的防御降不到底——这里按最多降掉 def_floor 这么大比例算（估的）
            dfn = max(dfn, float(tgt.st.get(key, 0.0)) * self.mods.get("def_floor", 0.0))
        dmg = base / (1 + dfn / 100.0)
        dmg *= max(0.0, 1 + a.mod("dealt_m" if kind == "magic" else "dealt_p", t) / 100.0)
        if a.side == 0:
            dmg *= self.mods.get("out", 1.0)
            cap = self.mods.get("hit_cap", 0.0)           # 难度效果「伤害衰减」：一下打得越多衰减越狠——这里按超过 hit_cap 的部分只算 hit_soft 这么大比例（估的）
            if cap > 0 and dmg > cap:
                dmg = cap + (dmg - cap) * self.mods.get("hit_soft", 0.3)
        else:
            dmg *= self.mods.get("enemy_out", 1.0)
        got = self._hurt(a, tgt, dmg, kind, tp_rate=tp_rate)
        ls = a.stat("ls", t)
        if got > 0 and ls > 0:
            self._heal(a, a, got * ls / (ls + tgt.lv + 100.0))

    # ---------- 分支条件 ----------
    def _mark(self, x: Actor | None, sid: int) -> int:
        m = x.marks.get(sid) if x is not None else None
        return int(m[0]) if m and m[1] > self.t else 0

    def _cond(self, a: Actor, act: dict[str, Any], tg: list[Actor]) -> bool | None:
        """动作 23 / 28 的条件（d1）成立不成立；成立走 d2 那支，不成立走 d3 那支。None = 这种条件不认识。
        含义对照的是公开的技能说明项目 wthee/pcr-tool（IfStatus.kt / IfSpStatus.kt）。"""
        c, v, t = int(act["d"][0]), act["v"], self.t
        x = tg[0] if tg else None
        if c == 0:
            return bool(tg)
        if 0 < c < 100:                                   # 百分之几的概率
            return self.rng.random() * 100 < c
        if c == 100:                                      # 无法行动
            return bool(x and x.stun_until > t)
        if c == 101:                                      # 加速状态
            return bool(x and x.speed(t) > 1.0 + x.haste + 1e-6)
        if c in (200, 300, 1600, 1601):                   # 失明、魅惑、恐慌、隐匿：这里不算这些状态
            return False
        if c == 400:
            return bool(x and x.taunt_until > t)
        if c in (500, 501, 502, 503, 504, 511, 512, 599): # 烧伤 / 诅咒 / 中毒 / 咒术……：这里不分种类，身上有持续伤害就算
            return bool(x and any(u > t and not heal for _d, u, heal, _s in x.dots))
        if 600 <= c < 700 or 6000 <= c < 7000:            # 标记层数 ≥ max(v3, 1)
            return self._mark(x or a, c - (600 if c < 700 else 6000)) >= max(int(v[2]), 1)
        if c == 721:                                      # 特殊标记状态（v3 = 标记编号）
            return self._mark(x or a, int(v[2])) >= 1
        if c == 700 or 701 <= c <= 709:                   # 落单 / 正好剩几个
            side = self.ours if (x or a).side == 0 else self.foes
            return sum(1 for z in side if z.alive) == (1 if c == 700 else c - 700)
        if c == 720:                                      # 队里有某个角色（v3 = 角色编号）
            want = int(v[2]) // 100
            side = self.ours if (x or a).side == 0 else self.foes
            return any(z.alive and z.uid // 100 == want for z in side)
        if c == 900:                                      # 血是满的
            return bool(x and x.hp >= x.max_hp * 0.999)
        if 901 <= c <= 999:                               # 血量低于百分之几
            return bool(x and x.hp / x.max_hp * 100.0 < c - 900)
        if c == 1000:                                     # 上一个动作把目标打倒了
            return bool(x is not None and not x.alive)
        if c == 1001:                                     # 这一下暴击了
            y = x or (self._others(a) or [a])[0]
            crit = a.stat("mcrit" if a.atk_type == "magic" else "crit", t)
            return self.rng.random() < min(1.0, max(0.0, crit * 0.05 * (a.lv / max(1, y.lv)) / 100.0))
        if 1200 <= c < 1300:                              # 技能计数 ≥ 个位数（十位数是第几个计数）
            return (x or a).counters.get((c % 100) // 10, 0) >= c % 10
        if c in (1300, 2000):                             # 目标是物理攻击的角色
            return bool(x and x.atk_type == "phys")
        if c == 2001:
            return bool(x and x.atk_type == "magic")
        if c == 1700:                                     # 目标身上有某种增益 / 减益（v3 = 增益减益的编号）
            code = int(v[2])
            kind, down = AURA.get(code // 10), code % 10 == 1
            return bool(x and kind and any(k == kind and u > t and ((val < 0) == down) for k, val, _p, u in x.buffs))
        if c == 1800:                                     # 多目标的敌人：部位这里没算
            return False
        if c == 1900:                                     # 身上有护盾
            return bool(x and any(b[2] > t and b[1] > 0 for b in x.barriers))
        if 3000 <= c < 4000:                              # 场上有某个环境效果
            return self.env.get(c - 3000, 0.0) > t
        return None

    # ---------- 一个动作 ----------
    def _aura(self, a: Actor, tgt: Actor, code: int, is_pct: bool, value: float, dur: float) -> None:
        down = code % 10 == 1
        kind = AURA.get((code % 1000) // 10 if code >= 10 else 0)
        if code == 1:
            kind = "hp"
        if kind is None or dur <= 0:
            return
        if kind == "hp":
            return
        if tgt.boss and tgt.side == 1 and down and kind in ("pdef", "mdef") and self.mods.get("def_floor"):
            pass
        tgt.buffs.append([kind, -value if down else value, is_pct, self.t + dur])

    def _cut_max(self, x: Actor, amount: float, dur: float) -> None:
        """把 x 的最大生命降 amount，持续 dur 秒；现在的血超过新的最大生命就压下来。降到见底（剩不到 1）算倒下——
        真机上幽灵领主的 UB 范围里站了两个以上时，这些人就是这一下一起倒的。"""
        if not x.alive or amount <= 0 or dur <= 0:
            return
        x.hp_downs.append([amount, self.t + dur])
        self._remax(x)
        if x.max_hp <= 1.0:
            x.hp, x.dead_at = 0.0, self.t
            if x.side == 0:
                self.deaths.append((x.name, round(self.t, 1)))
            if self.trace is not None:
                self.trace.append((round(self.t, 2), "-", x.name, -1.0))

    def _remax(self, x: Actor) -> None:
        cut = sum(v for v, until in x.hp_downs if until > self.t)
        x.max_hp = max(1.0, x.base_max - cut)
        x.hp = min(x.hp, x.max_hp)

    def _apply(self, a: Actor, sk: dict[str, Any], code: str) -> None:
        lv = a.level_of(code)
        t = self.t
        acts = sk.get("acts") or []
        children = set()
        for act in acts:
            if act["t"] in (23, 28):
                children.update(int(x) for x in act["d"][1:3] if x)
        done: dict[int, list[Actor]] = {}
        scale: dict[int, dict[int, float]] = {}
        add: dict[int, dict[int, float]] = {}          # 26：给某个动作的第几个数值加多少
        mul: dict[int, dict[int, float]] = {}          # 27：乘多少
        # 数值修正的动作在技能里常常排在被修正的动作后面：先把它们算掉
        acts = sorted(acts, key=lambda z: 0 if z["t"] in (26, 27, 74) and z["tt"] == 7 else 1)
        tp_rate = 1.0
        if a.side == 1:
            tp_rate = 0.0 if a.boss else MOB_TP_RATE
        queue = [act for act in acts if act["id"] not in children]
        raw_dealt = 0.0                              # 这个技能里“按比例掉血”的动作一共打了多少（敌人的；动作 26 的第 6 种量要用）
        by_id = {act["id"]: act for act in acts}
        guard = 0
        while queue and guard < 40:
            guard += 1
            act = queue.pop(0)
            ty, d, v = act["t"], act["d"], list(act["v"])
            for i, x in (add.get(act["id"]) or {}).items():
                if 1 <= i <= 7:
                    v[i - 1] += x
            for i, x in (mul.get(act["id"]) or {}).items():
                if 1 <= i <= 7:
                    v[i - 1] *= x
            tg = self._targets(a, act, done)
            done[act["id"]] = tg
            if ty == 1:
                for x in tg:
                    self._damage(a, x, {**act, "v": v}, lv, scale.get(act["id"], {}), tp_rate)
            elif ty == 4:
                power = a.stat("matk" if d[0] == 2 else "atk", t)
                for x in tg:
                    if v[0] == 2:
                        amt = x.max_hp * (v[1] + v[2] * lv) / 100.0
                    else:
                        amt = (v[1] + v[2] * lv + (v[3] + v[4] * lv) * power) * (1 + a.stat("hprec", t) / 100.0)
                    self._heal(a, x, amt)
            elif ty == 6:
                kind = {1: "phys", 2: "magic", 3: "phys", 4: "magic", 5: "both", 6: "both"}.get(d[0])
                if kind:
                    for x in tg:
                        x.barriers.append([kind, v[0] + v[1] * lv, t + v[2] + v[3] * lv])
            elif ty == 8:
                dur = v[2] + v[3] * lv
                for x in tg:
                    if d[0] in (1, 2):
                        m = v[0] + v[1] * lv
                        if m > 0:
                            x.speeds.append([m if d[0] == 2 or m < 1 else 1.0 / m, t + dur])
                    elif not (x.boss and CC_IMMUNE_BOSS) and x.invuln_until <= t:
                        x.stun_until = max(x.stun_until, t + dur)
            elif ty == 9:
                dps, dur = v[0] + v[1] * lv, v[2] + v[3] * lv
                if a.side == 0:
                    dps *= self.mods.get("dot_mult", 1.0)
                for x in tg:
                    x.dots.append([dps, t + dur, False, a])
            elif ty == 10:
                value, dur = (v[1] + v[2] * lv) * scale.get(act["id"], {}).get(2, 1.0), v[3] + v[4] * lv
                if a.side == 0 and tg and tg[0].side == 0:
                    value *= 1 + self.mods.get("buff_pct", 0.0) / 100.0
                for x in tg:
                    if int(d[0]) == 1 and a.side == 1 and x.side == 0:     # 敌人降我方的最大生命（幽灵领主的 UB）
                        self._cut_max(x, x.base_max * value / 100.0 if v[0] == 2 else value, dur)
                        continue
                    self._aura(a, x, int(d[0]), v[0] == 2, value, dur)
            elif ty == 16:
                amt = v[0] + v[1] * lv
                for x in tg:
                    if d[0] in (1, 4):
                        x.tp = min(1000.0, x.tp + amt * ((1 + x.stat("tpup", t) / 100.0) if d[0] == 1 else 1.0))
                    elif not (x.side == 1 and self.mods.get("enemy_tp_guard")):
                        x.tp = max(0.0, x.tp - amt)
            elif ty == 20:
                for x in tg:
                    x.taunt_until = t + (v[0] + v[1] * lv)
            elif ty == 21:
                for x in tg:
                    x.invuln_until = max(x.invuln_until, t + (v[0] + v[1] * lv))
            elif ty == 46:
                pct = v[0] + v[1] * lv
                for x in tg:
                    base = x.max_hp if d[0] == 1 else x.hp
                    if a.side == 1 and x.alive:
                        raw_dealt += max(0.0, base * pct / 100.0)
                    self._hurt(a, x, base * pct / 100.0 * (self.mods.get("enemy_out", 1.0) if a.side == 1 else 1.0), "magic" if d[1] == 2 else "phys", tp_rate=tp_rate)
            elif ty == 48:
                power = a.stat("matk" if d[0] == 2 else "atk", t)
                per, dur = v[0] + v[1] * lv + (v[2] + v[3] * lv) * power, v[4] + v[5] * lv
                for x in tg:
                    if d[1] == 2:
                        x.dots.append([per, t + dur, "tp", a])
                    else:
                        x.dots.append([per * (1 + a.stat("hprec", t) / 100.0), t + dur, True, a])
            elif ty == 83:
                if d[0] == 2:
                    for x in tg:
                        x.hastes = [h for h in x.hastes if len(h) < 3 or h[2] != act["id"]]      # 同一个动作再放一次：续上时间，不再叠一层
                        x.hastes.append([v[0] + v[1] * lv, t + v[2] + v[3] * lv, act["id"]])
            elif ty == 72:
                kind = {1: "phys", 2: "magic", 3: "all"}.get(d[0], "all")
                for x in tg:
                    x.cuts.append([kind, v[0] + v[1] * lv, t + v[2] + v[3] * lv])
            elif ty == 74:
                # 熔岩龙：打到的人越少越疼。v1 − v2 ×（人数 − 1），最少 1 倍，乘在目标动作的第 d2 个数值上
                n = len(tg)
                scale.setdefault(int(d[0]), {})[int(d[1])] = max(1.0, v[0] - v[1] * (n - 1))
            elif ty in (23, 28):
                ok = self._cond(a, act, tg)
                if ok is None:                         # 不认识的条件：按“不成立”走，记一笔
                    self.skipped[ty] = self.skipped.get(ty, 0) + 1
                    ok = False
                pick = d[1] if ok else d[2]
                if pick and int(pick) in by_id:
                    queue.insert(0, by_id[int(pick)])
            elif ty == 45:                             # 技能计数 +1（上限 v1）。“第一次放才有的大效果”都是：计数 < 1 时走大的那支，放完这里加一
                cid, lim = int(d[0]), int(v[0]) or 99
                for x in (tg or [a]):
                    x.counters[cid] = min(lim, x.counters.get(cid, 0) + 1)
            elif ty == 35:                             # 特殊标记：v2 = 标记编号，v4 = 加 / 减几层，v1 = 上限，v3 = 持续
                sid, top, delta = int(v[1]), int(v[0]) or 99, int(v[3])
                for x in tg:
                    cur = self._mark(x, sid)
                    until = t + float(v[2]) if delta > 0 else (x.marks.get(sid) or [0, t])[1]
                    x.marks[sid] = [float(max(0, min(top, cur + delta))), until]
            elif ty == 105:                            # 环境效果（比如「妨魔塵」）：只记它在不在，别的技能会看
                self.env[int(d[1])] = t + float(v[0])
            elif ty == 114:                            # 带标记的减伤（挨打掉一层并反击）：只算“标记在、己方减伤 v3%”
                for x in tg:
                    x.marks[int(v[0])] = [float(v[1]), t + float(v[3])]
                    x.cuts.append(["all", float(v[2]), t + float(v[3])])
            elif ty == 37:
                power = a.stat("matk" if d[0] == 2 else "atk", t)
                per, dur = v[0] + v[1] * lv + (v[2] + v[3] * lv) * power, v[4] + v[5] * lv
                for x in (tg if tg and tg[0].side == a.side else self._mates(a)):
                    x.dots.append([per * (1 + a.stat("hprec", t) / 100.0), t + dur, True, a])
            elif ty == 36:
                power = a.stat("matk" if d[0] == 2 else "atk", t)
                per, dur = v[0] + v[1] * lv + (v[2] + v[3] * lv) * power, v[4] + v[5] * lv
                for x in self._others(a):
                    x.dots.append([per / (1 + max(0.0, x.stat("mdef" if d[0] == 2 else "pdef", t)) / 100.0) * (self.mods.get("out", 1.0) if a.side == 0 else 1.0), t + dur, False, a])
            elif ty == 38:
                value, dur = v[0] + v[1] * lv, v[2] + v[3] * lv
                side = self._mates(a) if int(d[0]) % 10 == 0 else self._others(a)
                if a.side == 0 and int(d[0]) % 10 == 0:
                    value *= 1 + self.mods.get("buff_pct", 0.0) / 100.0
                for x in side:
                    self._aura(a, x, int(d[0]), d[1] == 2, value, dur)
            elif ty in (26, 27):
                # 数值修正：把目标动作的第 d2 个数值 加上 / 乘上 (v2 + v3×等级) × 某个量（v1 说是哪个量：7 物攻、8 魔攻、9 物防、10 魔防、4 目标数、0 自己的血量比例、1 掉了多少血）
                key = int(v[0])
                x = tg[0] if tg else a
                val = {7: a.stat("atk", t), 8: a.stat("matk", t), 9: a.stat("pdef", t), 10: a.stat("mdef", t), 4: float(len(tg)),
                       0: a.hp / a.max_hp, 1: 1 - a.hp / a.max_hp}.get(key)
                if 20 <= key < 30:                     # 技能计数
                    val = float(a.counters.get(key - 20, 0))
                elif 200 <= key < 300 or 2112 <= key < 3000:      # 标记层数
                    val = float(self._mark(x, key - (200 if key < 300 else 2000)))
                elif key == 2:                         # 已经打倒几个敌人
                    val = float(sum(1 for z in (self.foes if a.side == 0 else self.ours) if not z.alive))
                elif key == 6:
                    # 这个技能到这一步一共打出了多少伤害（所有目标加起来）。只在“敌人拿它去降我方最大生命”时算——幽灵领主的 UB：
                    # 范围里的人各掉一截血，再把范围里每个人的最大生命降掉“这一下的总伤害”。所以范围里只有一个人时她活得下来，
                    # 站了两个以上就一起倒（2026-11-27 拿 9 场真机记录核的）。别的用法（巨大吞拿鱼的 UB、我方十几个技能）没核过，照旧不算
                    target = by_id.get(int(d[0]))
                    if a.side == 1 and target is not None and target["t"] == 10 and int(target["d"][0]) == 1:
                        val = raw_dealt                # 按没被屏障、减伤抵掉之前的数算：真机上带着屏障的队照样是范围里的人一起倒
                if val is not None:
                    amount = (v[1] + v[2] * lv) * val
                    cap = v[3] + v[4] * lv                 # 加成有上限（v4 + v5×等级）
                    if ty == 26 and cap > 0:
                        amount = min(amount, cap)
                    slot = add.setdefault(int(d[0]), {}) if ty == 26 else mul.setdefault(int(d[0]), {})
                    slot[int(d[1])] = slot.get(int(d[1]), 0.0 if ty == 26 else 1.0) + amount if ty == 26 else slot.get(int(d[1]), 1.0) * amount
                else:
                    self.skipped[ty] = self.skipped.get(ty, 0) + 1
            elif ty in (2, 3, 7, 17, 18, 19, 90, 92, 93, 94, 95):
                pass                                   # 移动、击退、换目标、触发条件、被动：不影响这里的粗算
            else:
                self.skipped[ty] = self.skipped.get(ty, 0) + 1

    def _act(self, a: Actor) -> None:
        code = a.next_code
        t = self.t
        if a.stun_until > t:
            a.next_time = a.stun_until + 0.05
            return
        if code == "ub" and a.tp < 1000.0:
            code = self._peek(a)
        if code == "ub":
            a.tp = 1000.0 * min(0.9, max(0.0, a.stat("tpred", t)) / 100.0)
            a.ub_count += 1
            if a.side == 1:
                self.enemy_ub.append(round(t, 1))
            self._apply(a, a.sk["ub"], "ub")
        elif code == 1:
            tg = self._targets(a, {"tt": 3, "ta": 1, "tc": 1, "rg": -1}, {})
            for x in tg:
                rate = 1.0 if a.side == 0 else (1.0 if a.boss else MOB_TP_RATE)
                self._strike(a, x, a.stat("matk" if a.atk_type == "magic" else "atk", t) * (1 + (self.mods.get("normal_pct", 0.0) / 100.0 if a.side == 0 else 0.0)), a.atk_type, tp_rate=rate)
            a.tp = min(1000.0, a.tp + TP_ACTION * (1 + a.stat("tpup", t) / 100.0))
            a.idx += 1
        else:
            self._apply(a, a.sk[str(code)], str(code))
            a.tp = min(1000.0, a.tp + TP_ACTION * (1 + a.stat("tpup", t) / 100.0))
            a.idx += 1
        kind = _code_kind(code)
        a.next_code = self._peek(a)
        anim = ANIM_ENEMY if a.side == 1 else ANIM_UB if kind == "ub" else ANIM_ATTACK if kind == "attack" else ANIM_SKILL
        a.next_time = t + anim / a.speed(t) + self._cast(a, a.next_code)

    def _tick(self) -> None:
        t = self.t
        for a in self.ours + self.foes:
            if not a.alive:
                continue
            for dps, until, heal, src in a.dots:
                if until + 1e-6 < t:
                    continue
                if heal == "tp":
                    a.tp = min(1000.0, a.tp + dps)
                elif heal:
                    self._heal(src, a, dps)
                else:
                    self._hurt(src, a, dps, "magic", tp_rate=0.0, pierce=True)
            a.dots = [x for x in a.dots if x[1] > t]
            a.buffs = [x for x in a.buffs if x[3] > t]
            a.barriers = [x for x in a.barriers if x[2] > t and x[1] > 0]
            if a.hp_downs:
                a.hp_downs = [x for x in a.hp_downs if x[1] > t]
                self._remax(a)
            regen = self.mods.get("regen", 0.0)
            if regen and a.side == 0:
                self._heal(a, a, regen)
            dot = self.mods.get("enemy_dot", 0.0)
            if dot and a.side == 1:
                self._hurt(None, a, dot, "magic", tp_rate=0.0, pierce=True)

    def run(self) -> Result:
        while True:
            live = [a for a in self.ours + self.foes if a.alive]
            if not any(a.side == 0 for a in live) or not any(a.side == 1 for a in live):
                break
            nxt = min(live, key=lambda a: a.next_time)
            if min(nxt.next_time, self.next_tick) > self.limit:
                self.t = self.limit
                break
            if self.next_tick <= nxt.next_time:
                self.t = self.next_tick
                self.next_tick += 1.0
                self._tick()
                continue
            self.t = nxt.next_time
            self._act(nxt)
        win = not any(a.alive for a in self.foes)
        left = sum(a.hp for a in self.foes) / max(1.0, self.total_foe_hp)
        return Result(win=win, time=round(self.t, 1), deaths=list(self.deaths), left=round(left, 4), alive=sum(1 for a in self.ours if a.alive),
                      dealt={a.name: round(a.dealt) for a in self.ours}, taken={a.name: round(a.taken) for a in self.ours},
                      enemy_ub=list(self.enemy_ub), skipped=dict(self.skipped))


def simulate(data: Data, team: list[str], stage: str, mods: dict[str, float] | None = None, limit: float = 90.0, seed: int = 7) -> Result:
    return Battle(data, team, stage, mods, limit, seed).run()
