"""四个凹度档位（方案是用户 2026-11-19 定的，2026-11-24 做出来）。设置里的 walk.tier，界面上能选；默认第二档 = 以前一直在用的打法。

| 档 | 极难 | 重开 | 区域 3 首领 | 编队 |
| 1 最高凹分 | 一列不落 | 极难走不到、首领不合意、前两个区域的事件给得少、第二层（区域 2）绕不开商店，都撤退重开（上限放宽到 20 次） | 一队过 | 全输出，打输了再加保命的 |
| 2 极难全打 | 一列不落 | 只有极难走不到（或某一场怎么都打不过）才重开 | 一队过 | 同上 |
| 3 稳着打   | 能走到几个打几个 | 极难走不到不重开 | 先一队，输了多编一队 | 估算往坏处多想一档，多给一次重打 |
| 4 保通关   | 能不走就不走 | 同上 | 一开始就两队，输了三队 | 极难 / 首领第一次就带坦克和治疗，估算往坏处多想两档 |

所有档位：普通关都按快攻打；最终首领照旧不打（打完会结算、用掉通行证，那是另一个开关）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import plan as PL


@dataclass(frozen=True)
class Tier:
    n: int
    name: str
    blurb: str                         # 日志和界面上的一句话
    extreme: str = "all"               # 路线上的极难："all" 一列不落（走不到就重开）/ "most" 能走到几个打几个 / "avoid" 能不走就不走
    restart_blocked: bool = True       # 极难走不到要不要撤退重开
    max_restarts: int | None = None    # 最多重开几次（None = 用设置里的 walk.max_restarts）
    retries: int | None = None         # 一场打输以后最多换队再打几次（None = 用设置里的 walk.defeat_retries）
    boss_mid_teams: int | None = None  # 区域 3 首领第一次编几队（None = 用设置里的 walk.boss_teams_mid）
    boss_more: bool = False            # （2026-11-27 起不看这一项了：哪一档打输了都多编一队，除非勾了“一队过不了就重开”，见 REROLL_DEFAULTS 的 boss3_single）
    guards: tuple[str, ...] = ()       # 极难 / 首领第一次就带上的保命职能
    caution: int = 0                   # 战斗估算往坏处多想几档（按“已经输过几次”那样放大敌人的伤害）
    reroll: bool = False               # 开局凹：首领不合意、事件给得少就重开


TIERS: dict[int, Tier] = {
    1: Tier(1, "第一档·最高凹分", "极难全打；极难走不到、首领不合意、前两个区域的事件给得少、第二层绕不开商店都撤退重开；区域 3 首领先一队、输了多编一队（“第四层没双极难就重开”“第三层首领一队过不了就重开”在「更多选项」里勾了才算）",
            max_restarts=20, reroll=True),
    2: Tier(2, "第二档·极难全打", "极难全打，只有极难走不到才重开；区域 3 首领先一队、输了多编一队（“第四层没双极难就重开”“第三层首领一队过不了就重开”在「更多选项」里勾了才算）"),
    3: Tier(3, "第三档·稳着打", "极难能走到几个打几个，走不到不重开；区域 3 首领先一队、输了多编一队；打输多给一次重打",
            extreme="most", restart_blocked=False, retries=3, boss_more=True, caution=1),
    4: Tier(4, "第四档·保通关", "能不走极难就不走；极难和首领第一次就带坦克、治疗；区域 3 首领一开始就两队",
            extreme="avoid", restart_blocked=False, retries=4, boss_mid_teams=2, boss_more=True, guards=("tank", "heal"), caution=2),
}
DEFAULT = 2
# 第一档凹什么（设置里的 walk.reroll 可以改）：
#   boss_want = 只留这些首领（区域 3 首领和最终首领的名字都写进去；空着 = 不挑）；boss_avoid = 遇到就重开的首领（和 walk.boss_avoid 合在一起）；
#   event_min = 前 areas 个区域里，一个事件拿到的东西折成分数低于这个数就重开（角色 200、遗物 400、5 金币 1 分；0 = 不凹事件）
#   auto_avoid = 真机上打过两次以上、一次都没赢过的首领，自动算进“遇到就重开”（账本见 wins.py）
#   no_shop_areas = 这几个区域不走商店（2026-11-24 用户定的：第二层如果必须走商店就重开）：有不过商店、极难又一列不落的路就走那条，
#     没有就撤退重开。默认只有区域 2；写成 [] 就是不管商店
#   no_shop_always = 不管哪一档都按 no_shop_areas 来（2026-11-27 用户要的：「更多选项」里“第二层绕不开商店就重开”哪一档都能勾；界面勾了 = --shop-reroll）。
#     别的档位里“极难一列不落”换成那一档自己对极难的要求（第三档能走到几个算几个，第四档不走极难）
#   marks_first = 区域 1 至少要踩到几个印记格（给角色的格子；区域 1 的第 2、4 列各有一个），踩不到这么多就撤退重开。0 = 不管（默认）。
#     2026-11-27 用户要的「第一层没双角色格就重开」= 2（界面勾了 = --marks-reroll）。哪一档都管用
#   double_ex4 = 区域 4 的两个极难没法都走到时要不要撤退重开。2026-11-27 用户定的：这一条不再是默认的，放进「更多选项」
#     （界面勾了 = --ex4-reroll）。False（默认）：第一、二档在区域 4 也只打走得到的，不为这个重开；True：重开（第三档勾了也重开，第四档不走极难、不管）。
#     别的区域照旧：第一、二档极难走不到就重开
#   boss3_single = 区域 3 首领只用一队打、打不过就撤退。2026-11-27 用户定的：这一条也不再是默认的，放进「更多选项」（界面勾了 = --boss3-single）。
#     False（默认）：哪一档都是打输了下一次多编一队（以前只有第三、四档这样）；True：只编队伍 1，重打也不加队，打满次数还不过就撤退重开。
#     （手上 83 场区域 3 首领的记录：一队打 34 胜 49 负，赢的也要 63～89 秒；三队打的最终首领 21 胜 0 负。）
REROLL_DEFAULTS: dict[str, Any] = {"boss_want": [], "boss_avoid": [], "event_min": 400, "areas": 2, "auto_avoid": True, "no_shop_areas": [2],
                                   "no_shop_always": False, "marks_first": 0, "double_ex4": False, "boss3_single": False}


def get(n: Any) -> Tier:
    try:
        return TIERS[int(n)]
    except (KeyError, TypeError, ValueError):
        return TIERS[DEFAULT]


def reroll_of(cfg: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(REROLL_DEFAULTS)
    for k, v in (cfg or {}).items():
        if k in out:
            out[k] = v
    out["boss_want"] = [str(x) for x in (out["boss_want"] or [])]
    out["boss_avoid"] = [str(x) for x in (out["boss_avoid"] or [])]
    out["auto_avoid"] = bool(out["auto_avoid"])
    out["no_shop_always"] = bool(out["no_shop_always"])
    out["double_ex4"] = bool(out["double_ex4"])
    out["boss3_single"] = bool(out["boss3_single"])
    try:
        out["marks_first"] = max(0, min(2, int(out["marks_first"] or 0)))
    except (TypeError, ValueError):
        out["marks_first"] = 0
    try:
        out["no_shop_areas"] = sorted({int(x) for x in (out["no_shop_areas"] or []) if 1 <= int(x) <= 5})
    except (TypeError, ValueError):
        out["no_shop_areas"] = list(REROLL_DEFAULTS["no_shop_areas"])
    try:
        out["event_min"] = max(0.0, float(out["event_min"]))
        out["areas"] = max(0, min(5, int(out["areas"])))
    except (TypeError, ValueError):
        out["event_min"], out["areas"] = float(REROLL_DEFAULTS["event_min"]), int(REROLL_DEFAULTS["areas"])
    return out


def with_guards(tier: Tier, tweak: dict[str, Any] | None, kind: str) -> dict[str, Any] | None:
    """这一档在极难 / 首领第一次就要带的保命职能，加进这一场的对策里（对策表里已经写了的不重复）。普通战不加。"""
    if not tier.guards or kind not in ("extreme", "boss"):
        return tweak
    tw = dict(tweak or {})
    tw["always"] = list(tw.get("always") or []) + [g for g in tier.guards if g not in (tw.get("always") or [])]
    return tw


def missing_guards(tier: Tier, team: list[tuple[str | None, bool]]) -> list[str]:
    """一队人里缺这一档要求的哪种保命职能。team = [(职能, 会不会给全队回血)]。不要求保命的档位永远返回空。"""
    out = []
    for g in tier.guards:
        if g == "tank" and not any(kind == "tank" for kind, _heal in team):
            out.append(g)
        if g == "heal" and not any(kind == "heal" or heal for kind, heal in team):
            out.append(g)
    return out


def event_gain(before: dict[str, Any], after: dict[str, Any]) -> float | None:
    """一个事件前后地图上的数字差折成分数：角色 200、遗物 400、金币按 5 个 1 分。有哪个数没读出来就返回 None（不知道）。"""
    try:
        c = int(after["chars"]) - int(before["chars"])
        r = int(after["relics"]) - int(before["relics"])
        g = int(after["coins"]) - int(before["coins"])
    except (KeyError, TypeError, ValueError):
        return None
    return 200.0 * c + 400.0 * r + g / PL.COIN_RATE


def boss_verdict(bosses: list[str | None], want: list[str], avoid: list[str]) -> str:
    """看完两个首领：要重开返回原因，不重开返回 ""。没认出来的首领不算数（认不出就不凹，免得一直重开）。"""
    bad = [b for b in bosses if b and b in avoid]
    if bad:
        return f"这一局的首领是{'、'.join(bad)}（写了遇到就重开）"
    if want:
        off = [b for b in bosses if b and b not in want]
        if off:
            return f"这一局的首领是{'、'.join(off)}，不在想要的名单里（{'、'.join(want)}）"
    return ""


def suggest(powers: list[float]) -> tuple[int, str]:
    """按账号里角色的强度估一个档位（只是建议，不会自己改）：强度 3 以上的角色够多就打极难，少就保通关。"""
    strong = sum(1 for p in powers if p >= 3.0)
    if strong >= 25:
        return 2, f"强度 3 以上的角色有 {strong} 个，极难全打没问题（想花时间凹就用第一档）"
    if strong >= 10:
        return 3, f"强度 3 以上的角色有 {strong} 个，极难能打一部分"
    return 4, f"强度 3 以上的角色只有 {strong} 个，先保通关"
