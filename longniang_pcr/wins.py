"""打赢过的队、打输过的队（2026-11-24）：按敌人记真机上的结果，下次遇到同一个敌人——

- 以前赢过的队里，现在名单凑得齐的、最快的那一队，直接上（不再按规则排、也不再推演：真打出来的比估算准）；
- 以前只输没赢过的队，不再上（交给战斗估算时也排除掉）。

只记极难和单队打的首领战，而且五个人的名字都认得出、敌人也认得出的场次。存在 data/learned/wins.json，跨局保留。
“一局里赢过的人优先沿用”（run_wins）是另一回事：那是同一局里的，这里是跨局的。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

KEEP = 40            # 每个敌人留最近这么多场
RECENT = 4           # 一队最近这么多场里，赢的比输的多才算“靠得住”
TIME_LIMIT = 90.0    # 一场战斗游戏里最多这么多秒
EST_RECENT = 6       # 估算准不准：看这个敌人最近这么多场带估算的记录
EST_OVER = 1.15      # 时间到了没打完的那一场：实际用时按“至少 90 秒的这么多倍”算


class WinBook:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.fights: dict[str, list[dict[str, Any]]] = {}
        if self.path is not None and self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                self.fights = {str(k): [r for r in v if isinstance(r, dict) and isinstance(r.get("team"), list)]
                               for k, v in (d.get("fights") or {}).items() if isinstance(v, list)}
            except Exception:  # noqa: BLE001 —— 坏了就当没有
                self.fights = {}

    def record(self, enemy: str, team: list[str], win: bool, game: int | None = None, real: float | None = None, area: int = 0, tier: int = 0,
               kind: str = "", est: float | None = None, how: str | None = None) -> None:
        """est = 开打前战斗估算说这一队游戏里几秒打完（估算说打不过、或者没估算就不给）；how = 输的话是怎么输的（timeout = 时间到了）。"""
        if not enemy or len(team) != 5 or len(set(team)) != 5:
            return
        rs = self.fights.setdefault(enemy, [])
        row = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "team": sorted(team), "win": bool(win), "game": game, "real": real, "area": area, "tier": tier, "kind": kind}
        if isinstance(est, (int, float)) and est > 0:
            row["est"] = round(float(est), 1)
        if how and not win:
            row["how"] = how
        rs.append(row)
        del rs[:-KEEP]

    def est_factor(self, enemy: str) -> tuple[float, int] | None:
        """这个敌人真机上的用时是战斗估算的几倍：（倍数, 用了几场的记录）。看最近 EST_RECENT 场带估算的：
        打赢的 = 游戏里实际几秒 ÷ 估算几秒；时间到了没打完的 = 至少是（90 秒 × EST_OVER）÷ 估算几秒。取中间那个。没有记录返回 None。"""
        vals = []
        for r in [r for r in self.fights.get(enemy, []) if isinstance(r.get("est"), (int, float)) and r["est"] > 0][-EST_RECENT:]:
            if r.get("win") and isinstance(r.get("game"), (int, float)) and r["game"] > 0:
                vals.append(float(r["game"]) / float(r["est"]))
            elif not r.get("win") and r.get("how") == "timeout":
                vals.append(TIME_LIMIT * EST_OVER / float(r["est"]))
        if not vals:
            return None
        vals.sort()
        return round(vals[len(vals) // 2], 2), len(vals)

    def est_factor_all(self) -> tuple[float, int] | None:
        """所有敌人合起来：打赢的场次里，实际用时是估算的几倍（中间那个）。少于 5 场不算。"""
        vals = sorted(float(r["game"]) / float(r["est"]) for rs in self.fights.values() for r in rs
                      if r.get("win") and isinstance(r.get("est"), (int, float)) and r["est"] > 0 and isinstance(r.get("game"), (int, float)) and r["game"] > 0)
        return (round(vals[len(vals) // 2], 2), len(vals)) if len(vals) >= 5 else None

    def save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"fights": self.fights}, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    def teams(self, enemy: str) -> list[dict[str, Any]]:
        """这个敌人打过的每一队：赢几场、输几场、最近几场靠不靠得住、赢的时候游戏里最快几秒。"""
        by: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for r in self.fights.get(enemy, []):
            by.setdefault(tuple(r["team"]), []).append(r)
        out = []
        for team, rs in by.items():
            wins = [r for r in rs if r.get("win")]
            recent = rs[-RECENT:]
            games = [int(r["game"]) for r in wins if isinstance(r.get("game"), (int, float))]
            reals = [float(r["real"]) for r in wins if isinstance(r.get("real"), (int, float))]
            out.append({"team": list(team), "wins": len(wins), "losses": len(rs) - len(wins),
                        "solid": sum(1 for r in recent if r.get("win")) > sum(1 for r in recent if not r.get("win")),
                        "game": min(games) if games else None, "real": min(reals) if reals else None})
        return out

    def best(self, enemy: str, have: set[str], skip: list[set[str]] | None = None) -> dict[str, Any] | None:
        """以前赢过、最近也靠得住、现在名单凑得齐的队里最快的那一队（先比游戏里的秒数，没有就比现实秒数）。skip = 这一场已经输过的队。没有返回 None。"""
        skip = [set(s) for s in (skip or [])]
        cands = [t for t in self.teams(enemy) if t["wins"] and t["solid"] and set(t["team"]) <= have and set(t["team"]) not in skip]
        if not cands:
            return None
        return min(cands, key=lambda t: (t["game"] if t["game"] is not None else 999, t["real"] if t["real"] is not None else 9999.0, -t["wins"]))

    def lost(self, enemy: str) -> list[list[str]]:
        """只输没赢过的队：不再上。"""
        return [t["team"] for t in self.teams(enemy) if not t["wins"] and t["losses"]]

    def never_won(self, kind: str = "boss", min_losses: int = 2) -> list[str]:
        """真机上打过至少 min_losses 次、一次都没赢过的敌人（默认只看首领）：第一档凹首领时遇到它们就重开。"""
        out = []
        for enemy, rs in self.fights.items():
            mine = [r for r in rs if not kind or r.get("kind") == kind]
            if len(mine) >= min_losses and not any(r.get("win") for r in mine):
                out.append(enemy)
        return out

    def summary(self) -> tuple[int, int, int]:
        """（记过几个敌人, 一共几场, 其中赢了几场）"""
        n = sum(len(v) for v in self.fights.values())
        return len(self.fights), n, sum(1 for v in self.fights.values() for r in v if r.get("win"))
