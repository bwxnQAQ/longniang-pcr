"""按技能说明给角色标特点（纯文字处理，不联网、不碰画面）。

资料站 pcr.satroki.tech 的角色详情接口（/api/Unit/GetUnitInfo/<编号>?s=cn&withNo=True）里带着每个技能的中文说明，
比如“对前方一名敌人造成物理伤害（大），并对自身周围的所有敌人造成物理伤害（中）。”。这里只看这些说明里的固定说法：

  hit    擅长打一群（"aoe"）、打一个（"single"）还是都行（"both"）：看每个伤害技能打的是“一名敌人”还是“所有敌人 / 敌方全体 / 范围内”；
         连结爆发算 2 份，技能 1、技能 2 各 1 份，特殊技能各半份；打一群的占 65% 以上是 aoe，35% 以下是 single，中间是 both。
  heal   会不会给队友回血：给全队回（我方全体 / 范围内所有我方 / 领域 / 持续回复）的技能有几个就是几（1、2、3）；
         只能给一名队友回是 0.5；只回自己、不会回血是 0。（用户 2026-11-19 定的：要带奶的时候不一定带纯奶，很多强力角色自己就有奶）
  tags   dot = 能让敌人中毒 / 猛毒 / 诅咒 / 烧伤；patk_down / matk_down = 能降敌人的物理 / 魔法攻击力；
         selfharm = 自损：技能会消耗自己的生命值、用完以后大幅降自己的防御、或者会自爆（杏奈、伊莉亚这一类）——
         这种人站在全队最前面一上来就倒（2026-11-19 真机上两场都是杏奈站最前面、几秒就没了），编队时不让她站最前面。

有专武、六星的技能用强化后的说明（资料站上国服已经实装的才有）。说法是按 2026-11-19 国服 320 个角色的技能说明归纳的，
以后出了新写法认不出来就是“不标”，不会标错成别的。
"""
from __future__ import annotations

import re
from typing import Any

_MULTI = re.compile(r"所有|全体|全员|全部|周围|周边|范围内|最多|[两三四五N\d]名|[两三四五N\d]个|敌方$|前方敌人$|前方的敌人")
_ONE = re.compile(r"一名|一个|第二名|任意一名")
_ALL_WORD = re.compile(r"所有|全体|全员|全部")
_ALLY = re.compile(r"我方|己方|自身|角色$|成员$")
_SAME = re.compile(r"^(其|该名敌人|该敌人|对方|目标|该目标)$")
_HIT_TO = re.compile(r"对([^，。；：]*?)造成")
_SPLIT = re.compile(r"[，。；]")
_TEAM = re.compile(r"[我己]方全体|[我己]方全员|[我己]方所有|所有[我己]方|[我己]方[^，。；]*所有角色|范围内[^，。；]*[我己]方|[我己]方[^，。；]*范围内"
                   r"|周围[^，。；]*[我己]方|[我己]方在前方的所有|领域")
_ONE_ALLY = re.compile(r"[我己]方[^，。；]*一名|一名[我己]方|最前方[^，。；]*[我己]方角色")
_DOT = re.compile(r"中毒|猛毒|诅咒|烧伤|毒咒")
_TOP_OF = re.compile(r"(物理攻击力|魔法攻击力|攻击力)(或魔法攻击力)?(（[^）]*）)?最[高低]的")
HEAL_RANK = {"all": 3, "one": 2, "self": 1}


def _clean(text: Any) -> str:
    return str(text or "").replace("\\n", "").replace("\n", "")


def damage_targets(text: str) -> tuple[bool, bool]:
    """这个技能的伤害有没有打一群的（第一个）、有没有打一个的（第二个）。"""
    aoe = single = False
    last = None
    hits = 0
    for m in _HIT_TO.finditer(text):
        p = re.sub(r"(追加|连续)$", "", m.group(1))
        if _ALLY.search(p) and "敌" not in p:
            continue
        kind = None
        if _SAME.match(p):
            kind = last or "S"
        elif _ONE.search(p) and not _ALL_WORD.search(p):
            kind = "S"
        elif _MULTI.search(p):
            kind = "A"
        elif p.startswith("其"):
            kind = last or "S"
        if kind:
            hits += 1
            last = kind
            aoe, single = aoe or kind == "A", single or kind == "S"
    if not hits and re.search(r"造成[^，。；]*(物理|魔法)伤害", text):      # “降低前方所有敌人的防御力，造成物理伤害”这种：没有“对…造成”
        if re.search(r"所有敌人|敌方全体|敌人全体|范围内[^，。；]*敌", text):
            aoe = True
        elif re.search(r"一名敌人|一个敌人", text):
            single = True
    return aoe, single


def _scope(s: str) -> str | None:
    if _TEAM.search(s):
        return "all"
    if _ONE_ALLY.search(s):
        return "one"
    if "自身" in s:
        return "self"
    return None


def heal_scope(text: str) -> str | None:
    """这个技能给谁回血："all" 全队（或范围内的队友）、"one" 一名队友、"self" 只回自己；不回血是 None。"""
    best = None
    for cl in _SPLIT.split(text):
        if "回复" not in cl or not re.search(r"生命值|生命力", cl):
            continue
        if re.search(r"降低[^，。；]*生命值回复量", cl):
            continue
        if "回复量" in cl and not re.search(r"回复[^量]*生命", cl):          # “生命值的回复量越高”这种是在说数值，不是回血
            continue
        sc = _scope(cl) or _scope(text) or "one"
        if best is None or HEAL_RANK[sc] > HEAL_RANK[best]:
            best = sc
    return best


def gives_dot(text: str) -> bool:
    for cl in _SPLIT.split(text):
        c = cl.strip()
        if _DOT.search(c) and re.search(r"陷入|赋予", c) and not re.match(r"当|若|如果", c) and not re.search(r"[我己]方|自身", c):
            return True
    return False


_SELF_KO = re.compile(r"自爆|自身会?陷入无法战斗")
_SELF_COST = re.compile(r"消耗自身[^，。；【]{0,8}生命")
_SELF_DOWN = re.compile(r"使用后[^。；]*降低[^，。；]*防御力|(大幅|特大幅度?)降低自身的[^，。；]*防御力")


def self_harm(text: str) -> bool:
    """这个技能是不是自损的：自爆、消耗自己的生命值、用完以后（大幅）降自己的防御。只降一点点的、要叠了别的状态才扣血的不算。"""
    return bool(_SELF_KO.search(text) or _SELF_COST.search(text) or _SELF_DOWN.search(text))


def attack_down(text: str) -> tuple[bool, bool]:
    """能不能降敌人的物理攻击力（第一个）、魔法攻击力（第二个）。降自己人的不算；“魔法攻击力最高的一名敌人”这种只是在指人，也不算。"""
    phys = magic = False
    for cl in _SPLIT.split(text):
        if "降低" not in cl or re.search(r"自身|[我己]方", cl):
            continue
        whole = cl
        cl = _TOP_OF.sub("", cl)
        seg = cl[cl.find("降低"):] if "降低" in cl else ""
        if "物理·魔法攻击力" in seg or "敌人的攻击力" in whole:
            phys = magic = True
        phys = phys or "物理攻击力" in seg
        magic = magic or "魔法攻击力" in seg
    return phys, magic


def unit_traits(skills: dict[str, Any]) -> dict[str, Any]:
    """skills = 资料站角色详情里的 unitSkillModel 压平以后的 {槽位: 技能说明}（unionBurst / unionBurstEvo / main1 / main1Evo / main2 / main2Evo / sp1…）。
    返回 {"hit": "aoe" / "single" / "both" / None, "heal": 0 / 0.5 / 1 / 2 / 3, "tags": [...]}。"""
    s = {k: _clean(v) for k, v in (skills or {}).items() if isinstance(v, str)}

    def pick(a: str, b: str) -> str:
        return s.get(a) or s.get(b) or ""

    use = [(pick("unionBurstEvo", "unionBurst"), 2.0), (pick("main1Evo", "main1"), 1.0), (pick("main2Evo", "main2"), 1.0)]
    for k in ("sp1Evo", "sp1", "sp2", "sp3"):
        if s.get(k) and not (k == "sp1" and s.get("sp1Evo")):
            use.append((s[k], 0.5))
    aoe = single = 0.0
    heal, team_heals = None, 0
    dot = phys = magic = False
    for text, w in use:
        if not text:
            continue
        a, o = damage_targets(text)
        aoe += w if a else 0.0
        single += w if o else 0.0
        h = heal_scope(text)
        if h:
            heal = h if heal is None or HEAL_RANK[h] > HEAL_RANK[heal] else heal
            team_heals += h == "all"
        dot = dot or gives_dot(text)
        p, m = attack_down(text)
        phys, magic = phys or p, magic or m
    hit = None
    if aoe + single > 0:
        r = aoe / (aoe + single)
        hit = "aoe" if r >= 0.65 else "single" if r <= 0.35 else "both"
    harm = any(self_harm(text) for text, w in use[:3] if text)          # 只看连结爆发和两个技能（特殊形态下的技能不算）
    tags = [t for t, on in (("dot", dot), ("patk_down", phys), ("matk_down", magic), ("selfharm", harm)) if on]
    return {"hit": hit, "heal": float(team_heals) if heal == "all" else 0.5 if heal == "one" else 0.0, "tags": tags}


def flatten(model: dict[str, Any] | None) -> dict[str, str]:
    """资料站的 unitSkillModel → {槽位: 说明}（只留有说明的）。"""
    out: dict[str, str] = {}
    for k, v in (model or {}).items():
        if isinstance(v, dict) and v.get("description"):
            out[k] = _clean(v["description"])
        elif isinstance(v, list):
            text = "/".join(_clean(x.get("description")) for x in v if isinstance(x, dict) and x.get("description"))
            if text:
                out[k] = text
    return out
