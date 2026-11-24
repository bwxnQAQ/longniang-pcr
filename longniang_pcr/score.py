"""分数公式（纯计算）。

难度 5 的最终分数（2026-11-16 那局录制的 RESULT 页逐项核对过，49,800 分一分不差）：
    2.0 ×（100×走过的格数 + 500×区域数 + 100×角色数 + 200×遗物数 + 100×普通战场数 + 1000×极难战场数 + 1500×首领数）
其中“角色数”“遗物数”就是地图左下角那两个数字；事件里打的斗技场不算普通战 / 极难战。
"""
from __future__ import annotations

FULL_TILES = 31          # 一整局的格数：5 + 6 + 6 + 7 + 7，最后一格是最终首领
FULL_AREAS = 5
FULL_BOSSES = 2
MULT = {5: 2.0}          # 难度 → 倍率（只核对过难度 5）


def score(tiles: int, areas: int, chars: int, relics: int, normal: int, extreme: int, bosses: int, difficulty: int = 5) -> int:
    base = 100 * tiles + 500 * areas + 100 * chars + 200 * relics + 100 * normal + 1000 * extreme + 1500 * bosses
    return int(round(MULT.get(difficulty, 2.0) * base))


def score_if_cleared(chars: int, relics: int, normal: int, extreme: int, difficulty: int = 5) -> int:
    """站在最终首领跟前时：把最终首领打掉的话，最终分数是多少（最终首领本身不再给角色和遗物）。"""
    return score(FULL_TILES, FULL_AREAS, chars, relics, normal, extreme, FULL_BOSSES, difficulty)


TARGET = 50000           # 计划里高分向攻略说的那条线（“稳定 5 万以上”）


def shortfall(points: int, target: int = TARGET, difficulty: int = 5) -> str:
    """离目标分数还差多少，折成“几个遗物 / 几名角色”好懂一点。够了就说超出多少。"""
    gap = target - int(points)
    if gap <= 0:
        return f"比 {target:,} 多 {-gap:,} 分"
    m = MULT.get(difficulty, 2.0)
    relics, chars = -(-gap // int(200 * m)), -(-gap // int(100 * m))       # 向上取整
    return f"离 {target:,} 还差 {gap:,} 分（相当于再多 {relics} 个遗物，或者 {chars} 名角色）"
