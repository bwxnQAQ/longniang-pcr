"""黎明界迷宫的饰品（EX 装备）目录。【正式】

来源：用户 2026-11-24 20:00 录的那一段（recordings/20261124-200041）——在公会选择页上挨个点十个公会的「i」，
「公会详情」的「可以获得的报酬」里写着这个公会的宝箱出什么。十个公会各出一个系列，每个系列火、水、风、光、暗五件，一共 50 件：

| 公会 | 游戏里的名字（× 五种属性） | 部位 | 系列 | 出发奖励里的遗物 |
| 美食殿堂     | 黎明○轮 α 赞颂      | 轮 | 赞颂 | 公主之力 |
| 破晓之星     | 黎明○环 α 主宰      | 环 | 主宰 | 星幽增幅 |
| 咲恋救济院   | 黎明○装 α 尊荣      | 装 | 尊荣 | 咲恋救济院誓约 |
| 王宫骑士团   | 黎明○玉 α 珍品      | 玉 | 珍品 | 信仰骑士 |
| 拉比林斯     | 黎明○饰 α 荣光      | 饰 | 荣光 | 拉比林斯权能 |
| 慈乐之音     | 黎明○轮阿尔法戒律   | 轮 | 戒律 | 光耀慈乐之音 |
| 恶魔伪王国军 | 黎明○环阿尔法卓绝   | 环 | 卓绝 | 苍蓝子夜 |
| 伊丽莎白牧场 | 黎明○装阿尔法金刚   | 装 | 金刚 | 伊丽莎白守护者 |
| 墨丘利财团   | 黎明○玉阿尔法原质   | 玉 | 原质 | 高贵紫藤庐 |
| 暮光流星群   | 黎明○饰阿尔法容受   | 饰 | 容受 | 兵法二海一流 |

除了饰品，每个公会的宝箱里还有「特别装备炼成点数」。前五个公会的名字里写的是希腊字母 α，后五个写的是汉字“阿尔法”（游戏里就是这样）。
部位按游戏里的那个字叫（轮、环、装、玉、饰）；看图标，轮像戒指、环像手镯、装像项链、玉像宝珠、饰像耳环——这是我看图说的，
所以“戒指、手镯、项链、宝珠、耳环”这些词只当别名用，写目标时能认。

这个文件管三件事：
  1. 目录本身（SERIES / ALL）；
  2. 从读到的一行字认出是哪一件（identify）——名字里的 α 文字识别常常读不准，所以不靠它；
  3. “要刷什么”的写法（parse_filter）：可以写到具体一件、一个系列、一个部位、一种属性，或者它们的组合。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

ELEMENTS = ("火", "水", "风", "光", "暗")
SLOTS = ("轮", "环", "装", "玉", "饰")
SLOT_ALIASES: dict[str, tuple[str, ...]] = {"轮": ("戒指", "指环", "指轮"), "环": ("手镯", "手环", "臂环"), "装": ("项链", "吊坠", "颈饰"),
                                            "玉": ("宝珠", "宝玉", "宝石球"), "饰": ("耳环", "耳饰", "耳坠")}
ANY_WORDS = ("饰品", "任意", "全部", "所有", "随便", "EX装备", "EX")


@dataclass(frozen=True)
class Series:
    guild: str          # 哪个公会的宝箱出
    slot: str           # 部位：轮 / 环 / 装 / 玉 / 饰
    suffix: str         # 系列名（名字最后两个字）
    greek: str          # 名字中间那一段：前五个公会是 "α"，后五个是 "阿尔法"
    relic: str          # 这个公会出发奖励里的遗物（和饰品无关，顺手记下）

    def name_of(self, element: str) -> str:
        return f"黎明{element}{self.slot}{self.greek}{self.suffix}"


SERIES: tuple[Series, ...] = (
    Series("美食殿堂", "轮", "赞颂", "α", "公主之力"),
    Series("破晓之星", "环", "主宰", "α", "星幽增幅"),
    Series("咲恋救济院", "装", "尊荣", "α", "咲恋救济院誓约"),
    Series("王宫骑士团", "玉", "珍品", "α", "信仰骑士"),
    Series("拉比林斯", "饰", "荣光", "α", "拉比林斯权能"),
    Series("慈乐之音", "轮", "戒律", "阿尔法", "光耀慈乐之音"),
    Series("恶魔伪王国军", "环", "卓绝", "阿尔法", "苍蓝子夜"),
    Series("伊丽莎白牧场", "装", "金刚", "阿尔法", "伊丽莎白守护者"),
    Series("墨丘利财团", "玉", "原质", "阿尔法", "高贵紫藤庐"),
    Series("暮光流星群", "饰", "容受", "阿尔法", "兵法二海一流"),
)
OTHER_DROPS = ("特别装备炼成点数",)        # 每个公会的宝箱里都有、但不是饰品的东西


@dataclass(frozen=True)
class Acc:
    """一件饰品 = 一个系列 + 一种属性。"""
    series: Series
    element: str

    @property
    def name(self) -> str:          # 游戏里写的名字，去掉了空格：黎明火轮α赞颂 / 黎明火轮阿尔法戒律
        return self.series.name_of(self.element)

    @property
    def guild(self) -> str:
        return self.series.guild

    @property
    def slot(self) -> str:
        return self.series.slot

    @property
    def key(self) -> str:           # 图标模板文件里用的键（只有字母数字）
        return f"s{SERIES.index(self.series)}e{ELEMENTS.index(self.element)}"

    @property
    def short(self) -> str:         # 日志里的短写法：火轮·赞颂
        return f"{self.element}{self.slot}·{self.series.suffix}"


ALL: tuple[Acc, ...] = tuple(Acc(s, e) for s in SERIES for e in ELEMENTS)
BY_NAME: dict[str, Acc] = {a.name: a for a in ALL}
BY_KEY: dict[str, Acc] = {a.key: a for a in ALL}


def series_of(guild: str | None) -> Series | None:
    return next((s for s in SERIES if s.guild == guild), None)


def of_guild(guild: str | None) -> list[Acc]:
    return [a for a in ALL if a.guild == guild]


# ---------- 认：读到的一行字是哪一件 ----------
_GREEK = re.compile(r"阿尔法|阿尔|尔法|[αɑа⍺∝aAɒ]")
_HEAD = re.compile(r"([火水风光暗])([轮环装玉饰])")


def clean(text: Any) -> str:
    return re.sub(r"[\s　·・.。:：,，、\-—_]+", "", str(text or ""))


def identify(text: Any, guild: str | None = None) -> tuple[Acc | None, str]:
    """读到的名字 → （哪一件, 怎么认出来的）。认不出返回 (None, "")。

    靠三样：① “属性 + 部位”两个字连在一起（火轮、暗饰……）；② 名字最后的系列名（赞颂、戒律……）；③ 前面有“黎明”。
    名字里的 α 不看（文字识别常把它读成 a、读丢）。系列名读对了 → "name"；系列名没读对：
      - 知道这一局打的是哪个公会、部位也对得上 → 按那个公会的系列算（"guild"）——一个公会的宝箱只出它自己那个系列；
      - 不知道公会，但看得出名字里写的是汉字“阿尔法”还是不是 → 同一个部位的两个系列里挑对应的那个（"greek"）。
    只有“黎明”和系列名、属性那个字没读出来的，不认（属性不能猜）。"""
    t = clean(text)
    if len(t) < 4:
        return None, ""
    m = _HEAD.search(t)
    if m is None:
        return None, ""
    element, slot = m.group(1), m.group(2)
    tail = t[m.end():]
    head = t[:m.start()]
    dawn = "黎明" in head or head.endswith(("黎", "明"))
    exact = [s for s in SERIES if s.suffix in tail]
    if exact:
        s = next((x for x in exact if x.slot == slot), None)
        if s is None:                                   # 部位那个字和系列名对不上：一定有一个读错了，以两个字的系列名为准（要有“黎明”）
            return (Acc(exact[0], element), "name") if dawn and len(exact) == 1 else (None, "")
        return Acc(s, element), "name"
    if not dawn:
        return None, ""
    mine = series_of(guild)
    if mine is not None and mine.slot == slot:
        return Acc(mine, element), "guild"
    pair = [s for s in SERIES if s.slot == slot]
    half = [s for s in pair if any(ch in tail for ch in s.suffix) and not any(ch in tail for o in pair if o is not s for ch in o.suffix)]
    if len(half) == 1:                                  # 系列名两个字里读对了一个，而且另一个系列的字一个都没有
        return Acc(half[0], element), "half"
    if re.search(r"阿尔法|阿尔|尔法", tail):
        return Acc(next(s for s in pair if s.greek == "阿尔法"), element), "greek"
    if tail and mine is None and re.match(r"[αɑа⍺∝aA]", tail):
        return Acc(next(s for s in pair if s.greek == "α"), element), "greek"
    return None, ""


def canonical(text: Any, guild: str | None = None) -> str | None:
    acc, _how = identify(text, guild)
    return acc.name if acc else None


def is_accessory(name: Any) -> bool:
    return identify(name)[0] is not None


# ---------- 要刷什么：一个目标可以写到多细 ----------
@dataclass(frozen=True)
class Filter:
    """一个目标的范围。哪一项是 None 就是那一项不限。"""
    element: str | None = None
    slot: str | None = None
    series: Series | None = None

    def match(self, acc: Acc) -> bool:
        return ((self.element is None or acc.element == self.element) and (self.slot is None or acc.slot == self.slot)
                and (self.series is None or acc.series is self.series))

    def members(self) -> list[Acc]:
        return [a for a in ALL if self.match(a)]

    def guilds(self) -> list[str]:
        """哪些公会的宝箱出得了这个范围里的东西（按目录的顺序）。"""
        return list(dict.fromkeys(a.guild for a in self.members()))

    @property
    def key(self) -> str:
        """标准写法（存账本、当键用）：火轮赞颂 / 轮赞颂 / 火轮 / 轮 / 火 / 饰品。"""
        if self.series is not None:
            return f"{self.element or ''}{self.series.slot}{self.series.suffix}"
        return f"{self.element or ''}{self.slot or ''}" or "饰品"

    def text(self) -> str:
        """给人看的说法。"""
        el = f"{self.element}属性的" if self.element else ""
        if self.series is not None:
            if self.element:
                return f"{self.series.name_of(self.element)}（{self.series.guild}）"
            return f"{self.series.suffix}系列的{self.series.slot}，哪种属性都算（{self.series.guild}）"
        if self.slot is not None:
            two = "、".join(f"{s.guild}·{s.suffix}" for s in SERIES if s.slot == self.slot)
            return f"{el}{self.slot}，两个系列都算（{two}）"
        return f"{el}饰品，哪个部位都算（十个公会都出）" if self.element else "随便哪一件饰品"


def parse_filter(key: Any) -> Filter | None:
    """你写的目标 → 范围。认的写法（可以混着写，顺序随意）：
      属性：火 水 风 光 暗；部位：轮 环 装 玉 饰（也认 戒指 / 手镯 / 项链 / 宝珠 / 耳环）；
      系列：赞颂 主宰 尊荣 珍品 荣光 戒律 卓绝 金刚 原质 容受，或者直接写公会名；游戏里的全名（黎明火轮α赞颂）；“饰品” = 随便哪一件。
    写了系列又写了对不上的部位（比如“环赞颂”）、或者一个字都不认识，返回 None。"""
    from . import guilds as GD
    raw = clean(key)
    if not raw:
        return None
    t = raw.replace("黎明", "")
    t = re.sub(r"阿尔法|[αɑа⍺∝aA]", "", t)
    any_word = next((w for w in ANY_WORDS if w in t), None)
    if any_word:
        t = t.replace(any_word, "", 1)
    series: Series | None = None
    for s in SERIES:
        if s.suffix in t:
            series, t = s, t.replace(s.suffix, "", 1)
            break
    if series is None:
        for std, keys in GD.GUILDS:
            hit = next((k for k in sorted((std,) + tuple(keys), key=len, reverse=True) if k in t), None)
            if hit:
                series, t = series_of(std), t.replace(hit, "", 1)
                break
    for w in ("系列", "属性", "的", "哪种", "都算", "×", "x", "X"):
        t = t.replace(w, "")
    slot: str | None = None
    for sl, names in SLOT_ALIASES.items():
        hit = next((n for n in names if n in t), None)
        if hit:
            slot, t = sl, t.replace(hit, "", 1)
            break
    element: str | None = None
    for ch in t:
        if ch in ELEMENTS and element is None:
            element = ch
        elif ch in SLOTS and slot is None:
            slot = ch
        else:
            return None                                 # 还剩不认识的字：不猜
    if series is not None and slot is not None and series.slot != slot:
        return None
    if series is None and slot is None and element is None and not any_word:
        return None
    return Filter(element, None if series is not None else slot, series)


def count_in(flt: Filter, items: dict[str, int]) -> int:
    """一张战利品清单（{名字: 数量}）里，落在这个范围里的饰品一共几件。"""
    n = 0
    for name, c in items.items():
        acc = BY_NAME.get(name) or identify(name)[0]
        if acc is not None and flt.match(acc):
            n += int(c)
    return n


def best_guild(left: dict[str, int], candidates: list[str] | None = None, prefer: str | None = None) -> tuple[str | None, str]:
    """还差这些目标（{目标的标准写法: 还差几件}）的时候，下一局该打哪个公会：挑“能出的目标加起来还差最多”的那个；
    一样多先挑 prefer（你平时打的那个），再按目录的顺序。candidates 给了就只在里面挑。没有哪个公会出得了返回 (None, 原因)。"""
    need: dict[str, int] = {}
    for key, n in left.items():
        flt = parse_filter(key)
        if flt is None or n <= 0:
            continue
        for g in flt.guilds():
            need[g] = need.get(g, 0) + int(n)
    pool = [g for g in (candidates or [s.guild for s in SERIES]) if need.get(g)]
    if not pool:
        able = "、".join(sorted(need, key=lambda x: -need[x])) or "（哪个公会都不出）"
        return None, f"候选的公会（{'、'.join(candidates or [])}）的宝箱不出还差的这些饰品；出得了的是：{able}"
    order = [s.guild for s in SERIES]
    g = max(pool, key=lambda x: (need[x], x == prefer, -order.index(x) if x in order else -99))
    s = series_of(g)
    mine = [k for k, n in left.items() if n > 0 and (f := parse_filter(k)) is not None and g in f.guilds()]
    only = all(len(f.guilds()) == 1 for k in mine if (f := parse_filter(k)) is not None)
    return g, (f"还差的 {'、'.join(mine)} 只有它的宝箱出" if only
               else f"它的宝箱出{s.slot}（{s.suffix}系列），还差的 {'、'.join(mine)} 里它出得了的最多（一共还差 {need[g]} 件）")


def catalog() -> list[dict[str, Any]]:
    """给界面用的目录：十行，一个公会一行。"""
    return [{"guild": s.guild, "slot": s.slot, "suffix": s.suffix, "greek": s.greek, "relic": s.relic,
             "alias": SLOT_ALIASES[s.slot][0], "names": [s.name_of(e) for e in ELEMENTS]} for s in SERIES]
