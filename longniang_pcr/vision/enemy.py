"""「战斗准备」页面上是哪个敌人。

单个大敌人（多数极难、首领）的页面中间有一条血条，血条左上方写着名字（“岛鲸　等级.400　弱点 —”）。
认名字有两条路，先后试：
  1. 模板：录制里见过的名字（岛鲸、好朋友X、幽灵领主、领主哥布林）直接比对那几个字的形状，不依赖 OCR；
  2. OCR：把名字那一条放大 3 倍交给 RapidOCR，读出来的字和对策表里的名字 / 别名对（允许错一两个字）。
一排敌人站开的页面上没有名字（一个装置 + 几个角色的极难关；带小怪的首领，比如厄勒克特拉夫人）：
  3. 见过的那几组按画面认（模板 lineup_*，LINEUPS 里写着是谁）；没见过的认不出来，返回 None
     （极难格子里认不出的那一组，流程里按对策表的 unseen_group 排：要范围输出）。
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .. import ocr
from .pages import PageBook, to_norm

NAME_ROI = (352, 378, 320, 38)            # 名字那一条（不含后面的“等级.400”）
BAR_ROI = (400, 420, 480, 5)              # 血条中间一段：满血时整条是橙红色
MARK_PREFIX = "enemy_"
# 一排敌人的页面：模板 → 对策表里的名字。厄勒克特拉夫人：2026-11-16 录制和 11-18 真机上都是这一组；巨型魔像：11-18 真机上见过一次
# 2026-11-19 真机上又见到四组：毒液沙罗曼蛇，和三组“一个装置 + 几个角色”的极难关（对策表里叫 ××装置）
# 2026-11-27 玩家的排查包里有破防装置那一组（哥布林、狸猫、方块装置、龙妈、克蕾琪塔）
LINEUPS = {"lineup_hen": "厄勒克特拉夫人", "lineup_golem": "巨型魔像", "lineup_salamander": "毒液沙罗曼蛇",
           "lineup_attack": "攻击装置", "lineup_curse": "诅咒装置", "lineup_shield": "护盾装置", "lineup_frosthound": "冰霜魔狼",
           "lineup_break": "破防装置",
           # 2026-11-27 傍晚：用户自己电脑上一次运行里存下的十张“没认出来的一组”，其实是这五种（见 tools/dev/scratch/mk1127b.py）
           "lineup_heal": "回复装置", "lineup_bomb": "炸弹装置", "lineup_shield2": "护盾装置", "lineup_queen": "蜂后", "lineup_misora": "美空"}


MON_ROI = (388, 98, 360, 32)              # 「魔物详情」左上角的名字（黑字压在白底上）
MON_PREFIX = "mon_"


def read_monster(book: PageBook, img: np.ndarray, enemies: dict[str, Any]) -> dict[str, Any]:
    """「魔物详情」（在地图上点进度条的 BOSS 图标出来的）写的是哪个敌人。
    返回 {"name": 对策表里的名字或 None, "how": "template" / "ocr" / "", "text": OCR 读到的字}。"""
    out: dict[str, Any] = {"name": None, "how": "", "text": ""}
    best = (0.0, None)
    for key, m in book.marks.items():
        if key.startswith(MON_PREFIX):
            sc, _ = book.find_mark(img, key)
            if sc >= float(m.get("thr", 0.85)) and sc > best[0]:
                best = (sc, m.get("name"))
    if best[1] and best[1] in enemies:
        out.update(name=best[1], how="template", score=round(best[0], 2))
        return out
    seen = []
    for how, text in ocr.label_reads(img, MON_ROI, ink="dark"):
        if text and text not in seen:
            seen.append(text)
        name, sc = match_name(text, enemies)
        if name:
            out.update(name=name, how="ocr", score=round(sc, 2), read=how)
            break
    out["text"] = " / ".join(seen)
    return out


def load_counters(data_dir: Path) -> dict[str, Any]:
    """读对策表；文件不在或者坏了就当空表（所有敌人都按通用打法）。"""
    try:
        d = json.loads((Path(data_dir) / "counters.json").read_text(encoding="utf-8"))
        return d if isinstance(d.get("enemies"), dict) else {"enemies": {}}
    except Exception:  # noqa: BLE001
        return {"enemies": {}}


def has_name_bar(img: np.ndarray) -> bool:
    """页面中间有没有那条血条（有 = 单个大敌人，名字就在血条左上方）。"""
    x, y, w, h = BAR_ROI
    p = to_norm(img)[y:y + h, x:x + w].astype(np.int16)
    b, g, r = p[..., 0], p[..., 1], p[..., 2]
    return float(((r > 190) & (g > 50) & (g < 170) & (b < 110)).mean()) > 0.6


def _clean(text: str) -> str:
    text = re.sub(r"等级.*$", "", text)
    return re.sub(r"[\s·\.\-—_:：,，。!！?？|｜\[\]【】()（）]+", "", text)


def match_name(text: str, enemies: dict[str, Any]) -> tuple[str | None, float]:
    """OCR 读到的字 → 对策表里的名字。整段包含名字算 1.0；否则按相似度，够像（≥0.6）才认。"""
    t = _clean(text)
    if not t:
        return None, 0.0
    best: tuple[str | None, float] = (None, 0.0)
    for name, info in enemies.items():
        for alias in [name] + list(info.get("alias", [])):
            a = _clean(alias)
            if not a:
                continue
            if a.lower() in t.lower():
                sc = 1.0 + 0.01 * len(a)                     # 都包含时取名字长的（“哥布林” < “领主哥布林”）
            else:
                sc = difflib.SequenceMatcher(None, a.lower(), t.lower()[:len(a) + 2]).ratio()
                if len(a) <= 2:                              # 两个字的名字错一个就是另一个词了：不模糊匹配
                    sc = 0.0
            if sc > best[1]:
                best = (name, sc)
    return (best[0], min(best[1], 1.0)) if best[1] >= 0.6 else (None, best[1])


def read_enemy(book: PageBook, img: np.ndarray, enemies: dict[str, Any]) -> dict[str, Any]:
    """返回 {"name": 对策表里的名字或 None, "how": "template" / "ocr" / "", "text": OCR 读到的字, "bar": 有没有血条}。"""
    out: dict[str, Any] = {"name": None, "how": "", "text": "", "bar": has_name_bar(img)}
    if not out["bar"]:
        best = (0.0, None)
        for key, name in LINEUPS.items():
            if key in book.marks and name in enemies:
                sc, _ = book.find_mark(img, key)
                if sc >= float(book.marks[key].get("thr", 0.85)) and sc > best[0]:
                    best = (sc, name)
        if best[1]:
            out.update(name=best[1], how="lineup", score=round(best[0], 2))
        return out
    best = (0.0, None)
    for key, m in book.marks.items():
        if not key.startswith(MARK_PREFIX):
            continue
        sc, _ = book.find_mark(img, key)
        if sc >= float(m.get("thr", 0.8)) and sc > best[0]:
            best = (sc, m.get("name"))
    if best[1] and best[1] in enemies:
        out.update(name=best[1], how="template", score=round(best[0], 2))
        return out
    seen = []
    for how, text in ocr.label_reads(img, NAME_ROI, ink="white"):      # 名字是带描边的白字压在背景上：几种读法轮着试，对上对策表就停
        if text and text not in seen:
            seen.append(text)
        name, sc = match_name(text, enemies)
        if name:
            out.update(name=name, how="ocr", score=round(sc, 2), read=how)
            break
    out["text"] = " / ".join(seen)
    return out
