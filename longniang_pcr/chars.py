"""认具体角色：头像 → 名字。

头像指纹见 vision/cards.py 的 fingerprint。名字和头像有三个来源，各管各的一块：
  1. 黎明界里的画面（entries 的 fps）：每个角色进队时弹的「角色加入」上是小头像 + 全名（带“（夏日）”这种版本），招募页上也有名字。
  2. 资料站（entries 的 wfps）：B 站 WIKI 角色图鉴上每个角色的全名 + 三种星级的头像（「更新角色」下的，要先和游戏里的头像校准）。
  3. 「读角色」（sightings）：游戏「角色」页上每个角色现在显示的头像 + 横条上的名字。
     **横条上只有本名，不带版本**（2026-11-17 真机：凯露（夏日）的横条上写的是“凯露”），所以一个本名可能对着好几个版本——
     哪个版本要靠头像去对资料站的头像（resolve_sightings）。只有一个版本的本名（斑比、拉姆……）直接就是全名。
认人（identify）时三块一起看：读角色看到的头像是游戏里的原图，最准；它的全名定不下来时这张头像就先不认（宁可不认，不要认错）。

名字只认“正式名单”里有的（data/characters.json 的 names + 资料站读来的）：OCR 会把“碧”读成“珀”，名单里没有就当没读出来，
等头像去认；刚出的新角色名单里还没有时，先跑一次「更新角色」。
角色的特点（开局充能、持续伤害、降物攻……）在 data/characters.json，按全名查；表里没有的角色只按职能和属性算。
每场战斗谁上场、打了多久也记一笔（stats），只是留作参考，不参与策略——策略只按攻略来。
"""
from __future__ import annotations

import base64
import difflib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import numpy as np
from . import damage as DM

VERSION = 2                  # 头像库文件的格式。1（2026-11-17 晚之前）把「读角色」读到的本名直接当全名记，几个版本的头像混在一个名字下面，作废
SAME = 0.85                  # 指纹相似度到这个数算同一张头像（同一个角色 ≥0.93，不同角色 ≤0.80）
UNREAD_OK = 5             # 「读角色」里名字没读出来的头像不超过这么多张：照样敢说“这个角色玩家没有”；再多就说不准了
SAME_SIGHT = 0.88            # 「读角色」两次看到的是不是同一张头像（都是游戏里的原图，卡得严一点）
FACE_SURE = 0.90             # 没有名字线索、只凭资料站的头像认人，要到这个数、并且明显比第二像的高
MAX_FPS = 8                  # 一个角色最多存几张指纹（换过头像的几种样子，加上小头像、大头像、名单里的卡片之间的细微差别）
_CH = r"一-鿿A-Za-z0-9·・＆＝"
_NAME_OK = re.compile(rf"^[{_CH}]{{1,14}}(（[{_CH}]{{1,8}}）)?$")


_NOT_NAMES = ("以下角色", "角色加入", "关闭", "选择", "邀请", "伙伴", "奖励", "等级", "还剩")


def norm_text(text: str) -> str:
    """去空格，括号统一成全角，& 统一成全角。"""
    t = re.sub(r"\s+", "", text or "")
    return (t.replace("(", "（").replace(")", "）").replace("〔", "（").replace("〕", "）").replace("［", "（").replace("］", "）")
            .replace("&", "＆").replace("=", "＝"))


def clean_name(text: str) -> str:
    """OCR 读到的字 → 规整的角色名：去空格、括号统一成全角、去掉“成为了同伴。”这类尾巴。读得不像名字就返回空串。"""
    t = norm_text(text)
    t = re.sub(r"(成为了同伴|已加入到伙伴中|加入了).*$", "", t)
    t = t.strip("。.,，:：!！、|")
    if t.count("（") == 1 and "）" not in t:          # 右括号没读出来
        t += "）"
    if not _NAME_OK.match(t) or not re.search(r"[\u4e00-\u9fff]", t) or any(w in t for w in _NOT_NAMES):
        return ""
    return t


# 角色简介（游戏里那段介绍，资料站的名单接口带着）里说到“打一群”还是“打一个”的说法。只有一部分角色的简介提到了，没提到的不标。
_HIT_AOE = re.compile(r"全体敌|敌方全体|敌人全体|敌全体|所有敌|全部敌|范围攻击|大范围|范围内的敌|范围的敌|周围的敌|周围敌|自身周围|聚集的敌|前方的敌人|前方敌人"
                      r"|全体魔法攻击|全体攻击|敌方全员|多个敌|复数|附近敌人|附近的敌|广范围|群体|一扫|横扫|歼灭|箭雨|范围魔法|范围伤害|范围物理|全域|整个战场|敌阵")
_HIT_ONE = re.compile(r"敌方单体|单个敌|单体攻击|单体进行|单体造成|单体特大|单体连结|单体的|一名敌人|一点突破|眼前的敌人|单体高|对单体|单体物理|单体魔法|单体伤害"
                      r"|单一敌|一个敌人|最前方的敌人|最前面的敌")


def hit_of(comment: str) -> str | None:
    """角色简介 → "aoe"（打一群）/ "single"（打一个）/ "both" / None（简介里没提）。"""
    t = (comment or "").replace("\\n", "").replace("\n", "")
    a, o = bool(_HIT_AOE.search(t)), bool(_HIT_ONE.search(t))
    return "both" if a and o else "aoe" if a else "single" if o else None


# 增益 / 强化 / 减益型的角色帮的是物理队还是法队（看简介里的说法；自己是物理还是魔法不算数——有的魔法角色专门强化物理队）
_AID_PHYS = re.compile(r"(提升|提高|强化|增强|支援|辅助)[^。，]{0,14}物理攻击|(?<!应对)(?<!对抗)(?<!对付)物理型(队伍|角色)|物理角色|物理攻击(型)?角色"
                       r"|使用物理攻击的我方|为物理|物理、魔法攻击")
_AID_MAGIC = re.compile(r"(提升|提高|强化|增强|支援|辅助)[^。，]{0,14}魔法攻击|(?<!应对)(?<!对抗)(?<!对付)魔法型(队伍|角色)|魔法角色|魔法攻击(型)?角色"
                        r"|使用魔法攻击的我方|为魔法|物理、魔法攻击")


def aid_of(comment: str) -> str | None:
    """角色简介 → 这个人的增益 / 支援是给物理队的（"phys"）、给法队的（"magic"）、两边都给（"both"），还是简介里没说（None）。"""
    t = re.sub(r"^【[^】]*】", "", (comment or "").replace("\\n", "").replace("\n", ""))
    a, m = bool(_AID_PHYS.search(t)), bool(_AID_MAGIC.search(t))
    return "both" if a and m else "phys" if a else "magic" if m else None


def base_of(name: str) -> str:
    """全名 → 本名：去掉后面的“（版本）”。"""
    return re.sub(r"（[^（）]*）$", "", name or "")


_NAME_IN = re.compile(rf"[{_CH}]{{1,14}}(（[{_CH}]{{1,8}}）?)?")


def find_name(text: str) -> str:
    """比 clean_name 宽松：OCR 读到的字前后带了别的东西（边框、花纹被当成字）时，把里面最像名字的那一段找出来。"""
    whole = clean_name(text)
    if whole:
        return whole
    t = norm_text(text)
    best = ""
    for m in _NAME_IN.finditer(t):
        cand = clean_name(m.group(0))
        if len(re.findall(r"[\u4e00-\u9fff]", cand)) > len(re.findall(r"[\u4e00-\u9fff]", best)):
            best = cand
    return best


def _enc(fp: np.ndarray) -> str:
    return base64.b64encode(np.clip(np.round(fp * 127 * 8), -127, 127).astype(np.int8).tobytes()).decode("ascii")


def _dec(s: str) -> np.ndarray | None:
    try:
        a = np.frombuffer(base64.b64decode(s), dtype=np.int8).astype(np.float32).reshape(16, 17, 3)
    except Exception:  # noqa: BLE001
        return None
    n = float(np.linalg.norm(a))
    return a / n if n > 1e-3 else None


def _sim(a: np.ndarray, b: np.ndarray) -> float:
    return float((a * b).sum())


class CharBook:
    """头像库 + 角色特点表。path 不给就只在内存里（自测用）。"""

    def __init__(self, path: Path | None = None, table: dict[str, Any] | None = None):
        self.path = Path(path) if path else None
        self.table: dict[str, Any] = dict((table or {}).get("chars") or {})
        self.known_names: set[str] = set((table or {}).get("names") or []) | set(self.table)     # 正式名单（全名）：只认这里面有的名字
        self.builtin_names: frozenset[str] = frozenset((table or {}).get("names") or [])           # 项目自带的那份名单（「更新角色」拿它分辨“新角色”和“老角色变强了”）
        self.ocr_fix: dict[str, str] = dict((table or {}).get("ocr_fix") or {})                  # OCR 每次都读错的字：读到的 → 实际的（“珀” → “碧”）
        self.attrs: dict[str, str] = dict((table or {}).get("attrs") or {})                      # 全名 → 属性（资料站的）：同一个本名的几个版本属性常常不一样
        self.atks: dict[str, str] = dict((table or {}).get("atks") or {})                        # 全名 → "phys" / "magic"（资料站的）：物理队和法队分开用
        self.hits: dict[str, str] = dict((table or {}).get("hits") or {})                        # 全名 → "aoe" / "single" / "both"（按技能说明标的）
        self.heals: dict[str, float] = {str(n): float(v) for n, v in ((table or {}).get("heals") or {}).items() if isinstance(v, (int, float))}   # 全名 → 会不会给队友回血（≥1 = 能给全队回）
        self.more_tags: dict[str, frozenset[str]] = {}    # 全名 → 「更新角色」按技能说明给新角色标的特点（data/learned/wiki.json 的 traits）
        self.pvp: frozenset[str] = frozenset(str(n) for n in ((table or {}).get("pvp") or []))      # 纯竞技场用的角色（不是坦克时不上）
        self.toughs: dict[str, float] = {str(n): float(v) for n, v in ((table or {}).get("tough") or {}).items() if isinstance(v, (int, float))}   # 全名 → 耐打程度（一般坦克 = 1）
        self.toughs_p: dict[str, float] = {str(n): float(v) for n, v in ((table or {}).get("tough_phys") or {}).items() if isinstance(v, (int, float))}    # 全名 → 只算挨物理伤害时的耐打程度
        self.toughs_m: dict[str, float] = {str(n): float(v) for n, v in ((table or {}).get("tough_magic") or {}).items() if isinstance(v, (int, float))}   # 全名 → 只算挨魔法伤害时的
        self.aids: dict[str, str] = dict((table or {}).get("aids") or {})                        # 全名 → 增益 / 支援是给物理队还是法队的（按简介标的）
        self.roles_as: dict[str, str] = {n: v["as"] for n, v in ((table or {}).get("roles_as") or {}).items() if isinstance(v, dict) and v.get("as")}
        self.poss: dict[str, int] = dict((table or {}).get("pos") or {})                         # 全名 → 站位（数越小越靠前）：坦克要站最前面才有意义
        self.powers: dict[str, float] = {str(n): float(v) for n, v in ((table or {}).get("power") or {}).items() if isinstance(v, (int, float))}    # 全名 → 强度（数字越大越强，没有上限）
        self.bumps: dict[str, float] = {}             # 全名 → 「更新角色」发现她新出了专武 / 六星，强度往上加几档（data/learned/wiki.json 的 bumps）
        self.upgrade_table: dict[str, Any] = dict((table or {}).get("upgrade_table") or {})       # 出了专武以后强度怎么变（按攻略整理的）
        self.upgrades: dict[str, set[str]] = {k: set((table or {}).get(k) or []) for k in ("six", "ue1", "ue2")}      # 项目自带的那份“谁有六星 / 专武 1 / 专武 2”
        self.entries: list[dict[str, Any]] = []       # {"names": {全名: 分量}, "fps": [黎明界里见过的头像], "wfps": [资料站的头像], "role":…, "attr":…}
        # 「读角色」看到的：{"texts": {横条上读到的字: 次数}, "bases": {当时对上的本名: 次数}, "fp", "role", "attr", "name": 定下来的全名或 None, "via": 怎么定的}
        # 存的是读到的字本身：名单更新以后（新角色、我抄漏的名字）重新对一遍就行，不用再去游戏里读
        self.sightings: list[dict[str, Any]] = []
        self.roster: dict[str, dict[str, Any]] = {}   # 「读角色」里全名已经定下来的：全名 → {职能, 属性}（从 sightings 算出来的，不单独存）
        self.loose: set[str] = set()                  # 「读角色」里只读到本名、还分不出是哪个版本的那些本名（这些本名的角色有没有，说不准）
        self.unread_n = 0                             # 「读角色」里名字没读出来、头像也认不出的有几张
        self.scan: dict[str, Any] = {}                # 上一次「读角色」读完了没有：{"done": 读完一圈了吗, "count": 读了几个}；老的库里没有这一条（当成读完了）
        self.stats: dict[str, dict[str, float]] = {}  # 名字 → {"n": 普通战场数, "sec": 总秒数, "win":…, "lose":…}
        self.error = ""
        self.reset_note = ""                          # 读到了旧格式的库、清掉重来时，这里写一句话（给界面上说一声）
        self._bases: tuple[int, dict[str, list[str]]] = (-1, {})
        self._load()

    # ---- 存取 ----
    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            if d.get("version") != VERSION:           # 旧格式：里面的名字靠不住（本名当全名、几个版本混在一起、有读错的），留个备份，清掉重来
                n = len(d.get("portraits", []))
                try:
                    shutil.copyfile(self.path, self.path.with_name(self.path.stem + ".old.json"))
                except OSError:
                    pass
                self.reset_note = f"头像库是旧格式（里面 {n} 条的名字靠不住：横条上只有本名、不带版本），已经清空重来，旧的留了一份备份。"
                return
            for e in d.get("portraits", []):
                fps = [f for f in (_dec(x) for x in e.get("fps", [])) if f is not None]
                wfps = [f for f in (_dec(x) for x in e.get("wfps", [])) if f is not None]
                if (fps or wfps) and e.get("names"):
                    self.entries.append({"names": {str(k): int(v) for k, v in e["names"].items()}, "fps": fps, "wfps": wfps,
                                         "role": e.get("role"), "attr": e.get("attr")})
            for g in d.get("sightings", []):
                fp = _dec(g.get("fp", ""))
                if fp is not None:
                    self.sightings.append({"bases": {str(k): int(v) for k, v in (g.get("bases") or {}).items()},
                                           "texts": {str(k): int(v) for k, v in (g.get("texts") or {}).items()}, "fp": fp,
                                           "role": g.get("role"), "attr": g.get("attr"), "name": None, "via": ""})
            self.stats = {str(k): dict(v) for k, v in (d.get("stats") or {}).items()}
            self.scan = dict(d.get("scan") or {}) if isinstance(d.get("scan"), dict) else {}
            self.resolve_sightings()
        except Exception as e:  # noqa: BLE001  库坏了就当空的重新学，不让流程停下
            self.error = f"{type(e).__name__}: {e}"
            self.entries, self.sightings, self.stats, self.roster = [], [], {}, {}

    def save(self) -> bool:
        if not self.path:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            d = {"about": "工具自己记的角色头像库。portraits：全名 → 头像（fps 是黎明界里见过的，wfps 是从资料站的头像算出来的）；"
                          "sightings：「读角色」在角色页看到的头像和横条上的本名（name 是按名单和头像定下来的全名，每次都重新算，只是写出来方便看）。"
                          "可以整个删掉，会重新学。",
                 "version": VERSION,
                 "portraits": [{"name": self.name_of(e), "names": e["names"], "role": e.get("role"), "attr": e.get("attr"),
                                "fps": [_enc(f) for f in e["fps"]], "wfps": [_enc(f) for f in e.get("wfps", [])]} for e in self.entries],
                 "sightings": [{"base": self.base_of_sighting(g), "name": g.get("name"), "via": g.get("via", ""), "bases": g["bases"],
                                "texts": g.get("texts", {}), "role": g.get("role"), "attr": g.get("attr"), "fp": _enc(g["fp"])}
                               for g in self.sightings],
                 "stats": self.stats, "scan": self.scan}
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
            return True
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
            return False

    # ---- 正式名单 ----
    def bases(self) -> dict[str, list[str]]:
        """本名 → 名单里叫这个本名的所有全名（“凯露” → 凯露、凯露（夏日）、凯露（新年）……）。"""
        if self._bases[0] != len(self.known_names):
            out: dict[str, list[str]] = {}
            for n in self.known_names:
                out.setdefault(base_of(norm_text(n)), []).append(n)
            self._bases = (len(self.known_names), {k: sorted(v) for k, v in out.items()})
        return self._bases[1]

    def match_base(self, text: str) -> str:
        """「角色强化」页横条上读到的字 → 名单里的本名；对不上返回空串（当作没读出来，等头像去认）。
        三个字以上的名字允许错一个字；一两个字的名字错一个就是另一个人了，不猜。"""
        t = norm_text(text)
        bases = self.bases()
        if not t:
            return ""
        if t in bases:
            return t
        core = re.sub(rf"^[^{_CH}]+|[^{_CH}]+$", "", t)                   # 两头带进了边框之类的符号
        if core in bases:
            return core
        if self.ocr_fix.get(core) in bases:                               # OCR 每次都读错的那几个字
            return self.ocr_fix[core]
        near = [b for b in bases if len(b) == len(core) >= 3 and sum(x != y for x, y in zip(b, core)) == 1]
        return near[0] if len(near) == 1 else ""

    def read_base(self, img: np.ndarray, box: tuple[int, int, int, int], prefer: str | None = None) -> dict[str, Any]:
        """读「角色强化」页横条上的名字（本名）。几种读法轮着试，读到名单里有的本名就停。
        返回 {"base": 本名或空串, "how": 哪种读法读对的, "raw": [“读法:读到的字”…]}。"""
        from . import ocr

        out: dict[str, Any] = {"base": "", "how": "", "raw": [], "text": ""}
        for how, text in ocr.label_reads(img, box, ink="white", prefer=prefer):
            out["raw"].append(f"{how}:{text}")
            b = self.match_base(text)
            if b:
                out.update(base=b, how=how, text=norm_text(text))
                break
            if how.startswith("单行") and not out["text"] and clean_name(text):     # 名单里没有：把读到的字留着，名单更新以后再对
                out["text"] = norm_text(text)
        return out

    # ---- 「读角色」看到的头像 ----
    def base_of_sighting(self, g: dict[str, Any]) -> str:
        """这张头像的本名：拿存着的“横条上读到的字”去对现在的名单（读到次数多的先对）；没存字的老记录用当时对上的本名。"""
        for text, _n in sorted((g.get("texts") or {}).items(), key=lambda kv: -kv[1]):
            b = self.match_base(text)
            if b:
                return b
        return max(g["bases"].items(), key=lambda kv: kv[1])[0] if g.get("bases") else ""

    def add_sighting(self, base: str, fp: np.ndarray | None, role: str | None, attr: str | None, text: str = "") -> str:
        """记一张在角色页看到的头像。返回 new（第一次见）/ known（见过）/ skip。
        base 是空串 = 名字没对上名单，头像照记；text 是横条上读到的字（对没对上都存着）。"""
        if fp is None:
            return "skip"
        g = next((x for x in self.sightings if _sim(fp, x["fp"]) >= SAME_SIGHT), None)
        how = "known"
        if g is None:
            g = {"bases": {}, "texts": {}, "fp": fp, "role": role, "attr": attr, "name": None, "via": ""}
            self.sightings.append(g)
            how = "new"
        if base:
            g["bases"][base] = g["bases"].get(base, 0) + 1
        if text:
            g.setdefault("texts", {})[text] = g.setdefault("texts", {}).get(text, 0) + 1
        g["role"], g["attr"] = role or g.get("role"), attr or g.get("attr")
        self._resolve_one(g)
        return how

    def seen_of(self, base: str) -> int:
        """这个本名在角色页上看到了几张不同的头像（= 账号里有它的几个版本）。"""
        return sum(1 for x in self.sightings if self.base_of_sighting(x) == base) if base else 0

    def _wiki_best(self, fp: np.ndarray, names: set[str] | None = None) -> tuple[str | None, float, float]:
        """资料站的头像里（给了 names 就只在这些名字里）最像的：名字、相似度、第二像的相似度。"""
        best_n, best, second = None, 0.0, 0.0
        for e in self.entries:
            if not e.get("wfps"):
                continue
            n = self.name_of(e)
            if names is not None and n not in names:
                continue
            v = max(_sim(fp, f) for f in e["wfps"])
            if v > best:
                best_n, best, second = n, v, best
            elif v > second:
                second = v
        return best_n, best, second

    def _resolve_one(self, g: dict[str, Any]) -> None:
        """这张头像的全名定不定得下来。先按属性把同一个本名的几个版本筛一遍（资料站上有每个版本的属性，角色页上读到的属性很准），然后依次：
        黎明界里见过同一张头像（带全名）→ 资料站的头像里、剩下几个版本中最像的 → 资料站所有头像里明显最像的（横条上的字读错 / 没读出来时）
        → 剩下的版本只有一个、角色页上这个本名（这个属性）也只看到一张。都不行就是 None。
        （名单里只有一个版本、角色页上却看到两张不同的头像：说明名单不全，哪张是哪个版本定不了。2026-11-17 真机上银莲、厄里斯等五个就是这样。）"""
        base = self.base_of_sighting(g)
        fp, attr = g["fp"], g.get("attr")
        name, via = None, ""
        seen = [(max(_sim(fp, f) for f in e["fps"]), self.name_of(e)) for e in self.entries if e["fps"]]
        top = max(seen, default=(0.0, None))
        cands = self.bases().get(base, []) if base else []
        by_attr = bool(attr) and bool(cands) and all(c in self.attrs for c in cands)
        if by_attr and any(self.attrs[c] == attr for c in cands):
            cands = [c for c in cands if self.attrs[c] == attr]
        else:
            by_attr = False
        if top[0] >= SAME:
            name, via = top[1], "seen"
        score = 0.0
        if name is None and cands:
            n, v, second = self._wiki_best(fp, set(cands))
            score = v
            # 只在同一个本名（同一个属性）的几个版本里挑：够像、并且比第二像的明显高就行（不同版本是不同的画，差得很开）
            if n and (len(cands) == 1 and v >= 0.78 or v >= SAME and v - second >= 0.03 or v >= 0.78 and v - second >= 0.10):
                name, via = n, "icon"
        if name is None:
            n, v, second = self._wiki_best(fp)
            if n and v >= FACE_SURE and v - second >= 0.05 and (not attr or self.attrs.get(n, attr) == attr):
                name, via = n, ("icon" if base and base_of(n) == base else "face")
        if name is None and len(cands) == 1:
            crowd = sum(1 for x in self.sightings if self.base_of_sighting(x) == base and (not by_attr or x.get("attr") == attr))
            if crowd <= 1:
                name, via = cands[0], ("attr" if by_attr and len(self.bases().get(base, [])) > 1 else "only")
        g["name"], g["via"], g["score"] = name, via, round(score, 3)

    def resolve_sightings(self) -> dict[str, Any]:
        """把「读角色」看到的每张头像的全名重新定一遍（名单更新了、资料站的头像对上了以后都要重算）。
        返回 {"total", "named", "split"（本名读到了、但有几个版本还分不出来）, "unread"（名字没读出来、头像也还认不出）, "fixed": [(横条上读的, 按头像认的)]}。"""
        self.roster, self.loose, self.unread_n = {}, set(), 0
        out: dict[str, Any] = {"total": len(self.sightings), "named": 0, "split": 0, "unread": 0, "fixed": [], "via": {}}
        count: dict[str, int] = {}
        for g in self.sightings:
            b = self.base_of_sighting(g)
            count[b] = count.get(b, 0) + 1
        out["short"] = sorted(b for b, n in count.items() if b and n > len(self.bases().get(b, [])))     # 看到的版本比名单里的多：名单不全
        for g in self.sightings:
            base = self.base_of_sighting(g)
            self._resolve_one(g)
            out["via"][g["via"] or "none"] = out["via"].get(g["via"] or "none", 0) + 1
            if g["name"]:
                out["named"] += 1
                self.roster[g["name"]] = {"role": g.get("role"), "attr": g.get("attr")}
                if g["via"] == "face" and base:
                    out["fixed"].append((base, g["name"]))
            elif base:
                out["split"] += 1
                self.loose.add(base)
            else:
                out["unread"] += 1
        self.unread_n = out["unread"]
        return out

    # ---- 学、认 ----
    @staticmethod
    def name_of(e: dict[str, Any]) -> str:
        return max(e["names"].items(), key=lambda kv: kv[1])[0]

    @staticmethod
    def _all(e: dict[str, Any]) -> list[np.ndarray]:
        return e["fps"] + e.get("wfps", [])

    def _match(self, fp: np.ndarray | None) -> tuple[dict[str, Any] | None, float]:
        best: tuple[dict[str, Any] | None, float] = (None, 0.0)
        if fp is None:
            return best
        for e in self.entries:
            s = max(_sim(fp, f) for f in self._all(e))
            if s > best[1]:
                best = (e, s)
        return best

    def identify(self, fp: np.ndarray | None, role: str | None = None, attr: str | None = None) -> tuple[str | None, float]:
        """这张头像是谁（全名）。给了职能 / 属性时再核对一遍：和记的对不上就当不认识（宁可不认，不要认错）。
        「读角色」在角色页上见过这张头像时以它为准（那是游戏里的原图）：它的全名还没定下来（几个版本分不出），就当不认识。"""
        if fp is None:
            return None, 0.0
        e, s = self._match(fp)
        name, r0, a0 = (self.name_of(e), e.get("role"), e.get("attr")) if e is not None else (None, None, None)
        g = max(self.sightings, key=lambda x: _sim(fp, x["fp"]), default=None)
        if g is not None and _sim(fp, g["fp"]) >= SAME_SIGHT:
            s = _sim(fp, g["fp"])
            if not g.get("name"):
                return None, s
            name, r0, a0 = g["name"], g.get("role"), g.get("attr")
        if name is None or s < SAME:
            return None, s
        if (role and r0 and role != r0) or (attr and a0 and attr != a0):
            return None, s
        return name, s

    def learn(self, name: str, fp: np.ndarray | None, role: str | None = None, attr: str | None = None,
              weight: int = 1, canon: bool = True) -> str:
        """记一条“全名 + 头像”（黎明界的「角色加入」、招募页读来的）。返回 new / known / fixed（同一张头像以前读成了别的名字）/ skip。
        同一张头像读到过不同的名字时，分量加起来多的赢（资料站的名字分量重）。"""
        name = clean_name(name)
        name = self.canon(name) if canon else name
        if not name or fp is None:
            return "skip"
        key = "fps" if weight == 1 else "wfps"
        e, s = self._match(fp)
        if e is None or s < SAME:
            e = next((x for x in self.entries if self.name_of(x) == name), None)     # 名字认识、头像是新的（比如换成了另一种星级的头像）
            if e is None:
                self.entries.append({"names": {name: weight}, "fps": [], "wfps": [], "role": role, "attr": attr, key: [fp]})
                return "new"
            before, s = name, 0.0
        else:
            before = self.name_of(e)
        e["names"][name] = e["names"].get(name, 0) + weight
        lst = e.setdefault(key, [])
        if (not lst or max(_sim(fp, f) for f in lst) < 0.97) and len(lst) < MAX_FPS:
            lst.append(fp)
        e["role"], e["attr"] = role or e.get("role"), attr or e.get("attr")
        return "known" if self.name_of(e) == before else "fixed"

    def set_wiki(self, name: str, fps: list[np.ndarray]) -> bool:
        """资料站上这个全名的几张头像（已经按校准换算成指纹）。按名字放，不按头像合并——两个角色的头像再像也是两个人。
        返回 True = 库里原来没有这个名字。"""
        e = next((x for x in self.entries if self.name_of(x) == name), None)
        if e is None:
            self.entries.append({"names": {name: 5}, "fps": [], "wfps": list(fps), "role": None, "attr": None})
            return True
        e["names"][name] = max(e["names"].get(name, 0), 5)
        e["wfps"] = list(fps)
        return False

    def clear_wiki(self) -> None:
        """把从资料站算出来的头像都清掉（重新校准以后要重算）。只在资料站见过、黎明界里没见过的条目整条删掉。"""
        for e in self.entries:
            e["wfps"] = []
        self.entries = [e for e in self.entries if e["fps"]]

    def names(self) -> list[str]:
        """现在认得出的全名：黎明界里见过的、资料站头像对上的、「读角色」里全名定下来的。"""
        return sorted({self.name_of(e) for e in self.entries} | {g["name"] for g in self.sightings if g.get("name")})

    def canon(self, name: str) -> str:
        """OCR 偶尔会错一个字：如果正式名单里正好有一个只差一个字的，就按那个算。没有相近的、或者相近的不止一个，就原样返回。"""
        pool = self.known_names
        if not name or name in pool or not pool:
            return name
        same_len = [n for n in pool if len(n) == len(name) >= 3 and sum(a != b for a, b in zip(n, name)) == 1]
        if len(same_len) == 1:
            return same_len[0]
        if len(name) < 4:
            return name
        close = difflib.get_close_matches(name, sorted(pool), n=2, cutoff=0.84)
        return close[0] if len(close) == 1 else name

    def best_name(self, text: str) -> tuple[str, bool]:
        """OCR 读到的一串字（全名，可能带版本）→（名字，有没有把握）。有把握 = 这个名字在正式名单里。

        整串就是名单里的名字最好；不是的话，看是不是名单里的名字两头带进了符号（边框、花纹）；
        都不是，就把最像名字的那一段拿出来，算没把握。注意不能“里面包着一个名单里的名字就认”：
        “凯露（夏日）”里包着“凯露”，“未奏希＆美美＆镜华”里包着“未奏希”，那样会把人认错。
        """
        pool = self.known_names
        name = self.canon(find_name(text))
        if name and name in pool:
            return name, True
        fixed = self.ocr_fix.get(base_of(name), "") + name[len(base_of(name)):] if name and base_of(name) in self.ocr_fix else ""
        if fixed in pool:                                                 # OCR 每次都读错的那几个字（“珀（插班生）” → “碧（插班生）”）
            return fixed, True
        t = norm_text(text)
        inside = [n for n in pool if len(n) >= 2 and n in t and not re.search(rf"[{_CH}（）]", t.replace(n, "", 1))]
        if inside:
            return max(inside, key=len), True
        return name, False

    def read_name(self, img: np.ndarray, box: tuple[int, int, int, int], ink: str | None = "white", lines: int = 1,
                  prefer: str | None = None) -> dict[str, Any]:
        """读画面上某一块里的角色全名（黎明界的「角色加入」、招募页）。几种读法轮着试，读到名单里有的名字就停。

        返回 {"name": 名字或空串, "sure": 名单里有, "how": 哪种读法读对的, "raw": [“读法:读到的字”…], "guess": 名单里没有、但看着像名字的字}。
        名单里没有的不算读出来（name 是空串）：OCR 会把“碧”读成“珀”，而且几种读法会错得一模一样，分不出是新角色还是读错了。
        """
        from . import ocr

        out: dict[str, Any] = {"name": "", "sure": False, "how": "", "raw": [], "guess": ""}
        for how, text in ocr.label_reads(img, box, ink=ink, lines=lines, prefer=prefer):
            out["raw"].append(f"{how}:{text}")
            cand, sure = self.best_name(text)
            if cand and sure:
                out.update(name=cand, sure=True, how=how)
                return out
            out["guess"] = out["guess"] or clean_name(text)
        return out

    def refine(self, name: str, fp: np.ndarray | None, score: float) -> None:
        """名单里认出了这个人、但相似度不算很高（头像大小不同会差一点）：把这张卡的指纹也记下，下次就对得更稳。"""
        if fp is None or score >= 0.97:
            return
        e = next((x for x in self.entries if self.name_of(x) == name), None)
        if e is not None and len(e["fps"]) < MAX_FPS and (not e["fps"] or max(_sim(fp, f) for f in e["fps"]) < 0.97):
            e["fps"].append(fp)

    # ---- 角色特点 ----
    def tags(self, name: str | None) -> frozenset[str]:
        """这个角色的特点：只看按攻略整理的表（data/characters.json）。表里没有就是空的。"""
        info = self.table.get(name or "")
        return (frozenset(info.get("tags", [])) if isinstance(info, dict) else frozenset()) | self.more_tags.get(name or "", frozenset())

    def knows(self, name: str | None) -> bool:
        return bool(name) and name in self.table

    def atk(self, name: str | None) -> str | None:
        """这个角色是物理（"phys"）还是魔法（"magic"）；不认识返回 None。"""
        return self.atks.get(name or "")

    def pos(self, name: str | None) -> int | None:
        """这个角色的站位（数越小越靠前）；不认识返回 None。"""
        return self.poss.get(name or "")

    def aid(self, name: str | None) -> str | None:
        """这个角色的增益 / 支援是给哪边的："phys" / "magic" / "both"；简介里没说返回 None。"""
        return self.aids.get(name or "")

    def role_as(self, name: str | None) -> str | None:
        """游戏给这个角色标的职能不合用时，实际按哪种职能用（比如标着治疗、其实是强力增益的）；没有改写返回 None。"""
        return self.roles_as.get(name or "")

    def power(self, name: str | None) -> float:
        """这个角色的强度（数字越大越强，没有上限）：强度表里的数 + 「更新角色」发现的新专武 / 六星加的档数。不认识的是 1。"""
        if not name:
            return 1
        p = max(1.0, float(self.powers.get(name, 1)) + float(self.bumps.get(name, 0)))
        k = (getattr(self, "rates", None) or {}).get(name)      # 真机伤害校出来的“输出比重”（只有输出角色有，见 damage.py）
        return max(1.0, round(p * DM.power_factor(k), 2)) if k else p

    def hit(self, name: str | None) -> str | None:
        """这个角色擅长打一群（"aoe"）还是打一个（"single"），两样都行是 "both"；没有资料返回 None。"""
        return self.hits.get(name or "")

    def heal(self, name: str | None) -> float:
        """这个角色会不会给队友回血：≥1 = 有几个技能能给全队回，0.5 = 只能回一个人，0 = 不会 / 没有资料。"""
        return float(self.heals.get(name or "", 0.0))

    def is_pvp(self, name: str | None) -> bool:
        """是不是纯竞技场用的角色（攻略站：竞技场评价很高、打怪的两项评价都低）。"""
        return bool(name) and name in self.pvp

    def tough(self, name: str | None) -> float:
        """这个角色有多耐打：按资料站的生命值、物防、魔防算，一般坦克 = 1；没有资料是 0。"""
        return float(self.toughs.get(name or "", 0.0))

    def tough_vs(self, name: str | None, kind: str) -> float | None:
        """只算挨某一种伤害（kind = "phys" / "magic"）时有多耐打，一般坦克 = 1；没有分开的资料返回 None（那就用总的 tough）。"""
        return (self.toughs_p if kind == "phys" else self.toughs_m).get(name or "")

    def owned(self) -> set[str]:
        """账号里有哪些角色（全名）：「读角色」读到并且定下了全名的。没读过（或者读到的太少，不像是读完了）返回空集——那就不知道。"""
        names = set(self.roster)
        return names if len(names) >= 30 else set()

    def owns(self, name: str | None) -> bool | None:
        """这个角色玩家自己有没有（黎明界里没有的角色也能借来用，但练度低——2026-11-27 用户定的：编队最优先上玩家自己有的）。
        True = 有（「读角色」读到过）；False = 没有；None = 说不准：名字没认出来、没读过角色（或者上一次没读完）、
        这个本名在角色页上还有头像没分出是哪个版本、或者有好几张头像的名字根本没读出来。说不准的一律当成有。"""
        if not name:
            return None
        own = self.owned()
        if not own or self.scan.get("done") is False:
            return None
        if name in own:
            return True
        if base_of(name) in self.loose or self.unread_n > UNREAD_OK:
            return None
        return False

    # ---- 战绩 ----
    def record_battle(self, team: list[str], kind: str, seconds: float | None, win: bool) -> None:
        for name in team:
            st = self.stats.setdefault(name, {"n": 0, "sec": 0.0, "win": 0, "lose": 0})
            st["win" if win else "lose"] = st.get("win" if win else "lose", 0) + 1
            if win and kind == "normal" and seconds is not None and 1.0 <= seconds <= 120.0:
                st["n"] = st.get("n", 0) + 1
                st["sec"] = round(st.get("sec", 0.0) + float(seconds), 1)


def load_table(data_dir: Path) -> dict[str, Any]:
    try:
        d = json.loads((Path(data_dir) / "characters.json").read_text(encoding="utf-8"))
        return d if isinstance(d.get("chars"), dict) else {"chars": {}}
    except Exception:  # noqa: BLE001
        return {"chars": {}}
