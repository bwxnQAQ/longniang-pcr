"""公会（2026-11-24）：国服现在十个公会都能选，不再只认慈乐之音。

- 名字和认它用的关键字在 GUILDS 里（公会选择页上「王宫骑士团」下面还有一行（NIGHTMARE），「美食殿」有的地方写「美食殿堂」，所以按关键字认）；
- 「刷分」= 不指定公会，让工具挑：默认咲恋救济院（2026-11-18 用户定的），等每个打过的公会都攒了几局成绩以后，改挑平均估分最高的那个；
- 每局走到最终首领跟前时算的“打掉最终首领能得多少分”、用了多久，按公会记在 data/learned/guilds.json。
- 哪个公会的宝箱出哪种饰品：见 accessories.py（2026-11-24 晚照用户录的十个公会的「可以获得的报酬」做的目录）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

# (标准名, 认它用的关键字——公会选择页上读到的字里有其中一个就算)
GUILDS: list[tuple[str, tuple[str, ...]]] = [
    ("咲恋救济院", ("咲恋救济院", "救济院", "咲恋")),
    ("王宫骑士团", ("王宫骑士团", "骑士团", "NIGHTMARE")),
    ("美食殿堂", ("美食殿",)),
    ("拉比林斯", ("拉比林斯", "拉比林")),
    ("破晓之星", ("破晓之星", "破晓")),
    ("慈乐之音", ("慈乐之音", "慈乐")),
    ("恶魔伪王国军", ("恶魔伪王国军", "伪王国军", "伪王国")),
    ("伊丽莎白牧场", ("伊丽莎白牧场", "伊丽莎白", "牧场")),
    ("墨丘利财团", ("墨丘利财团", "墨丘利", "财团")),
    ("暮光流星群", ("暮光流星群", "流星群", "暮光")),
]
NAMES = [n for n, _k in GUILDS]
SCORE = "刷分"                  # 界面和设置里的特殊选项：让工具自己挑分最高的公会
AUTO = "自动"                   # 按饰品连续刷时的特殊选项：十个公会里按账本挑
SCORE_DEFAULT = "咲恋救济院"
MARKS = {"慈乐之音": "guild_cile"}      # 有名字模板的公会（没有读字的组件时也认得出）
MIN_RUNS = 3
KEEP = 60                       # 每个公会留最近这么多局的成绩


def canon(name: Any) -> str | None:
    """你写的名字 → 标准名（“美食殿”“救济院”“王宫骑士团（NIGHTMARE）”都认）。认不出返回 None。"""
    t = str(name or "").replace(" ", "").replace("（", "(").upper()
    if not t:
        return None
    for std, keys in GUILDS:
        if t == std.upper() or any(k.upper() in t for k in keys) or (len(t) >= 2 and t in std.upper()):
            return std
    return None


def keys_of(name: str) -> tuple[str, ...]:
    for std, keys in GUILDS:
        if std == name:
            return keys
    return (name,) if name else ()


def matches(name: str, text: str) -> bool:
    """公会选择页上读到的这一块字是不是这个公会的名字。"""
    t = text.replace(" ", "").replace("　", "").upper()
    return any(k.upper() in t for k in keys_of(name))


def mark_of(name: str) -> str:
    return MARKS.get(name, "")


class GuildBook:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.runs: dict[str, list[dict[str, Any]]] = {}
        if self.path is not None and self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                self.runs = {str(g): [r for r in rs if isinstance(r, dict)] for g, rs in (d.get("runs") or {}).items() if isinstance(rs, list)}
            except Exception:  # noqa: BLE001 —— 坏了就当没有
                self.runs = {}

    def record(self, guild: str, score: int | None, minutes: float | None = None, result: str = "", tier: int = 0) -> None:
        """记一局。result："final" 走到最终首领跟前（撤退）/ "cleared" 打通 / 其他（没走完的不算进平均分）。"""
        if not guild:
            return
        rs = self.runs.setdefault(guild, [])
        rs.append({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "score": int(score) if score else None,
                   "minutes": round(float(minutes), 1) if minutes else None, "result": result, "tier": tier})
        del rs[:-KEEP]

    def save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"runs": self.runs}, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    def scored(self, guild: str) -> list[int]:
        return [int(r["score"]) for r in self.runs.get(guild, []) if r.get("score") and r.get("result") in ("final", "cleared")]

    def avg(self, guild: str) -> tuple[float, int]:
        s = self.scored(guild)
        return (sum(s) / len(s), len(s)) if s else (0.0, 0)

    def pick_for_score(self, default: str = SCORE_DEFAULT, min_runs: int = MIN_RUNS) -> tuple[str, str]:
        """「刷分」这一局打哪个公会：默认的那个还没攒够 min_runs 局就先打它；攒够了以后，别的公会里有攒够局数、平均分更高的就换过去。"""
        d_avg, d_n = self.avg(default)
        if d_n < min_runs:
            return default, f"刷分默认用「{default}」（它才记过 {d_n} 局成绩，先攒够 {min_runs} 局）"
        best, best_avg, best_n = default, d_avg, d_n
        for g in self.runs:
            a, n = self.avg(g)
            if n >= min_runs and a > best_avg:
                best, best_avg, best_n = g, a, n
        if best == default:
            return default, f"「{default}」平均估分 {d_avg:,.0f}（{d_n} 局），记过成绩的公会里它最高"
        return best, f"「{best}」平均估分 {best_avg:,.0f}（{best_n} 局），比默认的「{default}」{d_avg:,.0f} 高"

    def table(self) -> list[dict[str, Any]]:
        """每个打过的公会一行：局数、平均估分、最高估分、平均用时。按平均估分从高到低。"""
        out = []
        for g, rs in self.runs.items():
            s = self.scored(g)
            mins = [float(r["minutes"]) for r in rs if r.get("minutes") and r.get("result") in ("final", "cleared")]
            out.append({"guild": g, "runs": len(rs), "scored": len(s), "avg": round(sum(s) / len(s)) if s else None, "best": max(s) if s else None,
                        "minutes": round(sum(mins) / len(mins), 1) if mins else None})
        return sorted(out, key=lambda r: -(r["avg"] or 0))

    def lines(self) -> list[str]:
        rows = [r for r in self.table() if r["scored"]]
        if not rows:
            return []
        return ["  各公会的成绩（走到最终首领跟前时算的“打掉它能得多少分”）：" + "；".join(
            f"{r['guild']} 平均 {r['avg']:,}、最高 {r['best']:,}（{r['scored']} 局" + (f"，一局约 {r['minutes']:.0f} 分钟" if r["minutes"] else "") + "）" for r in rows) + "。"]
