"""真机伤害记录：每场打完从「伤害报告」读每个人打了多少，记下来，拿来校正“谁是真的能打”。

用户 2026-11-24 定的做法：测试的时候每场打完看一下输出；增益角色不算；该打输出的角色里哪个伤害高就调高比重；记录所有输出角色。

存在 data/learned/damage.json，跨局保留。每个角色记两个数：
  rate  “输出比重”，只给游戏里标着 攻击 / 破防 的角色（增益、减益、强化、干扰、坦克、治疗不算——她们的价值不在自己打多少）。
        同一场里几个输出角色互相比：实际占的伤害比“按现在的比重该占的”多，就调高，少就调低。规则排队时强度乘上它。
  sim   “估算校正”，所有角色都有：战斗估算以为她这一场占几成伤害，真机实际占几成，差多少就把估算里她打出的伤害乘多少。
        只改她自己打出来的伤害，不动她给别人加的增益——所以增益角色不会因为自己伤害低而吃亏。
两个数都是慢慢调的（一场最多调到原来的 0.55～1.8 倍），总共不超出 0.15～3。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

DAMAGE_ROLES = ("attack", "break")       # 算“输出角色”的职能
STEP = 0.6                               # 一场调多少：比值的 0.6 次方
RATIO = (0.375, 2.667)                   # 一场里“实际 ÷ 预期”最多按这个范围算（0.6 次方以后是 0.55～1.8 倍）
LIMIT = (0.15, 3.0)                      # 两个数总的范围
FLOOR = 0.01                             # 占比低于 1% 按 1% 算（免得除出天文数字）
KEEP = 400                               # 最多留多少场的明细
POWER_CLAMP = (0.4, 1.8)                 # rate 乘到强度上时最多这么大的幅度


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class DamageBook:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.chars: dict[str, dict[str, Any]] = {}
        self.fights: list[dict[str, Any]] = []
        if self.path and self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                self.chars = {str(k): dict(v) for k, v in (d.get("chars") or {}).items() if isinstance(v, dict)}
                self.fights = [f for f in (d.get("fights") or []) if isinstance(f, dict)]
            except Exception:  # noqa: BLE001  文件坏了就当没有，不让流程停
                self.chars, self.fights = {}, []

    # ---- 读 ----
    def rate(self, name: str | None) -> float:
        return float((self.chars.get(name or "") or {}).get("rate", 1.0))

    def rates(self) -> dict[str, float]:
        """输出角色的比重（只有调过的才在里面）。"""
        return {n: float(c["rate"]) for n, c in self.chars.items() if "rate" in c and abs(float(c["rate"]) - 1.0) > 1e-6}

    def sims(self) -> dict[str, float]:
        """战斗估算里每个角色打出的伤害乘多少（只有调过的才在里面）。"""
        return {n: float(c["sim"]) for n, c in self.chars.items() if "sim" in c and abs(float(c["sim"]) - 1.0) > 1e-6}

    def table(self) -> list[dict[str, Any]]:
        """所有记过伤害的角色，输出角色在前、比重高的在前。"""
        rows = [{"name": n, **c} for n, c in self.chars.items() if c.get("n")]
        return sorted(rows, key=lambda r: (r.get("role") not in DAMAGE_ROLES, -float(r.get("rate", 1.0)), -float(r.get("share", 0.0))))

    # ---- 记一场 ----
    def record(self, team: list[str], roles: list[str | None], damage: list[int | None], sim_share: dict[str, float] | None = None,
               **info: Any) -> dict[str, Any]:
        """team / roles / damage 一一对应（damage 里读不出来的是 None）。sim_share = 战斗估算以为每个人占几成（没有估算就不给）。
        返回这一场的小结：{"shares": {名字: 占比}, "rate": {名字: (旧, 新)}, "sim": {名字: (旧, 新)}}。五个人没读全就只记明细、不调数。"""
        known = [(n, r, d) for n, r, d in zip(team, roles, damage) if n and "/" not in n and d is not None]
        total = float(sum(d for _n, _r, d in known))
        out: dict[str, Any] = {"shares": {}, "rate": {}, "sim": {}, "full": False}
        fight = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "team": list(team), "roles": list(roles), "damage": list(damage), **info}
        full = len(known) == len(team) and len(team) >= 2 and total > 0
        if full:
            learn = info.get("cause") != "protection"
            if info.get("battle") == "boss":
                result = info.get("result")
                learn = learn and (result == "win" or (result == "lose" and bool(info.get("cause"))))
            out["full"] = True
            shares = {n: d / total for n, _r, d in known}
            out["shares"] = shares
            fight["shares"] = {n: round(s, 4) for n, s in shares.items()}
            for n, r, d in known:
                c = self.chars.setdefault(n, {})
                c["n"] = int(c.get("n", 0)) + 1
                if info.get("unit") != "bar":                              # 数字没读出来、按条的长度折的相对值，不算进累计伤害
                    c["dmg"] = float(c.get("dmg", 0.0)) + float(d)
                c["share"] = round((float(c.get("share", 0.0)) * (c["n"] - 1) + shares[n]) / c["n"], 4)
                c["role"] = r or c.get("role")
                c["last"] = fight["when"][:10]
            # 输出角色之间互相比（至少两个输出角色才比得出来）
            dealers = [(n, d) for n, r, d in known if r in DAMAGE_ROLES]
            if learn and len(dealers) >= 2 and sum(d for _n, d in dealers) > 0:
                dsum = float(sum(d for _n, d in dealers))
                wsum = sum(self.rate(n) for n, _d in dealers)
                ratio = {n: _clip(max(FLOOR, d / dsum) / max(FLOOR, self.rate(n) / wsum), *RATIO) ** STEP for n, d in dealers}
                norm = 1.0
                for n, _d in dealers:                                  # 几个人一起调：按比重加权的平均不变（只挪相对高低，不整体涨跌）
                    norm *= ratio[n] ** (self.rate(n) / wsum)
                for n, _d in dealers:
                    old = self.rate(n)
                    new = round(_clip(old * ratio[n] / norm, *LIMIT), 3)
                    self.chars[n]["rate"] = new
                    out["rate"][n] = (round(old, 3), new)
            # 估算校正：估算以为的占比 对 真机的占比
            if learn and sim_share and all(n in sim_share for n, _r, _d in known) and sum(sim_share.values()) > 0:
                ssum = float(sum(sim_share[n] for n, _r, _d in known))
                ratio = {n: _clip(max(FLOOR, shares[n]) / max(FLOOR, sim_share[n] / ssum), *RATIO) ** STEP for n, _r, _d in known}
                scale = sum((sim_share[n] / ssum) * ratio[n] for n, _r, _d in known) or 1.0     # 调完以后，估算里全队的总伤害不变
                fight["sim_shares"] = {n: round(sim_share[n] / ssum, 4) for n, _r, _d in known}
                for n, _r, _d in known:
                    old = float(self.chars[n].get("sim", 1.0))
                    new = round(_clip(old * ratio[n] / scale, *LIMIT), 3)
                    self.chars[n]["sim"] = new
                    out["sim"][n] = (round(old, 3), new)
        self.fights.append(fight)
        del self.fights[:-KEEP]
        return out

    def save(self) -> bool:
        if not self.path:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"about": "真机伤害记录（每场打完从伤害报告读的）。rate = 输出角色的比重；sim = 战斗估算里她打出的伤害乘多少。删掉这个文件 = 从头学。",
                                       "version": 1, "chars": self.chars, "fights": self.fights}, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
            return True
        except Exception:  # noqa: BLE001
            return False


def power_factor(rate: float | None) -> float:
    """rate 乘到“强度”上的幅度。"""
    return 1.0 if not rate else _clip(float(rate), *POWER_CLAMP)
