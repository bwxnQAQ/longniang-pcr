"""更新角色：去资料站找国服现在有哪些角色，把全名、属性和头像加进头像库。

资料站（2026-11-17 用户定的；B 站 WIKI 的角色图鉴已经不更新了——停在 287 个角色，国服实际 320 个）：
  pcr.satroki.tech      「公主连结 Box」工具站，跟着国服的数据更新。读它公开的两个接口：
                        /api/Unit/GetUnitDatas?s=cn       每个角色的编号（unitId）、全名（带“（夏日）”这种版本）、物理还是魔法（atkType）
                        /api/Unit/GetUnitServerInfo?s=cn  哪些角色有 6 星、每个角色的属性（talentDict：1 火 2 水 3 风 4 光 5 暗）
                        /api/Unit/GetUnitSourceData/<编号>  一个角色的属性：也只给新角色读，算“耐打程度”（没有坦克时找肉的前排用）
                        /api/Unit/GetUnitInfo/<编号>?s=cn  一个角色的详情（技能说明）：只给项目自带的表里没有的新角色读，
                                                          按技能说明标“打一群 / 打一个、会不会回血、持续伤害、降攻”（规则在 skills.py）
                        头像：/icon/unit/<编号>.webp（128×128）
  redive.estertion.win  头像的备用来源（同一套编号：/icon/unit/<编号>.webp）；satroki 上哪张没下下来就到这里下，另外抽几张两边对一下。
                        它的国服数据库（db/redive_cn.db.br）停在 2025-09，名单不从它读。
  新角色的消息看国服官号 space.bilibili.com/353840826——工具不去读它，只在界面上放了个链接，由用户自己看。
文件名还叫 wiki.py、名单文件还叫 wiki.json，是沿用下来的名字。

头像的编号：角色编号去掉末两位，接上“星级 + 1”——11（★2 之前）、31（★3 之后）、61（★6 之后，只有开了 6 星的角色有），
正好是游戏里「显示切换」的三种，所以换过头像的角色三种样子都认得出。

资料站上的头像是原图，游戏里的卡片外面多一圈边框。差多少不靠猜：拿「读角色」看到的、是谁已经确定的头像
和资料站上同一个角色的头像对一遍，找出对得最准的缩放和偏移（calibrate）；对得上才把资料站的头像记进库，对不上就不记。
（2026-11-17 真机：缩放 1.0、偏移 0，相似度 0.99——原图原样垫在边框下面。）

这是工具里唯一会上网的地方：只读上面两个公开的资料站，不碰游戏服务器。
"""
from __future__ import annotations

import http.client
import json
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from . import chars as CH
from . import skills as SK
from .vision import cards as CD

UNITS_URL = "https://pcr.satroki.tech/api/Unit/GetUnitDatas?s=cn"
SKILL_URL = "https://pcr.satroki.tech/api/Unit/GetUnitInfo/{uid}?s=cn&withNo=True"    # 一个角色的详情：里面有每个技能的中文说明（unitSkillModel）
STATS_URL = "https://pcr.satroki.tech/api/Unit/GetUnitSourceData/{uid}"            # 一个角色的属性（各星级的基础值和成长、各 Rank 的加成）
TANK_EHP = 4905100.0                                   # 一般坦克的“有效生命”：2026-11-19 算的，职能是坦克的 36 个角色的中位数（见 tools/dev/scratch/mktough.py）
TANK_EHP_PHYS = 5067100.0                              # 只挨物理伤害时一般坦克的有效生命（生命值 ×（1 + 物防 ÷ 100））：2026-11-19 晚算的，耐打程度 0.8 以上的 32 个角色的中位数
TANK_EHP_MAGIC = 4990000.0                             # 只挨魔法伤害时的（生命值 ×（1 + 魔防 ÷ 100））
REF_LEVELS = 361 + 39                                  # 算属性时用的 等级 + Rank（2026-11-19 国服的上限；只用来比谁更肉，以后上限涨了也不改它，免得新老角色不可比）
REF_RANK = 39
MAX_SKILL_READS = 60                                   # 一次更新最多去读这么多个新角色的技能说明（平时一次就几个；多了说明哪里不对）
INFO_URL = "https://pcr.satroki.tech/api/Unit/GetUnitServerInfo?s=cn"
ICON_URLS = ("https://pcr.satroki.tech/icon/unit/{uid}.webp", "https://redive.estertion.win/icon/unit/{uid}.webp")
SITE_CN = ("satroki", "estertion")
OFFICIAL = "https://space.bilibili.com/353840826"          # 国服官号：新角色的消息在这（工具不读，只给个链接）
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
STAR_CN = {"1": "★2之前", "3": "★3之后", "6": "★6之后"}
ATTR = {1: "fire", 2: "water", 3: "wind", 4: "light", 5: "dark"}
ATK = {1: "phys", 2: "magic"}        # 名单接口里的 atkType：1 物理、2 魔法
GOOD = 0.86                  # 校准用的那些角色，资料站头像和游戏里头像的相似度中位数要到这个数才算对上（同一张图 ≥0.93，不同角色 ≤0.80；资料站的图是另外压过的，留一点余量）
MIN_PAIRS = 5                 # 至少要有这么多个“游戏里见过、是谁又确定”的角色才校准


_tls = threading.local()


def _headers(url: str) -> dict[str, str]:
    host = urllib.parse.urlsplit(url).netloc
    return {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9", "Referer": f"https://{host}/"}


def _fetch_plain(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers=_headers(url))
    with urllib.request.urlopen(req, timeout=timeout) as resp:      # noqa: S310  固定的 http(s) 地址
        return resp.read()


def _proxied(url: str) -> bool:
    """这台电脑设了系统代理没有（设了就老老实实走 urllib，它认代理；自己留连接的那条路不认）。"""
    try:
        u = urllib.parse.urlsplit(url)
        return bool(urllib.request.getproxies().get(u.scheme)) and not urllib.request.proxy_bypass(u.hostname or "")
    except Exception:  # noqa: BLE001
        return False


def fetch(url: str, timeout: float = 25.0) -> bytes:
    """读一个地址。同一个线程对同一个站的连接留着接着用——
    2026-11-18 真机：每张头像都重新连一次 pcr.satroki.tech，一张要 3 秒；连接留着用，后面的每张只是一来一回。"""
    if _proxied(url):
        return _fetch_plain(url, timeout)
    u = urllib.parse.urlsplit(url)
    conns: dict[tuple[str, str], http.client.HTTPConnection] = _tls.__dict__.setdefault("conns", {})
    key = (u.scheme, u.netloc)
    path = (u.path or "/") + ("?" + u.query if u.query else "")
    for attempt in (0, 1):
        conn = conns.get(key)
        fresh = conn is None
        if conn is None:
            cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
            conn = conns[key] = cls(u.netloc, timeout=timeout)
        try:
            conn.request("GET", path, headers=_headers(url))
            resp = conn.getresponse()
            data = resp.read()
        except (http.client.HTTPException, OSError):
            conn.close()
            conns.pop(key, None)
            if fresh or attempt:                # 新开的连接也不行：是真的连不上
                raise
            continue                            # 留着的连接被对方关了：重开一次再试
        if resp.status == 200:
            return data
        if resp.status in (301, 302, 303, 307, 308):
            return _fetch_plain(url, timeout)   # 跳转交给 urllib 去跟
        raise OSError(f"HTTP {resp.status}")
    raise OSError("连不上")                      # 走不到这


def icon_ids(unit_id: int, six: bool) -> list[str]:
    """这个角色的几张头像的编号：★2 之前、★3 之后，开了 6 星的再加 ★6 之后。"""
    short = int(unit_id) // 100
    return [f"{short}{star}1" for star in ("1", "3") + (("6",) if six else ())]


def parse_units(units_raw: bytes, info_raw: bytes | None = None) -> dict[str, dict[str, Any]]:
    """satroki 的两个接口 → {全名: {"id": 编号, "attr": 属性或 None, "icons": {头像编号: 地址}}}。读不懂返回 {}。"""
    try:
        units = json.loads(units_raw.decode("utf-8-sig"))
    except Exception:  # noqa: BLE001
        return {}
    six: set[int] = set()
    ue: dict[str, set[int] | None] = {"ue1": None, "ue2": None}      # 谁有专武 1 / 专武 2（None = 这次没读到，不拿它跟上次比）
    talent: dict[int, str] = {}
    if info_raw:
        try:
            info = json.loads(info_raw.decode("utf-8-sig"))
            six = {int(x) for x in info.get("rarity6Units") or []}
            for key, field in (("ue1", "uniqueEquipUnits"), ("ue2", "uniqueEquip2Units")):
                if isinstance(info.get(field), list):
                    ue[key] = {int(x) for x in info[field]}
            for k, ids in (info.get("talentDict") or {}).items():
                for short in ids or []:
                    if int(k) in ATTR:
                        talent[int(short)] = ATTR[int(k)]
        except Exception:  # noqa: BLE001  属性和 6 星读不出来：名单照用，只是少了这两样
            six, talent = set(), {}
    out: dict[str, dict[str, Any]] = {}
    for u in units if isinstance(units, list) else []:
        try:
            uid, name = int(u["unitId"]), CH.clean_name(str(u["unitName"]))
        except Exception:  # noqa: BLE001
            continue
        if not name or not (100000 <= uid < 200000):          # 1xxxxx 是可用角色；别的号段是敌人、召唤物
            continue
        out[name] = {"id": uid, "attr": talent.get(uid // 100), "atk": ATK.get(u.get("atkType")), "hit": CH.hit_of(str(u.get("comment") or "")),
                     "aid": CH.aid_of(str(u.get("comment") or "")),
                     "pos": u.get("searchAreaWidth") if isinstance(u.get("searchAreaWidth"), int) else None,
                     "icons": {i: ICON_URLS[0].format(uid=i) for i in icon_ids(uid, uid in six)}}
        if info_raw and (six or ue["ue1"] is not None):       # 六星 / 专武：读到了才写（没读到就不写，下次更新时不会被当成“没有”）
            out[name]["up"] = {"six": uid in six, **{k: uid in v for k, v in ue.items() if v is not None}}
    return out


UP_CN = {"six": "六星", "ue1": "专武 1", "ue2": "专武 2"}


def ehp(hp: float, pdef: float, mdef: float) -> float:
    """有效生命：生命值 ×（1 + 防御 ÷ 100），物理、魔法各算一个，取几何平均。"""
    return float(hp) * ((1 + float(pdef) / 100.0) * (1 + float(mdef) / 100.0)) ** 0.5


def read_tough(raw: bytes) -> float | None:
    """资料站一个角色的属性 → 耐打程度（一般坦克 = 1）。用五星的基础值 + 成长 × REF_LEVELS + Rank ≤ 39 的加成；读不懂返回 None。"""
    try:
        d = json.loads(raw.decode("utf-8-sig"))
        rar = max((r for r in d.get("unitRarities") or [] if int(r.get("rarity", 0)) <= 5), key=lambda r: int(r["rarity"]))
        ranks = [p for p in d.get("unitPromotionStatuses") or [] if int(p.get("promotionLevel", 0)) <= REF_RANK]
        pro = max(ranks, key=lambda p: int(p["promotionLevel"])) if ranks else {}

        def stat(k: str) -> float:
            return float(rar.get(k) or 0) + float(rar.get(k + "Growth") or 0) * REF_LEVELS + float(pro.get(k) or 0)

        return round(ehp(stat("hp"), stat("def"), stat("magicDef")) / TANK_EHP, 2)
    except Exception:  # noqa: BLE001
        return None


def read_traits(raw: bytes) -> dict[str, Any] | None:
    """资料站一个角色的详情 → 按技能说明标的特点（skills.unit_traits）。读不懂、里面没有技能说明返回 None。"""
    try:
        d = json.loads(raw.decode("utf-8-sig"))
        flat = SK.flatten(d.get("unitSkillModel"))
    except Exception:  # noqa: BLE001
        return None
    return SK.unit_traits(flat) if flat else None


def TRAIT_CN(t: dict[str, Any]) -> str:  # noqa: N802
    parts = [{"aoe": "打一群", "single": "打一个", "both": "一群和一个都行"}.get(t.get("hit") or "", "")]
    h = float(t.get("heal") or 0)
    parts.append("能给全队回血" if h >= 1 else "能给一名队友回血" if h > 0 else "")
    parts += [{"dot": "持续伤害", "patk_down": "降物攻", "matk_down": "降魔攻", "selfharm": "自损"}.get(x, x) for x in t.get("tags") or []]
    if float(t.get("tough") or 0) > 0:
        parts.append(f"耐打程度 {float(t['tough']):g}")
    return "、".join(p for p in parts if p) or "没有标出特点"


def upgrade_gain(table: dict[str, Any] | None, name: str, power: float, got: list[str]) -> tuple[float, str]:
    """新出了专武 / 六星，强度加多少——按攻略来，工具不自己判断（用户 2026-11-18 定的：有的角色出了专武依然没用）。
    table = data/characters.json 的 upgrade_table：日服攻略站给每把专武标的优先度（日服比国服快一年左右，国服要出的那边早就评过了），
    每一档写着 [加多少, 加完至少到多少]。返回（加多少, 攻略里是哪一档）；表里查不到的（包括六星：没有现成的优先度表）返回 (0, "")——不动，只列出来。
    一次更新里同时出了几样，取加完以后最高的那样。"""
    best, tier_cn = 0.0, ""
    for kind in got:
        tiers = (table or {}).get(kind) or {}
        tier = next((t for t, lst in tiers.items() if name in (lst or [])), None)
        if tier is None:
            continue
        gain, floor = (list(((table or {}).get("gain") or {}).get(kind, {}).get(tier) or [0, 0]) + [0, 0])[:2]
        new = max(power + float(gain), float(floor))
        if not tier_cn or new - power > best:
            best, tier_cn = max(0.0, new - power), f"{UP_CN[kind]}·攻略优先度{tier}"
    return round(best, 2), tier_cn


def find_upgrades(found: dict[str, dict[str, Any]], old_chars: dict[str, dict[str, Any]], baseline: dict[str, set[str]] | None = None,
                  known: set[str] | None = None) -> dict[str, list[str]]:
    """这次的名单比上一次多了哪些“六星 / 专武 1 / 专武 2”：{全名: ["ue2", …]}。
    上一次 = 上次「更新角色」存下来的（每个角色的 up）；那时候还没记这些（旧版本存的名单）就拿项目自带的那份比
    （baseline = data/characters.json 的 six / ue1 / ue2，known = 那份名单里有哪些角色）。
    上一次根本没有的新角色不算（她是新出的，不是“变强了”）。"""
    out: dict[str, list[str]] = {}
    for name, e in found.items():
        now = e.get("up")
        if not isinstance(now, dict):
            continue
        prev = (old_chars.get(name) or {}).get("up")
        if not isinstance(prev, dict):
            if baseline is None or name not in (known or set()):
                continue
            prev = {k: name in baseline.get(k, set()) for k in UP_CN}
        got = [k for k in ("six", "ue1", "ue2") if now.get(k) and k in prev and not prev.get(k)]
        if got:
            out[name] = got
    return out


def builtin_units(table: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """项目自带的名单（data/characters.json 的 ids / attrs / six）→ 和 parse_units 一样的格式。资料站的名单接口连不上时顶上。"""
    six = set(table.get("six") or [])
    attrs = table.get("attrs") or {}
    atks = table.get("atks") or {}
    out = {}
    for name, uid in (table.get("ids") or {}).items():
        try:
            out[name] = {"id": int(uid), "attr": attrs.get(name), "atk": atks.get(name), "hit": (table.get("hits") or {}).get(name), "aid": (table.get("aids") or {}).get(name),
                         "pos": (table.get("pos") or {}).get(name),
                         "icons": {i: ICON_URLS[0].format(uid=i) for i in icon_ids(int(uid), name in six)}}
        except (TypeError, ValueError):
            continue
    return out


def attach(book: CH.CharBook, learned_dir: Path) -> int:
    """把以前从资料站读来的名单和属性交给头像库。返回名单里有多少个角色。"""
    chars = load_index(Path(learned_dir) / "wiki.json")["chars"]
    book.known_names |= set(chars)
    book.attrs.update({n: e["attr"] for n, e in chars.items() if e.get("attr")})
    book.atks.update({n: e["atk"] for n, e in chars.items() if e.get("atk")})
    for n, e in chars.items():                       # 按简介标的“打一群 / 打一个”只用来补缺：项目自带的表是按技能说明标的，更细
        if e.get("hit") and n not in book.hits:
            book.hits[n] = e["hit"]
    for n, t in load_traits(Path(learned_dir) / "wiki.json").items():      # 新角色：「更新角色」按技能说明标的
        if n in book.builtin_names:
            continue
        if t.get("hit"):
            book.hits[n] = t["hit"]
        if float(t.get("heal") or 0) > 0:
            book.heals[n] = float(t["heal"])
        if t.get("tags"):
            book.more_tags[n] = frozenset(t["tags"])
        if float(t.get("tough") or 0) > 0:
            book.toughs[n] = float(t["tough"])
    book.aids.update({n: e["aid"] for n, e in chars.items() if e.get("aid")})
    book.poss.update({n: e["pos"] for n, e in chars.items() if e.get("pos")})
    book.bumps.update(load_bumps(Path(learned_dir) / "wiki.json"))
    book.resolve_sightings()
    return len(chars)


def load_traits(path: Path) -> dict[str, dict[str, Any]]:
    """「更新角色」按技能说明给角色标的特点：{全名: {"hit": …, "heal": …, "tags": […]}}（skills.unit_traits 的结果）。"""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return {str(n): dict(v) for n, v in (d.get("traits") or {}).items() if isinstance(v, dict)}
    except Exception:  # noqa: BLE001
        return {}


def load_bumps(path: Path) -> dict[str, float]:
    """「更新角色」记下的“谁新出了专武 / 六星，强度加几档”：{全名: 档数}。"""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return {str(n): float(v.get("n", 0)) for n, v in (d.get("bumps") or {}).items() if isinstance(v, dict) and float(v.get("n", 0)) > 0}
    except Exception:  # noqa: BLE001
        return {}


def load_index(path: Path) -> dict[str, Any]:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return d if isinstance(d.get("chars"), dict) else {"chars": {}}
    except Exception:  # noqa: BLE001
        return {"chars": {}}


def save_index(path: Path, index: dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def icon_file(icon_dir: Path, uid: str) -> Path | None:
    """这张头像下过没有（以前从 B 站 WIKI 下的是 .png，现在下的是 .webp，编号是同一套）。"""
    for ext in (".webp", ".png"):
        p = Path(icon_dir) / f"Icon_unit_{uid}{ext}"
        if p.exists():
            return p
    return None


def decode(data: bytes) -> np.ndarray | None:
    """图片文件的内容 → BGR 图。OpenCV 读不了（少见的 webp 写法）就让 Pillow 试一次。"""
    try:
        img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:  # noqa: BLE001
        img = None
    if img is None:
        try:
            import io

            from PIL import Image

            img = cv2.cvtColor(np.array(Image.open(io.BytesIO(data)).convert("RGB")), cv2.COLOR_RGB2BGR)
        except Exception:  # noqa: BLE001
            return None
    return img


def read_icon(path: Path | None) -> np.ndarray | None:
    """读一张头像文件，统一成 128×128 的 BGR 图。读不了返回 None。"""
    if path is None:
        return None
    try:
        img = decode(Path(path).read_bytes())
    except OSError:
        return None
    if img is None or min(img.shape[:2]) < 32:
        return None
    return cv2.resize(img, (128, 128), interpolation=cv2.INTER_AREA if img.shape[0] > 128 else cv2.INTER_CUBIC)


def download_icons(index: dict[str, Any], icon_dir: Path, say: Callable[[str], None], check: Callable[[], None],
                   get: Callable[[str], bytes] = fetch, pause: float = 0.05, workers: int = 4) -> tuple[int, int, dict[str, int]]:
    """把还没有的头像下到 icon_dir（文件名 Icon_unit_<编号>.webp）。两个站都能下（同一套编号）：先各试一张，哪个快先用哪个，
    下不下来再换另一个；几张一起下。返回（新下了几张，失败几张，{哪个站: 下了几张, "left": 没下的}）。"""
    icon_dir.mkdir(parents=True, exist_ok=True)
    todo = [(n, uid) for n, e in index["chars"].items() for uid in e.get("icons", {}) if icon_file(icon_dir, uid) is None]
    ok = bad = streak = 0
    by: dict[str, int] = {}
    order = list(range(len(ICON_URLS)))

    def grab(uid: str, si: int) -> bytes:
        data = get(ICON_URLS[si].format(uid=uid))
        if len(data) < 200 or decode(data) is None:
            raise ValueError("不是图片")
        return data

    def one(item: tuple[str, str]) -> tuple[str, str]:
        err = ""
        for si in order:
            try:
                (icon_dir / f"Icon_unit_{item[1]}.webp").write_bytes(grab(item[1], si))
                return SITE_CN[si], ""
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {str(e)[:80]}"
        return "", err

    def count(item: tuple[str, str], site: str, err: str) -> None:
        nonlocal ok, bad, streak
        if site:
            ok, streak = ok + 1, 0
            by[site] = by.get(site, 0) + 1
        else:
            bad, streak = bad + 1, streak + 1
            if bad <= 5:
                say(f"    ! {item[0]} 的头像 {item[1]} 两个站都没下下来：{err}")

    if todo:                                      # 第一张两个站各下一次，量一下哪个快
        check()
        took, first, first_site = [], b"", ""
        for si in order:
            t0 = time.perf_counter()
            try:
                data = grab(todo[0][1], si)
                took.append(time.perf_counter() - t0)
                if not first:
                    first, first_site = data, SITE_CN[si]
            except Exception:  # noqa: BLE001
                took.append(float("inf"))
        if first:
            (icon_dir / f"Icon_unit_{todo[0][1]}.webp").write_bytes(first)
        if took[1] < took[0] * 0.7 and took[0] - took[1] > 0.3:       # 备用站明显快：这次先从它下
            order = [1, 0]
            if took[0] != float("inf"):
                say(f"    两个站各试了一张：{SITE_CN[1]} 快（{took[1]:.1f} 秒，{SITE_CN[0]} {took[0]:.1f} 秒），这次先从它下。")
        count(todo[0], first_site, "两个站都没连上")
    last_say = time.time()
    with ThreadPoolExecutor(max(1, workers)) as pool:
        for i in range(1, len(todo), max(1, workers)):
            check()
            if streak >= 6:                       # 连着 6 张两个站都下不下来：多半是网不通，别一张张耗下去
                by["left"] = len(todo) - i
                say(f"    ! 连着 {streak} 张头像两个站都没下下来，先不下了（还剩 {by['left']} 张）。检查一下网络，下次再点会接着下。")
                break
            chunk = todo[i:i + max(1, workers)]
            for item, (site, err) in zip(chunk, pool.map(one, chunk)):
                count(item, site, err)
            done = min(len(todo), i + len(chunk))
            if done < len(todo) and (done // 50 > (i // 50) or time.time() - last_say > 8):
                say(f"    已经下了 {done} / {len(todo)} 张……")
                last_say = time.time()
            if pause:
                time.sleep(pause)
    return ok, bad, by


def cross_check(index: dict[str, Any], icon_dir: Path, get: Callable[[str], bytes] = fetch, n: int = 3) -> dict[str, Any]:
    """两个站互相对一下：抽几张已经有的头像，到 estertion 再下一遍，看是不是同一张图（编号是不是同一套）。只读不存。"""
    out: dict[str, Any] = {"checked": 0, "same": 0, "error": ""}
    uids = [uid for e in index["chars"].values() for uid in e.get("icons", {}) if uid.endswith("31")]
    for uid in uids[:: max(1, len(uids) // n)][:n]:
        mine = read_icon(icon_file(icon_dir, uid))
        if mine is None:
            continue
        try:
            other = decode(get(ICON_URLS[1].format(uid=uid)))
        except Exception as e:  # noqa: BLE001
            out["error"] = f"{type(e).__name__}: {str(e)[:80]}"
            break
        if other is None:
            continue
        other = cv2.resize(other, (128, 128), interpolation=cv2.INTER_AREA)
        out["checked"] += 1
        out["same"] += CD.same_card(CD.fingerprint(mine, 64, 64), CD.fingerprint(other, 64, 64)) >= 0.9
    return out


def icon_fp(icon: np.ndarray, s: float, dx: float = 0.0, dy: float = 0.0) -> np.ndarray | None:
    """资料站的原图头像 → 和游戏里的卡片可比的指纹。s = 游戏里的卡片相对原图缩了多少，dx / dy = 中心偏了多少（原图像素）。"""
    return CD.fingerprint(icon, 64.0 + dx, 64.0 + dy, 1.0 / s + 1e-9)


def _pairs(book: CH.CharBook, index: dict[str, Any], icon_dir: Path, limit: int = 40) -> list[tuple[list[np.ndarray], list[np.ndarray]]]:
    """拿来校准的“游戏里的头像 ↔ 资料站上同一个角色的头像”。游戏里的头像有两个来源：
    「读角色」看到的、本名在名单里只有一个版本的（斑比、古蕾雅……横条上只有本名，有几个版本的分不出是哪个，不能拿来对）；
    黎明界的「角色加入」读到全名的。"""
    def icons_of(name: str) -> list[np.ndarray]:
        info = index["chars"].get(name)
        if not info:
            return []
        return [im for im in (read_icon(icon_file(icon_dir, uid)) for uid in info["icons"]) if im is not None]

    out = []
    book.resolve_sightings()
    for g in book.sightings:
        if g.get("via") == "only":                  # 名单里只有一个版本、角色页上也只看到一张：这张头像是谁是确定的
            icons = icons_of(g["name"])
            if icons:
                out.append(([g["fp"]], icons))
    for e in book.entries:
        game = list(e["fps"])                       # 只拿在游戏画面上亲眼见过的头像来对
        icons = icons_of(book.name_of(e)) if game else []
        if icons:
            out.append((game, icons))
    return out[:limit]


def calibrate(pairs: list[tuple[list[np.ndarray], list[np.ndarray]]]) -> tuple[dict[str, float] | None, float]:
    """找出让“游戏里的头像”和“资料站上同名的头像”对得最准的缩放和偏移。返回（参数，对上的程度）；角色不够或者对不上返回 (None, 分数)。"""
    if len(pairs) < MIN_PAIRS:
        return None, 0.0

    def score(s: float, dx: float, dy: float, sub: list) -> float:
        vals = []
        for game, icons in sub:
            fps = [icon_fp(im, s, dx, dy) for im in icons]
            vals.append(max((CD.same_card(g, f) for g in game for f in fps), default=0.0))
        return float(np.median(vals))

    coarse = pairs[:12]
    best = (0.0, 1.0, 0.0, 0.0)
    for s in np.arange(0.84, 1.061, 0.02):                       # 先粗找缩放（偏移先当 0），再在附近细找
        v = score(float(s), 0.0, 0.0, coarse)
        if v > best[0]:
            best = (v, float(s), 0.0, 0.0)
    s0 = best[1]
    for s in (s0 - 0.01, s0, s0 + 0.01):
        for dx in (-2.0, -1.0, 0.0, 1.0, 2.0):
            for dy in (-2.0, -1.0, 0.0, 1.0, 2.0):
                v = score(s, dx, dy, coarse)
                if v > best[0]:
                    best = (v, s, dx, dy)
    final = score(best[1], best[2], best[3], pairs)
    params = {"s": round(best[1], 3), "dx": best[2], "dy": best[3]}
    return (params if final >= GOOD else None), final


def build(book: CH.CharBook, index: dict[str, Any], icon_dir: Path, params: dict[str, float]) -> tuple[int, int]:
    """按校准好的参数，把资料站上每个角色的三种头像都记进头像库。返回（记了几个角色，其中库里原来没有的几个）。"""
    done = new = 0
    book.clear_wiki()
    for name, info in index["chars"].items():
        fps = []
        for uid in sorted(info.get("icons", {})):
            im = read_icon(icon_file(icon_dir, uid))
            if im is not None:
                fp = icon_fp(im, params["s"], params["dx"], params["dy"])
                if fp is not None:
                    fps.append(fp)
        if not fps:
            continue
        new += book.set_wiki(name, fps)             # 按名字放，不按头像合并：资料站上的名字是准的
        done += 1
    return done, new


def update(book: CH.CharBook, learned_dir: Path, say: Callable[[str], None], check: Callable[[], None],
           get: Callable[[str], bytes] = fetch, save_raw: Path | None = None, min_entries: int = 50,
           fallback: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """一整套：读名单 → 找出新角色 → 下头像 → 校准 → 记进头像库 → 给「读角色」看到的头像定全名。任何一步不成都不会弄坏已有的库。
    fallback：资料站的名单没读到时用的名单（项目自带的那份，builtin_units）——头像照样能下，只是不知道有没有更新的角色。"""
    index_path, icon_dir = learned_dir / "wiki.json", learned_dir / "icons"
    old = load_index(index_path)
    res: dict[str, Any] = {"ok": False, "names": len(old["chars"]), "new_names": [], "gone_names": [], "icons_new": 0, "icons_failed": 0,
                           "icons_by": {}, "cross": None, "calibrated": False, "score": 0.0, "added": 0, "added_new": 0}
    say("  去资料站（pcr.satroki.tech）读国服的角色名单……")
    units_raw, info_raw, why = b"", None, ""
    try:
        units_raw = get(UNITS_URL)
    except Exception as e:  # noqa: BLE001
        why = f"{type(e).__name__}: {str(e)[:120]}"
    if units_raw:
        try:
            info_raw = get(INFO_URL)
        except Exception as e:  # noqa: BLE001
            say(f"  ! 属性和 6 星的信息没读到（{type(e).__name__}）：名单照用，这次不下 6 星头像、不按属性核对。")
    if save_raw is not None:
        try:
            save_raw.write_bytes(units_raw)
            if info_raw:
                save_raw.with_name(save_raw.stem + "_info" + save_raw.suffix).write_bytes(info_raw)
        except Exception:  # noqa: BLE001
            pass
    found = parse_units(units_raw, info_raw) if units_raw else {}
    if len(found) < min_entries:
        why = why or f"只认出 {len(found)} 个角色（接口的写法可能变了）"
        res["error"] = why
        if not fallback or len(fallback) < min_entries:
            say(f"  × 名单没读到：{why}。头像库没有动" + ("；读到的内容已存进这次的记录文件夹。" if units_raw else "。"))
            return res
        say(f"  ! 资料站的名单没读到（{why}）：这次先用项目自带的名单（{len(fallback)} 个角色），头像照下。有没有更新的角色这次看不出来；把记录文件夹告诉我。")
        found, res["used_builtin"] = dict(fallback), True
    res["new_names"] = sorted(n for n in found if n not in old["chars"])
    res["gone_names"] = sorted(n for n in old["chars"] if n not in found)
    # 这段时间谁新出了专武 1 / 专武 2 / 六星：强度往上加一档（用户 2026-11-18 定的：出了专武强度会上一个台阶，更新角色时要跟着改权重）
    bumps: dict[str, dict[str, Any]] = {str(n): dict(v) for n, v in (old.get("bumps") or {}).items() if isinstance(v, dict)}
    ups: dict[str, list[str]] = {}
    gains: dict[str, float] = {}
    tiers: dict[str, str] = {}
    if not res.get("used_builtin"):
        ups = find_upgrades(found, old["chars"], book.upgrades if any(book.upgrades.values()) else None, set(book.builtin_names))
        today = time.strftime("%Y-%m-%d")
        for name, got in ups.items():
            gain, tier = upgrade_gain(book.upgrade_table, name, book.power(name), got)      # 按攻略那张表来；表里没有的不加
            b = bumps.setdefault(name, {"n": 0, "log": []})
            b["n"] = round(float(b.get("n", 0)) + gain, 2)
            b.setdefault("log", []).append([today, got, gain, tier])
            gains[name], tiers[name] = gain, tier
        for name, e in found.items():                         # 旧版本存的名单里没有这些：这次没读到就把上次的带过来，免得下次比不了
            if "up" not in e and isinstance((old["chars"].get(name) or {}).get("up"), dict):
                e["up"] = old["chars"][name]["up"]
    res["upgrades"] = {n: {"got": [UP_CN[k] for k in got], "gain": gains.get(n, 0.0), "guide": tiers.get(n, "")} for n, got in ups.items()}
    # 新角色（项目自带的表里没有的）：读一下技能说明，标上“打一群 / 打一个、会不会给队友回血、持续伤害、降攻”，编队时就能用
    traits: dict[str, dict[str, Any]] = {str(n): dict(v) for n, v in (old.get("traits") or {}).items() if isinstance(v, dict) and n in found}
    todo = [n for n in found if n not in book.builtin_names and n not in traits] if not res.get("used_builtin") else []
    res["traits_new"], res["traits_failed"] = [], []
    for name in todo[:MAX_SKILL_READS]:
        check()
        try:
            t = read_traits(get(SKILL_URL.format(uid=found[name]["id"])))
        except Exception:  # noqa: BLE001  读不到不要紧：这个角色先按没有资料算，下次更新再试
            t = None
        if t is None:
            res["traits_failed"].append(name)
            continue
        try:                                         # 顺带读她的属性，算耐打程度（没有坦克时找肉的前排要用）；读不到就先不标
            tough = read_tough(get(STATS_URL.format(uid=found[name]["id"])))
        except Exception:  # noqa: BLE001
            tough = None
        if tough is not None:
            t["tough"] = tough
        traits[name] = t
        res["traits_new"].append(name)
    if res["traits_new"]:
        say("  新角色的技能说明读了 " + str(len(res["traits_new"])) + " 个：" + "、".join(
            f"{n}（{TRAIT_CN(traits[n])}）" for n in res["traits_new"][:12]) + ("……" if len(res["traits_new"]) > 12 else "") + "。")
    if res["traits_failed"]:
        say(f"  ! 有 {len(res['traits_failed'])} 个新角色的技能说明没读到（{'、'.join(res['traits_failed'][:8])}）：先按没有资料算，下次更新再试。")
    index = {"about": "从资料站 pcr.satroki.tech 读来的国服角色名单：全名、编号、属性、头像地址、有没有六星 / 专武（up）；"
                      "bumps 是每次更新时发现“谁新出了专武 / 六星”给她加的强度档数（更新角色功能写的，可以删，会重新读）。",
             "source": "builtin" if res.get("used_builtin") else "satroki", "updated": time.strftime("%Y-%m-%d %H:%M"),
             "params": old.get("params"), "chars": found, "bumps": bumps, "traits": traits}
    res["names"] = len(found)
    say(f"  国服现在有 {len(found)} 个角色" + (f"，其中 {len(res['new_names'])} 个是上次名单里没有的：{'、'.join(res['new_names'][:20])}"
                                       + ("……" if len(res["new_names"]) > 20 else "") if old["chars"] else "（第一次读）") + "。")
    if ups:
        what = lambda n: "、".join(UP_CN[k] for k in ups[n])                                   # noqa: E731
        up = [n for n in ups if gains.get(n, 0) > 0]
        same = [n for n in ups if gains.get(n, 0) <= 0 and tiers.get(n)]
        keep = [n for n in ups if not tiers.get(n)]
        say(f"  这段时间有 {len(ups)} 个角色新出了专武或六星。强度按攻略那张表（data/characters.json 的 upgrade_table）来：")
        if up:
            say("    加了的：" + "、".join(f"{n}（{tiers[n]}，{book.power(n):g} → {book.power(n) + gains[n]:g}）" for n in up[:30]) + ("……" if len(up) > 30 else "") + "。")
        if same:
            say("    攻略说用处不大、没加的：" + "、".join(f"{n}（{tiers[n]}）" for n in same[:30]) + ("……" if len(same) > 30 else "") + "。")
        if keep:
            say("    表里没有、先没动的（要查了攻略再定，告诉我一声）：" + "、".join(f"{n}（{what(n)}）" for n in keep[:30]) + ("……" if len(keep) > 30 else "") + "。")
    elif not res.get("used_builtin") and any("up" in e for e in found.values()):
        say("  专武和六星：和上一次比没有新出的，强度表不用动。")
    book.bumps.update({n: float(v.get("n", 0)) for n, v in bumps.items()})
    for n, t in traits.items():
        if n not in book.builtin_names:
            if t.get("hit"):
                book.hits[n] = t["hit"]
            if float(t.get("heal") or 0) > 0:
                book.heals[n] = float(t["heal"])
            if t.get("tags"):
                book.more_tags[n] = frozenset(t["tags"])
            if float(t.get("tough") or 0) > 0:
                book.toughs[n] = float(t["tough"])
    book.known_names |= set(found)
    book.attrs.update({n: e["attr"] for n, e in found.items() if e.get("attr")})
    book.atks.update({n: e["atk"] for n, e in found.items() if e.get("atk")})
    for n, e in found.items():                           # 按简介标的只补缺（见 attach）
        if e.get("hit") and n not in book.hits:
            book.hits[n] = e["hit"]
    book.aids.update({n: e["aid"] for n, e in found.items() if e.get("aid")})
    book.poss.update({n: e["pos"] for n, e in found.items() if e.get("pos")})
    save_index(index_path, index)
    n_icons = sum(len(e["icons"]) for e in found.values())
    have = sum(1 for e in found.values() for uid in e["icons"] if icon_file(icon_dir, uid) is not None)
    if have < n_icons:
        say(f"  下头像：一共 {n_icons} 张，已经有 {have} 张，要下 {n_icons - have} 张……")
        res["icons_new"], res["icons_failed"], res["icons_by"] = download_icons(index, icon_dir, say, check, get)
        if res["icons_by"].get("estertion"):
            say(f"    其中 {res['icons_by']['estertion']} 张是从备用的 redive.estertion.win 下的。")
    check()
    c = res["cross"] = cross_check(index, icon_dir, get)
    if c["checked"]:
        say(f"  两个资料站互相对了一下：抽了 {c['checked']} 张头像，{c['same']} 张是同一张图" + ("。" if c["same"] == c["checked"] else "——有对不上的，把记录文件夹告诉我。"))
    elif c["error"]:
        say("  备用的 redive.estertion.win 这次没连上（不影响：头像都从 pcr.satroki.tech 下好了）。")
    res.update(apply_icons(book, learned_dir, say))
    res["ok"] = True
    return res


def apply_icons(book: CH.CharBook, learned_dir: Path, say: Callable[[str], None]) -> dict[str, Any]:
    """用已经下好的头像：校准，记进头像库，再把「读角色」看到的每张头像是哪个版本定下来。读完角色（菜单 16）以后也会调一次。"""
    index_path, icon_dir = learned_dir / "wiki.json", learned_dir / "icons"
    index = load_index(index_path)
    out: dict[str, Any] = {"calibrated": False, "score": 0.0, "pairs": 0, "added": 0, "added_new": 0, "sight": None}
    if not index["chars"] or not icon_dir.exists():
        return out
    book.known_names |= set(index["chars"])
    book.attrs.update({n: e["attr"] for n, e in index["chars"].items() if e.get("attr")})
    book.atks.update({n: e["atk"] for n, e in index["chars"].items() if e.get("atk")})
    for n, e in index["chars"].items():
        if e.get("hit") and n not in book.hits:
            book.hits[n] = e["hit"]
    book.aids.update({n: e["aid"] for n, e in index["chars"].items() if e.get("aid")})
    book.poss.update({n: e["pos"] for n, e in index["chars"].items() if e.get("pos")})
    pairs = _pairs(book, index, icon_dir)
    out["pairs"] = len(pairs)
    params, score = calibrate(pairs)
    out["score"] = round(score, 3)
    if params is None and index.get("params") and len(pairs) < MIN_PAIRS:
        params = index["params"]                                    # 以前校准过，这次没有新的可对：沿用
    if params is None:
        out["sight"] = book.resolve_sightings()                     # 名单更新了：只有一个版本的本名现在能定下来
        book.save()
        if len(pairs) < MIN_PAIRS:
            say(f"  资料站的头像已经下好了，但还不能用：要先知道它和游戏里的头像差多少，这得有 {MIN_PAIRS} 个以上“在游戏里见过、名字又确定”的角色来对"
                f"（现在 {len(pairs)} 个）。先跑一次菜单 16「读角色」，再回来点这一项。")
        else:
            say(f"  ! 资料站的头像和游戏里的头像没对上（{len(pairs)} 个角色，相似度中位数 {score:.2f}，要到 {GOOD}）。"
                "这次没有把资料站的头像记进库——名单照常更新了。把这次的记录文件夹告诉我。")
        return out
    index["params"] = params
    save_index(index_path, index)
    out["calibrated"] = True
    out["added"], out["added_new"] = build(book, index, icon_dir, params)
    st = out["sight"] = book.resolve_sightings()                    # 「读角色」看到的头像：按资料站的头像定下是哪个版本
    scores = sorted(g.get("score", 0.0) for g in book.sightings if g.get("via") == "icon")
    if scores:
        out["icon_scores"] = {"min": scores[0], "p10": scores[len(scores) // 10], "median": scores[len(scores) // 2], "n": len(scores)}
    book.save()
    say(f"  资料站的头像和游戏里的对上了（用 {len(pairs)} 个角色对的，相似度 {score:.2f}；缩放 {params['s']}，偏移 {params['dx']:+.0f}, {params['dy']:+.0f}）。"
        f"已经把 {out['added']} 个角色的头像（每个最多三种）记进头像库。")
    if st["total"]:
        say(f"  「读角色」看到的 {st['total']} 张头像：{st['named']} 张定下了全名"
            + (f"，{st['split']} 张知道本名、但对不上是哪个版本" if st["split"] else "")
            + (f"，{st['unread']} 张名字没读出来、头像也没对上" if st["unread"] else "") + "。")
    if st["fixed"]:
        say("  其中横条上的字读错、按头像改过来的：" + "、".join(f"{a}→{b}" for a, b in st["fixed"][:20]) + "。")
    if st["split"] or st["unread"]:
        say("  没定下来的那些，在黎明界里先不按名字用（只看职能和属性）。把这次的记录文件夹告诉我。")
    return out
