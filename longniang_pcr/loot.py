"""战利品的账本（2026-11-24）：每打通一局拿到了什么、其中哪些是饰品；按饰品数量连续刷时离目标还差多少。

存在 data/learned/loot.json，跨局保留：
  runs    = 每一局 {t 时间, guild 公会, tier 档位, score 分数, items {名字: 数量}, read 读全了没有}
  session = 现在这一轮“连续刷”：{targets {关键字: 要几个}, got {关键字: 已经几个}, runs 打了几局, started 开始时间}
饰品 = 目录里的 50 件（accessories.py：十个公会各一个系列 × 五种属性，2026-11-24 晚照用户录的「可以获得的报酬」做的）。
以后出了目录里没有的新饰品，可以先在 config/settings.json 的 farm.accessory_words 里写它名字里的几个字顶着。
目标可以写到多细由 accessories.parse_filter 管：具体一件（火轮赞颂）、一个系列（赞颂 / 美食殿堂）、一个部位（轮）、一种属性（火）、
属性 + 部位（火轮）、随便哪件（饰品）；存进账本时一律换成标准写法。不认识的写法照老办法算——“名字里包含这几个字的东西”（刷材料时用得上）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import accessories as AC

ACCESSORY_WORDS: tuple[str, ...] = ()        # 目录以外、也当饰品算的名字关键字（设置里的 farm.accessory_words 加在这后面）
# 见过的、肯定不是饰品的东西（名字里包含这些字）：别的没见过的名字会单独列出来给你看
MATERIAL_WORDS = ("炼成点数", "迷宫币", "秘石", "星幽碎片", "星幽光球", "阿尔法", "令牌", "玛那", "宝石", "经验", "药剂", "碎片", "结晶", "硬币", "金币")
KEEP_RUNS = 500


def is_accessory(name: str, words: tuple[str, ...] | list[str] = ACCESSORY_WORDS) -> bool:
    return name in AC.BY_NAME or AC.is_accessory(name) or any(w and w in name for w in words)


def target_key(key: Any) -> str:
    """你写的目标 → 账本里用的标准写法。认得出是饰品的范围就换成标准写法（戒指 → 轮），认不出原样留着。"""
    flt = AC.parse_filter(key)
    return flt.key if flt is not None else str(key).strip()


def target_text(key: str) -> str:
    """一个目标给人看的说法。"""
    flt = AC.parse_filter(key)
    return flt.text() if flt is not None else f"名字里有「{key}」的东西"


def is_known(name: str, words: tuple[str, ...] | list[str] = ACCESSORY_WORDS) -> bool:
    return is_accessory(name, words) or any(w in name for w in MATERIAL_WORDS)


def count_for(key: str, items: dict[str, int]) -> int:
    """这张清单里算进这个目标的东西一共几个：目标是饰品的范围就按目录算，否则算名字里包含 key 的。"""
    flt = AC.parse_filter(key)
    if flt is not None:
        return AC.count_in(flt, items)
    return sum(int(n) for name, n in items.items() if key and key in name)


class LootBook:
    def __init__(self, path: str | Path | None = None, words: tuple[str, ...] | list[str] | None = None):
        self.path = Path(path) if path else None
        self.words = tuple(dict.fromkeys(list(ACCESSORY_WORDS) + [str(w) for w in (words or []) if str(w).strip()]))
        self.runs: list[dict[str, Any]] = []
        self.session: dict[str, Any] | None = None
        if self.path is not None and self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                self.runs = [r for r in d.get("runs", []) if isinstance(r, dict) and isinstance(r.get("items"), dict)]
                self.session = d.get("session") if isinstance(d.get("session"), dict) else None
            except Exception:  # noqa: BLE001 —— 文件坏了就当没有，不影响这一局
                self.runs, self.session = [], None

    # ---- 记 ----
    def record(self, items: dict[str, int], guild: str = "", tier: int = 0, score: int | None = None, read: bool = True,
               shot: str = "") -> dict[str, Any]:
        """记一局的战利品。返回这一局的小结：{accessories {名字: 数量}, unknown [没见过的名字], hits {目标关键字: 这一局拿到几个}}。"""
        items = {str(k): int(v) for k, v in items.items() if int(v) > 0}
        run = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "guild": guild, "tier": tier, "score": score, "items": items, "read": bool(read), "shot": shot}
        self.runs.append(run)
        del self.runs[:-KEEP_RUNS]
        acc = {n: c for n, c in items.items() if is_accessory(n, self.words)}
        hits: dict[str, int] = {}
        if self.session is not None:
            self.session["runs"] = int(self.session.get("runs", 0)) + 1
            got = self.session.setdefault("got", {})
            for key in self.session.get("targets", {}):
                n = count_for(key, items)
                hits[key] = n
                got[key] = int(got.get(key, 0)) + n
        return {"accessories": acc, "unknown": [n for n in items if not is_known(n, self.words)], "hits": hits}

    def save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"runs": self.runs, "session": self.session}, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    # ---- 连续刷的这一轮 ----
    def begin(self, targets: dict[str, int], fresh: bool = False) -> dict[str, Any]:
        """开始（或者接着）一轮连续刷。目标和上一轮一样、上一轮还没刷够、又没说要从头算：接着上一轮的数往下数。"""
        clean: dict[str, int] = {}
        for k, v in (targets or {}).items():
            if str(k).strip() and int(v) > 0:
                clean[target_key(k)] = clean.get(target_key(k), 0) + int(v)       # 两种写法说的是同一个范围（戒指、轮）：并成一个
        targets = clean
        s = self.session
        if fresh or s is None or s.get("targets") != targets or not self.left():
            self.session = {"targets": targets, "got": {k: 0 for k in targets}, "runs": 0, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
        return self.session

    def left(self) -> dict[str, int]:
        """每个目标还差几个（已经够了的不列）。没有在刷的一轮返回空。"""
        s = self.session or {}
        got = s.get("got", {})
        return {k: int(v) - int(got.get(k, 0)) for k, v in (s.get("targets") or {}).items() if int(v) - int(got.get(k, 0)) > 0}

    def done(self) -> bool:
        return self.session is not None and bool(self.session.get("targets")) and not self.left()

    # ---- 看 ----
    def totals(self, guild: str | None = None) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.runs:
            if guild is not None and r.get("guild") != guild:
                continue
            for n, c in r["items"].items():
                out[n] = out.get(n, 0) + int(c)
        return out

    def guild_rates(self, key: str) -> dict[str, tuple[float, int]]:
        """每个公会平均一局出几个名字里带 key 的东西：{公会: (平均每局几个, 打过几局)}。选打哪个公会用。"""
        out: dict[str, tuple[float, int]] = {}
        for g in {str(r.get("guild") or "") for r in self.runs}:
            mine = [r for r in self.runs if str(r.get("guild") or "") == g and r.get("read", True)]
            if g and mine:
                out[g] = (sum(count_for(key, r["items"]) for r in mine) / len(mine), len(mine))
        return out

    def pick_guild(self, guilds: list[str], default: str, min_runs: int = 3, hints: dict[str, tuple[str, ...]] | None = None) -> tuple[str, str]:
        """接下来这一局打哪个公会。还差的目标里有饰品：按目录挑出得了、而且还差得最多的那个公会；候选里没有出得了的返回 ("", 原因)，
        调用的地方必须停下（硬打下去只会白花通行证）。还差的都是别的东西（材料）时照老办法：还差的目标里挑最缺的那个，看哪个公会出它出得多；
        候选里有公会还没打够 min_runs 局（不知道它出什么）就先去打它（hints 里说“多半出这一类”的排前面）；都没出过就用默认的。返回（公会, 一句理由）。"""
        guilds = [g for g in dict.fromkeys(guilds) if g] or [default]
        left = self.left()
        acc_left = {k: n for k, n in left.items() if AC.parse_filter(k) is not None}
        if acc_left:                                 # 还差的是饰品：哪个公会出什么目录里写着，不用试
            g, why = AC.best_guild(acc_left, guilds, prefer=default)
            return (g or ""), why
        if not left or len(guilds) == 1:
            return (guilds[0] if len(guilds) == 1 else default), ("只有一个候选公会" if len(guilds) == 1 else "没有还差的目标")
        key = max(left, key=lambda k: left[k])
        rates = self.guild_rates(key)
        hinted = [g for g in guilds if any(h in key or key in h for h in (hints or {}).get(g, ()))]
        fresh = [g for g in guilds if rates.get(g, (0.0, 0))[1] < min_runs]
        if fresh:
            g = next((x for x in hinted if x in fresh), fresh[0])
            return g, (f"「{g}」只打过 {rates.get(g, (0.0, 0))[1]} 局，还不知道它出不出「{key}」，先打它看看"
                       + ("（资料上说它多半出这一类）" if g in hinted else ""))
        best = max(guilds, key=lambda g: rates[g][0])
        if rates[best][0] <= 0:
            g = hinted[0] if hinted else default
            return g, f"候选的公会都没出过「{key}」，" + (f"资料上说「{g}」多半出这一类，先打它" if hinted else f"先用默认的「{default}」")
        return best, f"还差最多的是「{key}」（差 {left[key]} 个），「{best}」平均一局出 {rates[best][0]:.2f} 个（{rates[best][1]} 局）"

    def lines(self) -> list[str]:
        """给日志的小结：这一轮的进度；打过几局、一共出过哪些饰品。"""
        out: list[str] = []
        s = self.session
        if s and s.get("targets"):
            got = s.get("got", {})
            out.append("  连续刷的进度：" + "、".join(f"{k} {int(got.get(k, 0))}/{v}" for k, v in s["targets"].items())
                       + f"（这一轮已经打通 {int(s.get('runs', 0))} 局）")
        tot = self.totals()
        acc = {n: c for n, c in tot.items() if is_accessory(n, self.words)}
        if self.runs:
            out.append(f"  战利品账本：记过 {len(self.runs)} 局；饰品一共 "
                       + ("、".join(f"{n} ×{c}" for n, c in sorted(acc.items(), key=lambda x: -x[1])) if acc else "0 件") + "。")
        return out
