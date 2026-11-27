"""出发 → 走几格 → 撤退（阶段 2 第一步）。

和阶段 1 的演练一样从迷宫首页出发、最后「撤退（无报酬）」，所以通行证照样原样退回；
不同的是中间真的往前走：选开局三人、点格子、打战斗（AUTO）、选角色 / 遗物、过事件、路过商店。
走满指定的格数就撤退。这一步的目的是把“打通一局”要用到的每个页面都实打实走一遍。

首领（2026-11-17 加的），由 boss 参数决定打到哪：
- "stop"：见到首领就撤退。
- "mid"：打区域 3 的首领——打完还能照样撤退退通行证；走到最终首领跟前撤退。
- "all"：最终首领也打。打完游戏自动结算（RESULT → 宝箱开封结果 → 获得道具 → 迷宫首页），这一局就结束了，
  通行证不会退回。2026-11-17 你定的：「打通一局」也在最终首领前撤退、不花通行证，所以现在没有哪个入口会用 "all"；
  这段代码留着，等阶段 3 做“分数够了才领奖”时再接上。
首领战的队伍先用最省事的编法：按名单顺序每队 5 个。区域 3 的首领只编队伍 1（你那局录制里就是一队打掉的，
而且用的队伍越少金币越多）；最终首领三队都编上，求稳。怎么按属性和有效效果编队留给阶段 3。

选路（2026-11-16 按你的要求改）：
- 每进一个区域，先拖动地图把整层看完（格子、每格是什么、格子之间的连线），再排这一层的路线：
  有极难的列，每一列的极难都要走到；极难数一样的路线里挑“路上的格子加起来最值分”的（2026-11-17，阶段 3），再一样才取靠上的。
- 有哪一列的极难走不到 → 撤退（无报酬），由外面决定要不要重开。
- 每走一格都按“现在真正发光的格子”重新排一次后面的路，和看全图时的判断不一致会记下来。

其余还没有策略（那是阶段 3）：
- 三选一（角色、遗物）：选最左边；
- 事件：按 data/events.json 里的默认选法；没见过的事件交给你；
- 商店：按 strategy.choose_shop 买（★1 遗物、随机印记这些“每 1 分花的金币少”的先买，能更新就更新；最后一个区域把剩下的金币花掉），
  点「确认」之前核对「购买确认」上的金额；设置里 walk.shop.buy 关掉就和以前一样直接关闭。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..plan import KIND_NAMES, AreaMap, Plan, make_plan, row_name, shop_value
from .. import advisor as AD
from .. import chars as CH
from .. import damage as DM
from .. import ocr
from .. import strategy as ST
from ..runner import Halt, NBox, Runner, Seen
from ..score import score_if_cleared
from ..vision import cards as CD
from ..vision import enemy as EN
from ..vision import battle as VB
from ..vision import hud as HUD
from ..vision import report as RP
from ..vision import routes as RT
from ..vision import shop as SH
from ..vision import team as TM
from ..vision import tiles as TL
from ..vision.pages import to_norm
from .survey import Survey
from .. import guilds as GD
from .. import accessories as AC
from .. import loot as LT
from .. import tiers as TR
from .. import wins as WN
from ..vision import loot as VL
from .retreat_drill import BOX as DRILL_BOX
from .retreat_drill import guild_button

BOX: dict[str, NBox] = dict(DRILL_BOX)
BOX.update({
    "pick3.invite": (990, 612, 200, 40),          # 角色选择的「去邀请」
    "splash.any": (1120, 84, 110, 44),            # 角色登场画面：点右上角空白处翻过去
    "dialog.outside": (1070, 300, 80, 140),       # 获得道具 / 角色加入：点对话框右边的空白处关掉（录制里你也是这么点的）
    "move.ok": (680, 478, 210, 36),               # 移动目标确认的「确认」
    "move.cancel": (392, 478, 200, 36),           # 移动目标确认的「取消」
    "ready.fight": (990, 588, 200, 38),           # 战斗准备的「挑战」
    "team.equip": (800, 588, 36, 34),             # 队伍编组的「特别装备」
    "team.start": (1060, 586, 150, 40),           # 队伍编组的「战斗开始」
    "equip.auto": (690, 618, 200, 40),            # 特别装备设定的「自动装备」
    "equip.ok": (985, 618, 200, 40),              # 特别装备设定的「装备确定」
    "equip.cancel": (95, 620, 200, 36),           # 特别装备设定的「取消」
    "autoequip.ok": (690, 618, 190, 40),          # 自动特别装备设定的「确认」
    "map.boss1": (657, 30, 32, 30), "map.boss2": (811, 30, 32, 30), "monster.close": (586, 624, 100, 30), "end3.retreat": (585, 480, 110, 32),
    "defeat.retry": (960, 636, 230, 40), "defeat.end": (655, 636, 230, 40), "ready.map": (690, 588, 210, 38),
    "win.next": (1010, 636, 200, 38),             # WIN! 的「下一步」
    "scene.skip": (1140, 36, 60, 36),             # 演出画面右上角的跳过
    "shop.close": (985, 616, 180, 38),            # 商店的「关闭」
    "shop.refresh": (375, 636, 150, 26),          # 商店的「用×××更新」
    "buy.ok": (700, 562, 180, 34),                # 购买确认的「确认」
    "buy.cancel": (405, 562, 180, 34),            # 购买确认的「取消」
    "bought.ok": (550, 478, 180, 34),             # 购买完毕的「确认」
    "refresh.ok": (700, 478, 180, 34),            # 更新确认的「确认」
    "refresh.cancel": (405, 478, 180, 34),        # 更新确认的「取消」
    "shop_exit.ok": (680, 478, 210, 38),          # 商店确认的「确认」
    "result.btn": (540, 646, 200, 34),            # RESULT 页下面的「下一步」/「关闭」
    "chest.ok": (540, 622, 200, 34),              # 宝箱开封结果的「确认」
    "chest.open": (560, 470, 260, 60),            # 宝箱开封结果：宝箱还没翻开时，点对话框下半截的空白处翻开
    "daychange.ok": (540, 474, 200, 40),          # 日期变更的「确认」（2026-11-24 真机截图上量的：按钮 503～775 × 463～527）
    "sort.lv": (92, 293, 22, 20),                 # 「分类」里“显示顺序”的第一个选项「等级」前面那个圆点
    "sort.ok": (700, 624, 170, 32),               # 「分类」的「确认」（用户截图上按钮 650～922 × 610～668）
    "sort.cancel": (410, 624, 170, 32),           # 「分类」的「取消」（357～630 × 610～668）
    "notice.ok": (550, 478, 180, 34),             # 只有一个「确认」的提示框（“无法获得报酬。”）：按钮和购买完毕的「确认」在同一个位置
})
OUTSIDE = ("lab_home", "home", "adventure", "guild_select", "dlg_guild_confirm", "dlg_daychange")     # 还没进到一局里面的页面


def read_passes(img: np.ndarray) -> int | None:
    """迷宫首页「持有通行证 75/99」里的 75。没有读字的组件、或者没读出来返回 None。"""
    if not ocr.available():
        return None
    try:
        for _how, text in ocr.label_reads(to_norm(img), (836, 430, 90, 38), ink=None):
            m = re.search(r"(\d{1,3})/(\d{2,3})", text.replace(" ", "").replace("／", "/"))
            if m and int(m.group(1)) <= int(m.group(2)):
                return int(m.group(1))
    except Exception:  # noqa: BLE001
        pass
    return None


AFK_BLIND = ("这台电脑上读字的组件没装好，我看不出标题画面、公告上写的是什么（有没有密码、验证码、支付这些字），"
             "所以不自己走回迷宫，停在这里。在界面上点一次「准备运行环境」再试")


class Hold(Exception):
    """分数够了，但这一次没让工具自己结算：停在最终首领跟前，交给用户（不撤退、不再点）。"""


class Relap(Exception):
    """换日 / 掉线以后走回迷宫，发现原来那一局已经不在了：外面从头再开一局（游戏这时停在公会选择页）。"""

MOVE_KEYS = ["move_normal", "move_extreme", "move_mark", "move_relic", "move_event", "move_shop", "move_boss"]
MOVE_NAMES = {"normal": "战斗格子（普通）", "extreme": "战斗格子（极难）", "mark": "连结印记格子", "relic": "迷宫遗物格子",
              "event": "事件格子", "shop": "商店格子", "boss": "首领战格子"}
PICK_KEYS = ["pick_0", "pick_1", "pick_2", "pick_3"]
EVENT_KEYS = ["ev_arena", "ev_lost", "ev_box", "ev_tablet", "ev_guild_office", "ev_venue", "ev_picnic", "ev_picnic2", "ev_slot2", "ev_janken", "ev_slot"]
EVENT_NAMES = {"arena": "斗技场", "lost": "迷路", "box": "箱子", "tablet": "石板", "guild_office": "公会管理协会",
               "venue": "活动会场出现了魔物（纯）",       # 2026-11-19 真机上第一次见：右边是“纯成为伙伴 + 全体随机印记 ×2～4”，用户定的选纯
               "picnic": "郊游做料理",                    # 2026-11-24 真机上第一次见：只有一个选项（50% 概率进入下一个事件）
               "picnic2": "郊游做料理（做好了）",          # 做成了：左边收手拿“随机职能的印记 ×2”，右边接着做（50% 概率再进下一个事件）。事件表里定的：收手
               # 2026-11-26 用户发来截图：标题「再较量一次！」，左边“挑战结束”，右边“50% 概率获得阿尔法金币 ×4000 并进入下一个事件”（消耗 2000）。
               # 对照事件表应该是老虎机赢了第一把以后的第二步（它的第一步国服长什么样还没见过）。
               # 18:38 用户说保持选左边；19:28 改成押；21:30 看了金币是怎么进出的以后定下来：不押（见 _slot_pick；押的那套留在 walk.slot_bet 后面）。
               # 选了左边会弹一个「确认」框“无法获得报酬。”——见主循环里的 dlg_no_reward；押完以后出什么还没见过
               "slot2": "再较量一次（押金币）",
               # 老虎机的第一步「是老虎机！要挑战吗？」：只有一个选项（50% 概率获得阿尔法金币 ×2000 并进入下一个事件），不花钱。
               # 2026-11-26 玩家排查包里见到两次：赢了那次金币 4,950 → 6,950（当场进口袋），接着就是「再较量一次！」；输了那次 +500（保底）
               "slot": "老虎机（要挑战吗）",
               "janken": "石头剪刀布"}                    # 2026-11-26 玩家排查包里第一次见：三项一样（赢了 3000 金币、输了 1000），选哪个都行
EVENT_OPTIONS = {"arena": 2, "lost": 2, "box": 2, "tablet": 3, "guild_office": 2, "venue": 2, "picnic": 1, "picnic2": 2, "slot2": 2, "janken": 3, "slot": 1}
# 公会管理协会：给出一组两种职能，二选一。计划里定的选法（每组里选哪个）：
#   坦克 / 治疗 → 治疗（队里只有 1 名坦克时选坦克——这条要能读出队伍职能才做得了，留到阶段 3）
#   攻击 / 破坏 → 破坏；辅助 / 增益 → 增益；减益 / 干扰 → 减益
ROLE_KEYS = {"tank": "role_tank", "heal": "role_heal", "debuff": "role_debuff", "jam": "role_jam",
             "support": "role_support", "buff": "role_buff",
             "attack": "role_attack", "break": "role_break"}   # 攻击 / 破防这一组：2026-11-24 真机上第一次遇到，照那张截图补的
ROLE_NAMES = {"tank": "坦克", "heal": "治疗", "attack": "攻击", "break": "破坏", "support": "强化", "buff": "增益",
              "debuff": "减益", "jam": "干扰"}
ROLE_RULE = [({"tank", "heal"}, "heal"), ({"attack", "break"}, "break"), ({"support", "buff"}, "buff"), ({"debuff", "jam"}, "debuff")]
LABEL_NAMES = {"normal": "普通", "extreme": "极难", "boss": "首领", None: "非战斗格"}
KIND_CN = {"normal": "普通战", "extreme": "极难", "boss": "首领战"}
PROFILE_CN = {"fast": "打法：快攻", "steady": "打法：稳（带坦克和治疗）", "sturdy": "打法：加厚", "burst": "打法：全输出"}
HIT_CN = {"aoe": "打一群", "single": "打单体", "both": "单体和一群都行"}
# 队伍编组的名单一屏放不下时往下翻：每次拖多远（1280×720 坐标）。首领战一屏只有一行（行距 147），普通战两行；
# 都少拖十几个像素，新露出来的那一行就不会被名单上沿切掉“等级”两个字
# 名单怎么翻（2026-11-19 真机上出过事以后重写的）：
#   名单在最上面时再往下拉，会拉出一条「用角色名搜索」的输入框，按到它会弹出输入法——那一趟就是从 y=190 起手拖，正好按在上面。
#   所以：起手和落手都在 LIST_DRAG 这条竖线上（第 4、5 列卡片中间的缝），而且最高不超过 y=232（输入框露出来时在 160～203）；
#   往上翻之前先看“这个页签的第一张卡是不是已经看得见”，看得见就不再往上拉；每次只翻需要的那几行，不多拉。
LIST_STEP = {True: 135.0, False: 236.0}  # 看名单时一次往下翻多少：首领战一屏只有一行，翻一行；平时一屏两行多，翻一行半（不会漏行）
ROW_STEP = {True: 135.0, False: 147.0}   # 找某一张卡时，差一行就拖这么多
LIST_DRAG = (640.0, 470.0)               # 从这里往上拖（两列卡片中间的缝里，不会按到卡片上）
MAX_LIST_SCROLL = 10                     # 一个页签最多往下翻几次（一行 8 张，翻 10 次能看 100 多张）
IME_ROI = (100, 655, 1000, 60)           # 弹出输入法时，画面最下面这一条是白的（右边有「确定」）
IME_OK = (1205.0, 664.0, 54.0, 34.0)     # 那条白栏右边的「确定」
TAB_CN = {"all": "全部", "fire": "火", "water": "水", "wind": "风", "light": "光", "dark": "暗", "effect": "有效效果"}
# 同一个页面连续出现多少次还没过去就停（有些页面本来就要点好几下）
SAME_LIMIT = {"dlg_team": 90, "dlg_pick3": 10, "map": 12, "win": 8, "win_next": 5, "join_splash": 8, "event": 6,
              "relic_pick": 10, "recruit_pick": 10, "result": 12, "dlg_chest_result": 8,
              "dlg_shop": 20, "dlg_buy": 8, "dlg_refresh": 8,
              "guild_select": 40}      # 公会选择页要左右拖着找公会：它自己数着拖了几次、到头没有（_on_guild_select），不靠这里的 3 次
GUILD_ONE_WAY = 10                 # 公会选择页上一个方向最多拖这么多次（十个公会、一屏三个，五六次就到头了；到头会自己掉头）
SHOP_DRAG = ((434.0, 520.0), (434.0, 330.0))     # 把商品列表往上拖一截（190 像素；普通商店一共只能拖 70，一下就到底）：从两列商品中间的缝里拖
SHOP_MAX_BUYS = 24                               # 一家商店最多买这么多件（6 件一批、最多 3 批是 18 件；再多说明哪里不对）
SAME_DEFAULT = 3            # 其他页面：点了 3 次还在原地就停（多半是按钮是灰的，或者点的位置不对）


def button_lit(img: np.ndarray, box: NBox) -> bool:
    """蓝色按钮现在能不能点。能点时是亮蓝底白字（这一块平均亮度 150 左右），灰掉时是暗蓝底暗字（95 左右）。"""
    x, y, w, h = (int(v) for v in box)
    gray = cv2.cvtColor(to_norm(img)[y + 6:y + h - 6, x + 15:x + w - 15], cv2.COLOR_BGR2GRAY)
    return float(gray.mean()) >= 125.0


SLOT_DIGIT_COLS = (46, 59)      # “消耗2000”那一块（标记 slot_cost2000）里，第一个数字占的那几列
SLOT_BET_COST = 2000            # 「再较量一次！」只押这一步（押 2000 赌 4000）；按钮上不是这个数就不押
PAID_LABEL_Y = 566              # 「选择」两个字的位置：不花金币的按钮在 y≈576；要花金币的按钮下面多一行“消耗 N”，字往上挪到 y≈556


def _orange(bgr: np.ndarray) -> np.ndarray:
    """按钮上那行橙色字（“消耗2000”）的字芯，0/1。"""
    b, g, r = (bgr[..., i].astype(np.int16) for i in range(3))
    return ((r > 200) & (g > 120) & (b < 140)).astype(np.uint8)


def slot_cost_is_2000(book: Any, img: np.ndarray) -> tuple[bool, float, float]:
    """「再较量一次！」右边按钮上写的是不是“消耗2000”。返回（是不是, 整块的相似度, 第一个数字的字形重合度）。

    整块比灰度的话“消耗4000”“消耗8000”也有 0.97（六个字里只差一个），分不开；所以整块对上以后，再单独比第一个数字的橙色字芯：
    同一个“2”重合度是 1.0，换成别的数字只有 0.4 左右。两样都够才算——认错了就是白白多押一次金币，所以宁可不认。"""
    if "slot_cost2000" not in book.marks or "slot_digit2" not in book.tmpl:
        return False, 0.0, 0.0
    whole, (x, y, w, h) = book.find_mark(img, "slot_cost2000")
    if whole < float(book.marks["slot_cost2000"].get("thr", 0.9)):
        return False, float(whole), 0.0
    c0, c1 = SLOT_DIGIT_COLS
    got = _orange(to_norm(img)[y:y + h, x + c0:x + c1])
    ref = (book.tmpl["slot_digit2"] > 0).astype(np.uint8)
    if got.shape != ref.shape:
        return False, float(whole), 0.0
    union = int((got | ref).sum())
    digit = int((got & ref).sum()) / union if union else 0.0
    return digit >= 0.8, float(whole), digit


def choose_button(label_box: tuple[int, int, int, int]) -> NBox:
    """「选择」两个字的位置 → 按钮里可以点的范围。"""
    x, y, w, h = label_box
    return (x - 30.0, y - 6.0, w + 60.0, h + 12.0)


def load_event_defaults(folder: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        data = json.loads((folder / "events.json").read_text(encoding="utf-8"))
        for e in data.get("events", []):
            pick = (e.get("default") or {}).get("pick")
            if isinstance(pick, int):
                out[e["id"]] = pick
    except Exception:  # noqa: BLE001
        pass
    return out


def shops_summary(shops: list[dict[str, Any]], coins: int | None = None) -> str:
    """这一趟逛过的商店合起来的小结（给最后的结果用）。shops 是 Walk.result["shops"]。"""
    if not shops:
        return "这一趟没有路过商店。"
    n_relic = sum(1 for sh in shops for b in sh["bought"] if b[0] == "relic")
    n_char = sum(len(sh["bought"]) for sh in shops) - n_relic
    spent = sum(int(sh["spent"]) for sh in shops)
    gained = 400 * n_relic + 200 * n_char
    return (f"商店：逛了 {len(shops)} 家，买了遗物 {n_relic} 个、随机印记 {n_char} 个（多 {n_char} 名角色），"
            f"一共花了 {spent:,} 金币、换来 {gained:,} 分" + (f"；最后还剩 {coins:,} 金币" if coins is not None else "") + "。")


class Walk:
    name = "走几格再撤退"

    def __init__(self, runner: Runner, guild_mark: str = "guild_cile", guild_name: str = "慈乐之音",
                 steps: int = 3, pick: tuple[int, ...] = (0, 7, 11), event_defaults: dict[str, int] | None = None,
                 battle_timeout: float = 300.0, survey: bool = True, edge_thr: float = RT.EDGE_THR,
                 unknown_event: str = "ask", boss: str = "stop", teams_mid: int = 1, teams_final: int = 3, slot_bet: bool = False,
                 route_values: dict | None = None, team_mode: str = "order", defeat_retries: int = 2,
                 counters: dict | None = None, chars: "CH.CharBook | None" = None,
                 shop_buy: bool = True, shop_rate: float = ST.SHOP_MAX_RATE, shop_refresh_max: int = 600,
                 scout: bool = True, boss_avoid: tuple[str, ...] | list[str] = (), advisor: "AD.Advisor | None" = None,
                 damage: "DM.DamageBook | None" = None, damage_report: bool = True, adopt: bool = False,
                 tier: "TR.Tier | int | None" = None, reroll: dict | None = None, loot: "LT.LootBook | None" = None,
                 wins: "WN.WinBook | None" = None, keep_passes: int = 0,
                 auto_equip: bool = True, settle_score: int = 0, settle_spend: bool = False, final_stop: bool = False,
                 resume: bool = False):
        self.r = runner
        # 2026-11-24 晚用户要的三个开关：
        self.auto_equip = bool(auto_equip)           # 队伍换过人以后点「特别装备」→「自动装备」。关了就不碰装备（你自己配好的不会被换掉）
        self.settle_score = max(0, int(settle_score or 0))     # 走到最终首领跟前时估分达到这个数才算合格；0 = 不凹分数（照旧到了就撤退）
        self.settle_spend = bool(settle_spend)       # 合格以后由工具打最终首领并结算（用 1 张通行证）。不给 = 合格了停在最终首领跟前等你
        self.settled = ""                            # 这一趟在最终首领跟前定的是什么：fight / hold / redo
        # V1.0（2026-11-25 用户定的）：走到最终首领跟前不再自动撤退——没勾「使用门票」就停在那里、任务结束；勾了才打它、结算。
        # final_stop = 这一趟按这个规矩来（界面上的「开始」）；不给就是老样子（到了就撤退，自测和连续刷里别的用法）
        self.final_stop = bool(final_stop) or self.settle_score > 0 or self.settle_spend
        self.passes: int | None = None               # 迷宫首页上读到的通行证张数（读不出来是 None）
        self.keep_passes = max(0, int(keep_passes))  # 会用通行证的那种跑法（打最终首领）：通行证不多于这个数就不出发
        # 打赢过的队（2026-11-24）：按敌人记真机上的结果，下次凑得齐就直接上赢过的那一队；只输没赢过的队不再上。没给 = 不记也不用
        self.wins = wins
        self.shop_free_path: list[tuple[int, int]] = []     # 第一档：上一次说过的“绕开商店的路”（同一条路不重复说）
        self.fights: list[dict[str, Any]] = []       # 这一趟每一场战斗：区域、类型、敌人、输赢、游戏里几秒
        # 战利品（2026-11-24）：打通结算以后把「获得道具」清单读下来、记进账本（哪些是饰品、离目标还差多少）。没给账本也照读照存截图
        self.loot = loot
        self.loot_done = False
        self.loot_items: dict[str, int] = {}
        self.loot_info: dict[str, Any] | None = None
        self.guild_swipes = 0                        # 公会选择页上没看到要选的公会：朝现在这个方向拖了几次
        self.guild_nudges = 0                        # 看到名字但卡片只露出半张：朝那边拖了几次
        self.guild_dir = -1                          # 现在朝哪边拖：-1 = 手指往左（看右边的公会），+1 = 手指往右（看左边的公会）
        self.guild_turns = 0                         # 拖到头掉过几次头（两头都到过还没有 = 找遍了）
        self.guild_view: dict[str, float] | None = None      # 上一次拖之前这一屏读到的公会名字和位置（拖完一样 = 到头了）；None = 上一步不是拖
        self.guild_blank = 0                         # 连着几次一个公会的名字都没读出来
        self.effect_said = 0.0                       # 上一次记「迷宫遗物效果」是什么时候（同一个对话框不重复记）
        self.hands_seen = 0                          # 已经知道的“你动过模拟器、我让过手”的次数（多了就把记着的进度清掉，见 _sync_hands）
        self.team_empty = 0                          # 连着几次“队伍里没人、名单里也挑不出人”
        # 凹度档位（方案 2026-11-19 定，2026-11-24 做）：没给 = 第二档，就是以前一直用的打法。见 tiers.py
        self.tier: TR.Tier = tier if isinstance(tier, TR.Tier) else TR.get(tier)
        self.reroll = TR.reroll_of(reroll)           # 第一档凹什么：想要 / 不要的首领、事件至少给多少分
        self.ev_before: dict[str, Any] | None = None  # 刚走上一个事件格：走之前地图上的数字（事件完了拿来算这个事件给了多少）
        self.ev_area = 0
        self.sort_tries = 0                          # 这一场战斗的队伍编组里，为了把排序换回「等级」点开过几次「分类」
        self.sort_taps = 0                           # 「分类」里点过几次「等级」那个圆点还没选上
        self.slot_bets = 0                           # 这一个事件格里已经押过几次金币（「再较量一次！」只押一次；走上事件格时清零）
        self.bet_watch = 0                           # 刚押完：接下来这么多个画面各存一张原图（押完以后出什么还没见过，留着以后补认法）
        self.event_gains: list[float | None] = []    # 这一趟每个事件折成多少分
        # 挂机恢复（2026-11-24）：换日、连接出错以后游戏会退回标题画面，afk.Recovery 负责走回来；这里记“正在往回走”的状态
        self.afk = getattr(runner, "recovery", None)
        self.rejoin = False                          # 从游戏外面走回来的路上（回到一局里面的页面就清掉）
        self.rejoin_taps = 0
        self.pass_unsure = bool(adopt)               # 换过日 / 中途接手：出发前后的通行证数字没法比，就不比了
        # 真机伤害（2026-11-24 用户定的：测试的时候每场打完看一下输出，输出角色谁伤害高就调高比重）。没给 = 不看
        self.dmg = damage
        self.report_on = bool(damage_report) and damage is not None
        self.report_done = True                      # 这一场的伤害报告看过了没有（开打时置回 False）
        self.faces: list[np.ndarray | None] = []     # 开打前成员栏里每个位置的头像（打完去伤害报告里找同一张脸）
        self.face_names: list[str | None] = []       # 每个位置是谁
        self.faces_tab = 0                           # 这些头像是在首领战的第几队那个页签上截的（0 = 不是首领战）
        self.last_shares: dict[str, float] = {}      # 刚看的那张伤害报告里每个人占几成（没读全是空的）
        self.defeat_report = False                   # 这一场输在伤害不够：点「重新挑战」之前先看一眼伤害报告
        self.last_roles: dict[str, str | None] = {}  # 这一场上场的人各算哪种职能
        self.last_secs: float | None = None          # 这一场现实里用了多少秒
        self.last_game: int | None = None            # 这一场游戏里用了多少秒（读战斗画面右上角的计时器）
        # 战斗估算（2026-11-19 晚用户定的：按敌我双方的数值、技能、公式算，每场上算出来最好的一队）。没给就照旧按规则排
        self.advisor = advisor
        self.last_est: dict[str, Any] | None = None  # 这一场上场的那队估算下来会怎样（打完和真的结果一起记下来，以后拿来校）
        # 开局看首领（2026-11-18 用户定的）：到了区域 1 的地图先点进度条上的两个 BOSS 图标，看这一局区域 3 首领和最终首领是谁——
        # boss_avoid 里写了的首领直接撤退重开；别的就记下它们要什么（坦克、降魔攻……），招募时对应着拿
        self.scout, self.boss_avoid = bool(scout), [str(x) for x in (boss_avoid or [])]
        if self.tier.reroll:
            self.boss_avoid += [x for x in self.reroll["boss_avoid"] if x not in self.boss_avoid]
        self.scout_step = 0                          # 0 = 还没看区域 3 首领，1 = 还没看最终首领，2 = 看完了（或者看不了）
        self.scout_wait, self.scout_miss = False, 0  # 刚点了图标、在等「魔物详情」弹出来；点了没反应的次数
        self.bosses: list[str | None] = [None, None]  # 这一局的 [区域 3 首领, 最终首领]（对策表里的名字；没认出来是 None）
        self.boss_wants: dict[str, list[str]] = {"roles": [], "tags": []}     # 后面两个首领要的职能 / 效果：招募时名单里还没有就优先拿
        self.roster_tags: set[str] = set()           # 名单里的人已经有哪些特点（上一次编队时看的）
        self.no_mech = False                         # 这一场的敌人非要某种机制不可，而名单里一个带的都没有：只打这一次，输了不重打
        self.unknown_joins = 0                       # 上一次看名单以后，加入了几个没认出名字的角色
        self.roster_scanned = False                  # 这一局在队伍编组里把名单看过一遍了没有（没看过就不知道开局那三个人是谁）
        self.roster_heal = False                     # 名单里有没有“有奶”的人（职能是治疗，或者技能能给全队回血）
        self.run_units: dict[str, tuple[str | None, str | None]] = {}     # 这一局已经有的角色：全名 → (属性, 职能)。编队时看名单、角色加入时读名字，两边都往里记
        self.run_unnamed: list[tuple[str | None, str | None]] = []       # 名单里认不出名字的卡：(属性, 职能)（上一次编队时看的）
        self.ime_taps = 0                            # 输入法被弹出来的次数（不该发生；发生了点「确定」收起来）
        self.tries: list[dict[str, Any]] = []        # 这一场前面每次是怎么输的 [{"how": …, "team": [名字]}]：下一次怎么编队看它
        self.hp_log: list[tuple[float, list[float]]] = []     # 这一场战斗中隔一会儿读一次的血量 [(第几秒, [最前面的人 … 最后面的人])]
        # 商店：shop_buy = 买不买；shop_rate = 平时只买“每 1 分不超过这么多金币”的；shop_refresh_max = 更新一次最多肯花多少
        self.shop_buy, self.shop_rate, self.shop_refresh_max = bool(shop_buy), float(shop_rate), int(shop_refresh_max)
        self.shop: dict[str, Any] | None = None      # 正在逛的这家商店：更新了几次、买了什么、哪件核对不上不买了
        self.shop_factor: float | None = None        # 这一局的商店打几折（价是平常的几成；None = 还没逛过商店）。见 strategy.shop_discount
        self.shops: list[dict[str, Any]] = []        # 这一趟逛过的每家商店的小结
        # 编队方式："role" = 认卡片上的职能和属性，按 strategy.py 的规则挑人（阶段 3）；"order" = 老办法，按名单顺序补满
        self.team_mode = team_mode
        self.defeat_retries = max(0, int(defeat_retries))   # 一场战斗打输以后最多再打几次；再输就撤退重开
        if self.tier.retries is not None:            # 第三、四档多给几次
            self.defeat_retries = max(self.defeat_retries, self.tier.retries)
        self.tb: dict[str, Any] | None = None        # 这一场的编队进度（看了哪些页签、打算带谁、还要点谁）
        self.attempt = 0                             # 这一场是第几次打（0 = 第一次）
        self.losses = 0                              # 这一趟一共输了几场
        self.boss_extra = 0                          # 首领战输过以后多编几队
        self.weak: str | None = None                 # 这一场敌人的弱点属性
        self.counters: dict[str, Any] = dict((counters or {}).get("enemies") or {})     # 对策表：敌人名字 → 攻略里的对策
        self.unseen_group: dict[str, Any] = dict((counters or {}).get("unseen_group") or {})   # 极难格子里一排敌人、认不出是哪一组时用的对策（要范围输出）
        self.enemy: str | None = None                # 这一场认出来的敌人（对策表里的名字）
        self.tweak: dict[str, Any] | None = None     # 对策表里这个敌人的那一条
        self.enemy_done, self.enemy_tries = False, 0
        self.chars: CH.CharBook = chars if chars is not None else CH.CharBook()      # 头像库：头像 → 名字（没给就只在这一趟里记）
        self.join_seen: list | None = None           # 这一次「角色加入」已经读过了（存的是读到的名字）
        self.join_tries = 0
        self.last_team: list[str] = []               # 这一场上场的人（认得出名字的写名字，认不出的写 职能/属性）
        self.last_had: list[str] = []                # 这一场上的队带着哪种保命的人（"tank" = 有坦克或肉的前排顶在最前面，"heal" = 有会给全队回血的人）
        self.run_wins: dict[str, int] = {}           # 这一局里谁赢过几场（赢过的人编队时优先沿用）
        self.last_front: tuple[str | None, float] | None = None     # 这一场顶在最前面的“替身坦克”（名字, 耐打程度）；队里有真坦克或没人顶是 None
        self.no_info: set[str] = set()               # 认出了名字、但角色表里还没有资料的人
        self.battle_kind = "normal"
        self.roster: dict[str, int] = {}             # 名单里各职能有几个人（上一次编队时数的，加上之后招的）
        self.recruit_side: str | None = None         # 招募时往物理队还是法队凑（上一次编队时看名单定的）
        self.eff_tank = False                        # 这一场首领战，游戏在「对首领的有效效果」里写着“坦克型”
        self.lost_how: str | None = None             # 这一场上一次是怎么输的："timeout" 时间到了人还活着 / "wiped" 队伍倒了 / None 看不出来
        self.targets: str | None = None              # 这一场的敌人是一群（"multi"）还是一个（"single"）：战斗准备页面上看的
        self.full_tabs: set[str] = set()             # 这一场编队时，哪些页签满了一屏（后面可能还有没看到的角色）
        self.series: dict[str, int] = {}             # 各遗物系列现在几级（自己记的）
        self.pick_auto: list[int] | None = None
        self.battle_logged = False                   # 这一场的结果已经记进日志了
        self.guild_mark, self.guild_name = guild_mark, guild_name
        self.steps = max(0, int(steps))              # 0 = 只看全图、排路线，不走
        self.survey, self.edge_thr = survey, edge_thr
        self.route_values = dict(route_values or {})  # 每种格子值多少分（覆盖 plan.ROUTE_VALUES）；极难数相同的路线之间按它挑
        self.unknown_event = unknown_event           # 没见过的事件 / 认不出的选项："ask" 交给你，"first" 先选第 1 项
        self.slot_bet = bool(slot_bet)               # 「再较量一次！」押不押金币：默认不押（用户 2026-11-26 21:30 定的）；设置里 walk.slot_bet = true 才押
        self.boss = boss                             # "stop" 见到首领就撤退；"mid" 打区域 3 的首领；"all" 最终首领也打
        self.teams_mid, self.teams_final = max(1, min(3, teams_mid)), max(1, min(3, teams_final))
        if self.tier.boss_mid_teams is not None:     # 第四档：区域 3 首领一开始就多编一队
            self.teams_mid = max(self.teams_mid, min(3, self.tier.boss_mid_teams))
        self.cleared = False                         # 最终首领打完了，正在走结算
        self.at_final = False                        # 走到最终首领跟前了（这一趟不打，撤退）
        self.chest_taps = 0
        self.team_expect: tuple[int, int, int] | None = None     # 刚点了名单里的一格：（成员栏应该变成几个, 那一格的位置）
        self.choice_wait = 0
        self.area = 0                                # 现在在第几个区域
        self.area_map: AreaMap | None = None
        self.plan: Plan | None = None
        self.col = 0                                 # 在这个区域里已经走到第几列（0 = 还在出发点）
        self.cur_ly: int | None = None               # 现在站的那格在哪一行
        self.pending: TL.Tile | None = None          # 点了、还没确认移动的那一格
        self.restart = False                         # 撤退是因为极难走不到（外面可以据此重开）
        self.surveys: list[dict[str, Any]] = []
        self.hud: dict[str, int | None] = {"chars": None, "relics": None, "chests": None, "coins": None}   # 地图上最近一次读到的四个数字
        self.final_score: int | None = None          # 走到最终首领跟前时算的：打掉它的话最终分数是多少
        self.pick = "auto" if pick == "auto" else tuple(pick)
        self.event_defaults = event_defaults or {}
        self.battle_timeout = battle_timeout
        self.pass_before: np.ndarray | None = None
        self.departed = self.seen_confirm = self.seen_pick3 = self.ended = False
        if adopt:                                    # 接手：游戏已经停在公会选择页上了（上一局在换日时没了），当成已经点过「出发」
            self.departed = True
        # 接着打进行中的一局（2026-11-27 用户要的“从中途打”）：开始前勾了才有。游戏里有一局打到一半时，点「出发」会直接回到那一局的地图——
        # 没勾：照旧停下，不动它；勾了：从地图接手，后面和工具自己开的局一样走。只有地图能接（地图上看得到区域、数字和能走的格子，
        # 路线是从现在站的地方往后排的）；停在战斗准备上可以先点「查看地图」回去，别的页面（编队、战斗中、事件……）前面发生了什么不知道，不接。
        self.resume = bool(resume)
        self.took_over = False                       # 这一局是接手的（出发前的通行证数字、前面走过的格子都没看到）
        self.resume_said = False
        self.own_said = False                        # “还没扫描过角色，分不出哪些是自己的”这句话说过了（一局说一次）
        self.mid_area = False                        # 接手以后还没看过图：第一次看图是从区域中途看起的
        self.pass_block: str | None = None           # 勾了接着打时：通行证不够出发的那句话先留着，点了「出发」真到了公会选择页（没有进行中的一局）再停
        self.want_retreat = False
        self.why_retreat = ""
        self.moves: list[str] = []                   # 走过的格子类型
        self.battles = 0
        self.fighting = False                        # 点了「战斗开始」，还没见到 WIN!
        self.arriving = False                        # 刚确认了移动，这一格的内容（战斗 / 三选一 / 事件 / 商店）还没弹出来
        self.arrive_wait = 0
        self.team_changed = self.equip_done = self.auto_done = False
        self.map_idle = 0
        self.win_wait = 0
        self.team_retry = 0
        self.beat = 0.7                              # 点完名单里的格子后停这么久再看（对勾要半秒左右才盖上去）
        self.patience = 1.0                          # 各种“再等等看”的时长倍数（测试里调小）
        self.result: dict[str, Any] = {}

    # ---- 小工具 ----
    def _read_passes(self, img: np.ndarray) -> int | None:
        return read_passes(img)

    def _same_pass(self, img: np.ndarray) -> tuple[bool, float]:
        if self.pass_unsure or self.pass_before is None:     # 换过日（通行证可能每天会变）/ 中途接手：不比，按“对得上”算
            return not self.cleared, 0.0
        now = self.r.book.crop(img, "pass_count")
        diff = float(np.abs(now.astype(np.int16) - self.pass_before.astype(np.int16)).mean())
        return diff < 2.5, diff

    def _pass_check(self, img: np.ndarray) -> tuple[bool, float, str, int | None]:
        """回到迷宫首页：通行证对不对得上。返回（对得上吗, 数字那一块的图像差异, 要说的话, 现在读到几张）。

        游戏每天北京时间 12 点会发一张通行证（2026-11-27 两台电脑上都撞上了：一趟跨过 12 点，撤退回来比出发前多 1 张，
        以前只比“数字那一块图像变没变”，把变多也当成出错、整次任务停掉）。所以读得出数字时按数字比，只有**变少**才算对不上：
          撤退回来：不比出发前少就对；打通结算回来：这一局用掉 1 张，不比“出发前 - 1”少就对。
        数字读不出来时照旧比图像（撤退：应该没变；打通：应该变了）。"""
        same, diff = self._same_pass(img)
        if self.pass_unsure or self.pass_before is None:
            return True, diff, "", None
        after = self._read_passes(img)
        before = self.passes
        if not self.cleared and same:                # 撤退回来、数字那一块和出发前一模一样：没变，不用再看读出来的数（免得读错一位闹误会）
            return True, diff, "", after
        if before is None or after is None or not 0 <= after <= 999:
            return ((not same) if self.cleared else same), diff, "", after
        expect = before - 1 if self.cleared else before
        if after < expect:
            return False, diff, f"出发前 {before} 张，现在 {after} 张，比应该有的 {expect} 张少了 {expect - after} 张", after
        if after > expect:
            return True, diff, (f"出发前 {before} 张、现在 {after} 张，比应该有的 {expect} 张多 {after - expect} 张："
                                "游戏每天北京时间 12 点会发通行证，不是出错"), after
        return True, diff, "", after

    def _tap_wait(self, s: Seen, box: NBox, label: str, think: bool = False, timeout: float = 6.0) -> str:
        res = self.r.tap(s, box, label, think)
        if res != "changed":
            self.r.wait_leave(s.page, timeout)
        return res

    def _read_hud(self, img: np.ndarray) -> None:
        """读地图上的角色数 / 遗物数 / 宝箱数 / 金币。前三个一局里只增不减：读到比上次小的就不信（多半是漏了一位）。"""
        h = HUD.read_hud(self.r.book, img).as_dict()
        new = dict(self.hud)
        for k, v in h.items():
            if v is None:
                continue
            if k != "coins" and new[k] is not None and v < new[k]:
                self.r.log.event("hud_drop", field=k, was=new[k], read=v)
                continue
            new[k] = v
        if new != self.hud:
            self.hud = new
            self.r.log.event("hud", **new, moves=len(self.moves))

    def _route_values(self) -> dict:
        """排路线用的每种格子的分值。商店那一项写的是 "auto"（默认）时按现在手里的金币现算；不买东西时商店不值分。"""
        v = dict(self.route_values)
        if not isinstance(v.get("shop", "auto"), (int, float)):
            v["shop"] = shop_value(self.hud["coins"], self.area) if self.shop_buy else 0.0
        return v

    def _say_final_score(self) -> None:
        c, rl = self.hud["chars"], self.hud["relics"]
        n, e = self.moves.count("normal"), self.moves.count("extreme")
        if c is None or rl is None:
            self.r.log.say("      左下角的角色数 / 遗物数没读出来，这一趟算不了分数。")
            return
        self.final_score = score_if_cleared(c, rl, n, e)
        self.r.log.say(f"      现在：角色 {c}、遗物 {rl}，普通战 {n} 场、极难 {e} 场"
                       + (f"，金币还剩 {self.hud['coins']}" if self.hud["coins"] is not None else "")
                       + f"。把最终首领打掉的话，最终分数是 {self.final_score:,}。")
        self.r.log.event("final_score", score=self.final_score, chars=c, relics=rl, normal=n, extreme=e, coins=self.hud["coins"])

    def _boss_ok(self) -> bool:
        return (self.boss in ("mid", "all") and self.area == 3) or (self.boss == "all" and self.area == 5)

    def _final_gate(self) -> None:
        """走到最终首领跟前了（final_stop 才会来）。V1.0 的规矩（2026-11-25 用户定的）：
        - 没勾「使用门票」：停在这里，任务结束（不撤退、不打）——这一局交给你；分数那一格不看。
        - 勾了：估分没到你定的分数（定了的话）→ 撤退重打，门票不用、不算一局；到了（或者没定分数）→ 打最终首领，打完游戏自动结算、用 1 张门票。
        打最终首领只有 settle_spend（界面上那个勾，每次都要重新勾）给了才会发生。"""
        r = self.r
        sc, want = self.final_score, self.settle_score
        if not self.settle_spend:
            self.settled = "hold"
            r.log.event("settle", decision="hold", score=sc, want=want)
            raise Hold("走到最终首领跟前了" + (f"（把它打掉能得 {sc:,} 分）" if sc is not None else "") + "。这一次没有勾「使用门票」，所以停在这里、任务结束："
                       "你自己打掉它就结算；不想要这一局就在地图上点「撤退（无报酬）」")
        if want > 0 and (sc is None or sc < want):
            self.settled, self.restart = "redo", True
            self.why_retreat = (f"估分 {sc:,} 不到你定的 {want:,}" if sc is not None else f"分数没算出来，没法和你定的 {want:,} 比") + "，不结算，撤退重打"
            r.log.event("settle", decision="redo", score=sc, want=want)
            return
        if self.passes is not None and self.passes <= self.keep_passes:
            self.settled = "hold"
            r.log.event("settle", decision="hold", score=sc, want=want, why="keep_passes", passes=self.passes)
            raise Hold(f"走到最终首领跟前了，但门票只剩 {self.passes} 张、设置里说要留 {self.keep_passes} 张：不打最终首领，停在它跟前交给你")
        self.settled, self.boss = "fight", "all"
        r.log.say((f"      估分 {sc:,}" + (f" 达到你定的 {want:,}" if want > 0 else "") if sc is not None else "      分数没算出来（你没定分数线）")
                  + "：打最终首领。打完游戏会自动结算，用掉 1 张门票（这是你这一次勾了「使用门票」）。")
        r.log.event("settle", decision="fight", score=sc, want=want)

    def _must_tags(self) -> set[str]:
        """这一场的敌人非要不可的机制（对策表里的 must，比如好朋友X 的持续伤害）。没有就是空的。"""
        return set((self.tweak or {}).get("must") or [])

    def _no_mech_for_sure(self) -> bool:
        """在「战斗准备」上：这个敌人非要某种机制不可，而这一局的人里**确定**一个带的都没有——那就不打了（2026-11-24 好朋友X：
        没拿到带持续伤害的角色，连打三次都是 90 秒打不完）。“确定”= 这一局的人名字都认得、攻略表里都有资料；有认不出的就不在这里下结论，
        进队伍编组看了名单和「有效效果」页签再说（见 _on_team_role 里的 no_mech）。这一局还没在队伍编组里看过名单（第一场战斗）也不下结论。
        返回 True = 已经定了要撤退重开。"""
        must = self._must_tags()
        if self.attempt == 0:
            self.no_mech = False                     # 新的一场：重新看
        if not must or self.attempt > 0 or self.want_retreat or not self.run_units or not self.roster_scanned:
            return False
        names = list(self.run_units)
        have = [n for n in names if must & self.chars.tags(n)]
        unsure = [n for n in names if not self.chars.knows(n)]
        if have or unsure or self.run_unnamed or self.unknown_joins:
            return False
        what = "、".join(ST.TAG_CN.get(t, t) for t in sorted(must))
        kind = KIND_CN.get(self.battle_kind, self.battle_kind)
        self.want_retreat, self.restart = True, True
        self.why_retreat = f"{kind}·{self.enemy} 非要{what}不可，这一局的 {len(names)} 个人里一个带的都没有"
        self.arriving = False
        self.r.log.say(f"      {self.why_retreat}：打也是白打，不打了，撤退重开。")
        self.r.log.event("no_mech", enemy=self.enemy, must=sorted(must), sure=True, roster=len(names))
        return True

    def _boss_stop_reason(self) -> str:
        if self.boss == "mid" and self.area == 5:
            return "下一格是最终首领（打完会自动结算、用掉通行证，所以不打）"
        return "下一格是首领"

    def _boss_teams(self) -> int:
        if self.boss_extra:
            return min(3, (self.teams_final if self.area == 5 else self.teams_mid) + self.boss_extra)
        return self._boss_teams_base()

    def _boss_teams_base(self) -> int:
        return self.teams_final if self.area == 5 else self.teams_mid

    def _choose_tile(self, rc: list[TL.Tile]) -> TL.Tile | None:
        """按路线选下一格。没有地图（没开看全图）时退回老办法：有极难走极难，否则最上面。返回 None = 该撤退了。"""
        r, m = self.r, self.area_map
        if m is None:
            ex = [t for t in rc if t.label == "extreme"]
            if self.tier.extreme == "avoid":         # 保通关：能不走极难就不走
                return ([t for t in rc if t.label != "extreme"] or rc)[0]
            return ex[0] if ex else rc[0]
        known = sorted(m.rows.get(self.col + 1, {}))

        def row_of(t: TL.Tile) -> int:
            """这个发光的格子在地图里是哪一行。差几个像素就对到看全图时记下的那一行上（行高在路线里是当键用的）。"""
            near = min(known, key=lambda y: abs(y - t.ly), default=t.ly)
            return near if abs(near - t.ly) <= 12 else t.ly

        by_row = {row_of(t): t for t in rc}
        glow = sorted(by_row)
        if self.col >= 1 and self.cur_ly is not None:
            guess = m.nexts(self.col, self.cur_ly, self.edge_thr)
            if guess != glow:
                r.log.say(f"      注意：看全图时判断从这格能去 {'/'.join(row_name(y) for y in guess) or '（无）'}，"
                          f"实际发光的是 {'/'.join(row_name(y) for y in glow)}，以实际为准。")
                r.log.event("edge_mismatch", area=self.area, col=self.col, ly=self.cur_ly, guess=guess, glow=glow)
        for ly, t in by_row.items():                 # 走到跟前看得更清楚：补上这一列的格子类型
            m.set_tile(self.col + 1, ly, t.kind, True)
        plan = make_plan(m, self.col + 1, glow, self.edge_thr, self._route_values(), self.tier.extreme)
        self.plan = plan
        if not plan.ok:
            self._give_up(plan)
            return None
        alt = self._avoid_shop(m, self.col + 1, glow, plan)
        if alt is None:
            return None
        self.plan = plan = alt
        want = plan.row_for(self.col + 1)
        return by_row[want] if want in by_row else min(rc, key=lambda t: abs(t.ly - want))

    def _avoid_shop(self, m: AreaMap, col: int, starts: list[int], plan: Plan) -> Plan | None:
        """第一档：这个区域不走商店（默认只有区域 2——用户定的“第二层如果必须走商店就重开”）。
        选好的路不过商店：原样用。过商店：有不过商店、极难又一列不落的路就改走那条；没有（必须走商店）→ 安排撤退重开，返回 None。"""
        if not (self.tier.reroll and self.area in self.reroll["no_shop_areas"]) or not plan.ok:
            return plan
        if not any(m.rows.get(c, {}).get(ly) == "shop" for c, ly in plan.path):
            return plan
        r = self.r
        alt = make_plan(m, col, starts, self.edge_thr, self._route_values(), self.tier.extreme, ban=("shop",))
        if alt.ok:
            if alt.path != self.shop_free_path[-len(alt.path):]:
                self.shop_free_path = list(alt.path)
                r.log.say(f"      原本的路要过商店；{self.tier.name}在区域 {self.area} 不走商店，改走：{self._plan_text(alt)}。")
                r.log.event("shop_avoid", area=self.area, col=self.col, path=[[c, ly] for c, ly in alt.path], was=[[c, ly] for c, ly in plan.path])
            return alt
        why = (f"区域 {self.area} 绕不开商店" + ("（不过商店就打不全极难）" if alt.path else "")
               + f"（{self.tier.name}：第二层必须走商店就重开）")
        r.log.say(f"      {why}：撤退重开。")
        r.log.event("shop_restart", area=self.area, col=self.col, path=[[c, ly] for c, ly in plan.path])
        self.want_retreat, self.why_retreat, self.restart = True, why, True
        return None

    def _give_up(self, plan: Plan) -> None:
        cols = "、".join(f"第 {c} 列" for c in plan.blocked) if plan.blocked else "后面"
        why = f"区域 {self.area} {cols}的极难走不到" if plan.path else f"区域 {self.area} 从这里走不到尽头（地图可能没看准）"
        self.r.log.say(f"      {why}：撤退。")
        self.r.log.event("blocked", area=self.area, col=self.col, blocked=plan.blocked, extremes=plan.extremes, wanted=plan.wanted)
        self.want_retreat, self.why_retreat, self.restart = True, why, bool(plan.path)

    def _plan_text(self, plan: Plan) -> str:
        m = self.area_map
        assert m is not None
        parts = []
        for c, ly in plan.path:
            kind = m.rows.get(c, {}).get(ly)
            parts.append(row_name(ly) + (f"({KIND_NAMES.get(kind, '？')})" if kind else ""))
        return " → ".join(parts)

    def _do_survey(self, s: Seen, rc: list[TL.Tile]) -> None:
        r = self.r
        mid = self.took_over and self.mid_area      # 接手的一局、第一次看图：是从这个区域的中途开始看的
        sv = Survey(r, self.area, self.edge_thr, mid=True) if mid else Survey(r, self.area, self.edge_thr)
        m = sv.run(s)
        if m is None:                                # 拖的中途画面变了：回主循环重新看
            return
        self.area_map = m
        self.mid_area = False
        if mid:
            r.log.say(f"      区域 {self.area} 从现在站的地方往后还有 {m.last} 列（下面的“第 1 列”是你现在这格的下一列）：")
        else:
            r.log.say(f"      区域 {self.area} 一共 {m.last} 列：")
        for line in m.describe(self.edge_thr):
            r.log.say("        " + line)
        plan = make_plan(m, 1, sorted(t.ly for t in rc), self.edge_thr, self._route_values(), self.tier.extreme)
        self.plan = plan
        if plan.ok:
            alt = self._avoid_shop(m, 1, sorted(t.ly for t in rc), plan)
            if alt is None:                          # 第一档：这个区域绕不开商店，已经安排撤退重开
                self.surveys.append({"area": self.area, "cols": m.last, "extreme_cols": m.extreme_cols(), "ok": False, "blocked": [],
                                     "path": [[c, ly] for c, ly in plan.path], "value": plan.value, "ties": plan.ties,
                                     "kinds": [m.rows.get(c, {}).get(ly) for c, ly in plan.path], "shop_forced": True})
                return
            self.plan = plan = alt
        ex = m.extreme_cols()
        self.surveys.append({"area": self.area, "cols": m.last, "extreme_cols": ex, "ok": plan.ok, "blocked": plan.blocked,
                             "path": [[c, ly] for c, ly in plan.path], "value": plan.value, "ties": plan.ties,
                             "kinds": [m.rows.get(c, {}).get(ly) for c, ly in plan.path]})
        if plan.ok:
            if not ex:
                note = "　（这个区域没有极难）"
            elif self.tier.extreme == "avoid":
                note = f"　（{self.tier.name}：能不走极难就不走，这条路上有 {plan.extremes} 个）"
            elif plan.blocked:
                note = (f"　（极难在{'、'.join(f'第 {c} 列' for c in ex)}，其中{'、'.join(f'第 {c} 列' for c in plan.blocked)}走不到；"
                        f"{self.tier.name}不为这个重开，打能走到的 {plan.extremes} 个）")
            else:
                note = f"　（极难在{'、'.join(f'第 {c} 列' for c in ex)}，都能走到）"
            r.log.say(f"      路线：{self._plan_text(plan)}" + note)
            if plan.ties > 1:
                r.log.say(f"      极难数一样的走法有 {plan.ties} 条，挑了路上格子最值分的这条（极难以外约 {plan.value:.0f} 分）。")
            r.log.event("plan", area=self.area, path=[[c, ly] for c, ly in plan.path], extremes=plan.extremes,
                        value=plan.value, ties=plan.ties)
        else:
            self._give_up(plan)

    def _after_event(self) -> None:
        """一个事件处理完、回到地图：算它给了多少（角色 200、遗物 400、5 金币 1 分）。第一档在前几个区域里给得少就撤退重开。"""
        r = self.r
        before, area = self.ev_before or {}, self.ev_area
        self.ev_before = None
        gain = TR.event_gain(before, self.hud)
        self.event_gains.append(gain)
        r.log.event("event_gain", area=area, gain=gain, before=before, after=dict(self.hud))
        if gain is None:
            return
        r.log.say(f"      刚才那个事件拿到的东西折成分数约 {gain:.0f}。")
        low, areas = self.reroll["event_min"], self.reroll["areas"]
        if self.tier.reroll and low > 0 and area <= areas and gain < low and not self.want_retreat:
            self.want_retreat, self.restart = True, True
            self.why_retreat = f"区域 {area} 的事件只拿到约 {gain:.0f} 分（{self.tier.name}：前 {areas} 个区域的事件低于 {low:.0f} 分就重开）"
            r.log.say(f"      {self.why_retreat}：撤退重开。")
            r.log.event("event_restart", area=area, gain=gain, low=low)

    def _on_daychange(self, s: Seen) -> None:
        """「日期变更」：国服每天 5 点换日，之后第一次和服务器说话就弹它，点「确认」游戏退回标题画面。"""
        r = self.r
        r.log.event("daychange", departed=self.departed, in_run=self.seen_pick3, moves=len(self.moves))
        if self.afk is None or not self.afk.on:
            r.log.shot(s.img, "daychange", png=True)
            raise Halt("游戏换日了（每天 5 点）：点「确认」以后会回到标题画面。现在没开“自己走回迷宫”（设置里的 walk.recover），所以停在这里")
        if not self.afk.can_see():
            r.log.shot(s.img, "daychange", png=True)
            raise Halt("游戏换日了（每天 5 点）：点「确认」以后会回到标题画面。" + AFK_BLIND)
        self.afk.begin("游戏换日了（每天 5 点）")
        self.rejoin, self.pass_unsure = True, True
        if not self.seen_pick3 and not self.ended:   # 这一局还没真的开始（「出发」那一下被换日挡回来了）：回到首页从头出发
            self.departed = self.seen_confirm = False
        self._tap_wait(s, BOX["daychange.ok"], "确认（日期变更：游戏会回到标题画面）")

    def _rejoined(self, s: Seen) -> None:
        """走回一局里面了：把“正在点 / 正在打”这些半截状态清掉，按现在看到的页面接着走。"""
        if self.afk is not None:
            self.afk.done(s.res.name)
        self.r.log.event("rejoined", page=s.page, moves=len(self.moves), was_fighting=self.fighting)
        self.rejoin, self.rejoin_taps, self.pass_unsure = False, 0, True
        self.departed = self.seen_confirm = True
        self.fighting = self.arriving = False
        self.pending, self.tb = None, None
        self.map_idle = self.arrive_wait = 0

    BATTLE_TICK = 60.0                               # 计时器这么久没动过，才算“这场仗卡住了”（放 UB 动画时它会停几秒，不会停这么久）

    def _battle_cap(self) -> tuple[float, int]:
        """这场战斗最多等多久（秒），和它是几队的仗。battle_timeout 是**一队**的时间：首领战派了几队就乘几——
        几队是一队打完（或者倒了）下一队接着上，画面一直是战斗中，中间不会出 WIN!。
        （2026-11-26 玩家反馈：最终首领派了 3 队，300 秒不够，被当成“打了超过 300 秒还没结束”停了。）"""
        teams = max(1, self._boss_teams()) if self.battle_kind == "boss" else 1
        return float(self.battle_timeout) * teams, teams

    def _watch_battle(self) -> None:
        """战斗中：不点任何东西，等到出现 WIN!。打太久或者画面一直不认识（可能是打输了）就停。

        “太久”：过了 _battle_cap 的时间、而且计时器已经 BATTLE_TICK 秒没动过。计时器还在走就说明仗是真的还在打
        （游戏开的不是 4 倍速、UB 动画多的时候会比平常久），那就接着等，最多等到两倍。"""
        r = self.r
        r.log.say("      …战斗中（AUTO），等它打完")
        r.log.event("battle_start", n=self.battles + 1)
        t0 = last_battle = time.time()
        cap, teams = self._battle_cap()
        last_tm: int | None = None                   # 计时器上一次读到的数，和它最后一次变化是什么时候
        last_tick = t0
        said_long = False
        other = 0
        self.hp_log = []
        left: int | None = None                      # 计时器上最后一次读到还剩多少秒
        lost_since: float | None = None              # 从什么时候开始一直是不认识的画面
        while True:
            r.check()
            s = r.look()
            now = time.time()
            lost_since = None if s.res.known else (lost_since or now)
            if lost_since is not None and now - lost_since > 25.0 and self.afk is not None and self.afk.on:
                # 放 UB 动画时画面也会不认识几秒，但不会连着 25 秒：多半是连接出错之类的系统弹窗，交回主流程让挂机恢复看一眼
                r.log.say("      …战斗画面换成了一个不认识的画面，已经 25 秒了：交回去看是不是系统弹窗")
                r.log.event("battle_end", seconds=round(now - t0, 1), result="unknown")
                return
            game = VB.LIMIT - left if left is not None else None
            took = f"现实 {now - t0:.0f} 秒" + (f"、游戏里约 {game} 秒（计时器最后读到还剩 {left} 秒）" if game is not None else "")
            if s.page in ("win_crown", "win", "win_next"):
                self.last_secs, self.last_game = round(now - t0, 1), game
                r.log.say(f"      …打赢了，用时{took}")
                r.log.event("battle_end", n=self.battles + 1, seconds=round(now - t0, 1), game=game, result="win", battle=self.battle_kind,
                            attempt=self.attempt, team=list(self.last_team), enemy=self.enemy, est=self.last_est)
                self.chars.record_battle([n for n in self.last_team if "/" not in n], self.battle_kind, round(now - t0, 1), True)
                self.chars.save()
                self._remember(True)
                for n in self.last_team:
                    if "/" not in n:
                        self.run_wins[n] = self.run_wins.get(n, 0) + 1
                self.battle_logged = True
                return
            if s.page == "defeat":
                self.last_secs, self.last_game = round(now - t0, 1), game
                r.log.say(f"      …打输了，用时{took}")
                r.log.event("battle_end", n=self.battles + 1, seconds=round(now - t0, 1), game=game, result="lose", battle=self.battle_kind,
                            attempt=self.attempt, team=list(self.last_team), enemy=self.enemy, est=self.last_est)
                self.chars.record_battle([n for n in self.last_team if "/" not in n], self.battle_kind, round(now - t0, 1), False)
                self.chars.save()
                self._remember(False)
                self.battle_logged = True
                return
            if s.page == "battle":
                last_battle, other = now, 0
                tm = VB.read_timer(r.book, s.img)    # 游戏是 4 倍速、放 UB 动画时计时器会停，现实秒数说明不了打了多久；计时器才是真的
                if tm is not None and tm != last_tm:
                    last_tm, last_tick = tm, now
                if tm is not None and (left is None or tm <= left):
                    left = tm
                if self.team_mode == "role":         # 记一下每个人还剩多少血：打输了靠它分“从前面一个个倒”还是“全队一起崩”
                    hp = CD.battle_hp(s.img, len(self.last_team) or CD.SLOTS)
                    if not self.hp_log or hp != self.hp_log[-1][1]:
                        self.hp_log.append((round(now - t0, 1), hp))
                        del self.hp_log[:-600]
            elif s.res.known and not s.res.wait:
                other += 1
                if other >= 3:                       # 出现了别的认识的页面：交回主流程处理
                    r.log.event("battle_end", seconds=round(now - t0, 1), result=s.page)
                    return
            over = now - t0 > cap
            if over and now - last_tick <= self.BATTLE_TICK and now - t0 <= 2 * cap:
                over = False                         # 计时器还在走：仗是真的还在打，接着等（最多等到两倍）
                if not said_long:
                    said_long = True
                    r.log.say(f"      …这场已经打了 {now - t0:.0f} 秒，比平常久；计时器还在走，接着等（最多等到 {2 * cap:.0f} 秒）")
                    r.log.event("battle_long", seconds=round(now - t0, 1), cap=cap, teams=teams, timer=last_tm)
            if over or now - last_battle > 60.0:
                files = r.log.dump_recent("battle")
                r.log.event("halt", why="battle", shots=files, seconds=round(now - t0, 1), cap=cap, teams=teams)
                if now - last_battle > 60.0:
                    raise Halt("战斗画面离开超过 1 分钟还没出现 WIN!（可能是打输了，失败画面我还没见过）")
                how = f"首领战派了 {teams} 队，每队按 {self.battle_timeout:.0f} 秒算" if teams > 1 else f"一场按 {self.battle_timeout:.0f} 秒算"
                still = "计时器还在走，但已经等到两倍了" if now - last_tick <= self.BATTLE_TICK else f"计时器也有 {now - last_tick:.0f} 秒没动过了"
                frozen = ""
                if now - last_tick > 0.8 * (now - t0) and last_tm is not None:
                    # 几乎从开打起计时器就停在同一个数上：不是打得慢，是游戏卡住了。2026-11-27 一位玩家连着两次卡在优衣（公主）的大招动画上
                    # （计时器停在 1:25，画面是她的特写，背景还在动）——这是游戏 / 模拟器那边的事，工具战斗中什么都不点
                    first = [n for n in self.last_team if "/" not in n and not self.run_wins.get(n)]
                    frozen = (f"。计时器从还剩 {last_tm} 秒起就没动过：游戏多半是卡在某个角色的大招动画上了（不是工具点错了）。"
                              f"场上是 {'、'.join(self.last_team)}"
                              + (f"；其中这一局第一次上场的是 {'、'.join(first)}，先怀疑她们" if first and len(first) < len(self.last_team) else "")
                              + "。可以手动点一下画面看能不能跳过；老是卡在同一个角色上的话，在游戏的设定里把大招动画关掉再试")
                    r.log.event("battle_frozen", timer=last_tm, team=list(self.last_team), first=first, seconds=round(now - t0, 1))
                raise Halt(f"这场战斗打了超过 {now - t0:.0f} 秒还没结束（{how}；{still}）{frozen}")
            r.pause(0.5)

    # ---- 各页面 ----
    def _on_pick3(self, s: Seen) -> None:
        r = self.r
        key, score, sure = r.book.classify(s.img, PICK_KEYS)
        if key is None or sure < 0.3:
            r.log.shot(s.img, "pick3_count_unreadable", png=True)
            raise Halt(f"「角色选择」右上角的已选人数没认出来（相似度 {score:.2f}）")
        n = int(key[-1])
        if n >= 3:
            if r.tap(s, BOX["pick3.invite"], "去邀请") != "changed":
                self.seen_pick3 = True
                r.wait_leave(s.page)
            return
        by_name = self.pick != "auto" and any(isinstance(x, str) for x in self.pick)
        if self.pick == "auto" or by_name:
            if self.pick_auto is None:
                cards = CD.pick_cards(r.book, s.img)
                names = [self.chars.identify(c.fp, c.role, c.attr)[0] for c in cards]
                shown = lambda i: f"第 {cards[i].index + 1} 格 " + (f"{names[i]}[{cards[i].text}]" if names[i] else cards[i].text)      # noqa: E731
                if by_name:                          # 设置里写的是名字：在名单上找这几个人
                    idx = [names.index(x) for x in self.pick if x in names]
                    lost = [x for x in self.pick if x not in names]
                    if lost or len(idx) < 3:
                        r.log.shot(s.img, "pick3_name_not_found", png=True)
                        raise Halt(f"设置里写的开局人选在名单上没找到：{'、'.join(str(x) for x in lost) or '不够 3 个'}。"
                                   f"名单上认出来的是：{'、'.join(n for n in names if n) or '（一个都没认出来）'}。请改 config/settings.json 里 walk.pick")
                    r.log.say("      开局 3 人按设置里写的名字选：" + "、".join(shown(i) for i in idx))
                else:
                    idx = ST.choose_start([(c.role, c.attr) for c in cards], names=names, tags=[self.chars.tags(x) for x in names],
                                          atks=[self.chars.atk(x) for x in names], bases=[CH.base_of(x) if x else None for x in names],
                                          funcs=[self.chars.role_as(x) for x in names], aids=[self.chars.aid(x) for x in names],
                                          powers=[self.chars.power(x) for x in names], owned=[self.chars.owns(x) for x in names])
                    r.log.say("      开局 3 人按规则挑（当成一支 3 个人的快攻队：输出、破防、强化、增益优先，强的先拿，坦克和治疗排最后；"
                              "物理和魔法不混，同一个角色不重复拿）：" + "、".join(shown(i) for i in idx))
                    lent0 = [names[i] for i in range(len(names)) if self.chars.owns(names[i]) is False]
                    if lent0:
                        took = [names[i] for i in idx if self.chars.owns(names[i]) is False]
                        r.log.say(f"      （名单上有 {len(lent0)} 个不是你自己的角色，练度低，排在自己有的后面"
                                  + (f"；自己有的凑不齐，这次还是拿了 {'、'.join(took)}。）" if took else "，这次没拿。）"))
                self.pick_auto = [cards[i].index for i in idx]
                r.log.event("start_pick", cards=[[c.index, c.role, c.attr] for c in cards], names=names, pick=self.pick_auto, by="name" if by_name else "rule")
                for i in idx:
                    if cards[i].role:
                        self.roster[cards[i].role] = self.roster.get(cards[i].role, 0) + 1
            pick: tuple[int, ...] = tuple(self.pick_auto)
        else:
            pick = self.pick
        if n >= len(pick):
            raise Halt(f"设置里的开局人选只有 {len(pick)} 个，不够 3 个")
        cells = {c.index: c for c in TM.pick_cells(s.img)}
        want = pick[n]
        if want not in cells:
            raise Halt(f"开局人选里的第 {want + 1} 格在名单上是空的（这个公会的名单只有 {len(cells)} 人）。"
                       f"请改 config/settings.json 里 walk.pick")
        r.tap(s, cells[want].tap_box, f"开局第 {n + 1} 人：名单第 {want + 1} 格", think=True)
        r.pause(self.beat)

    def _take_over(self, s: Seen) -> None:
        """从地图接手进行中的一局（开始前勾了「接着打进行中的一局」才会来）。之后和工具自己开的局一样走：
        区域按地图上的数字、路线从现在站的地方往后排、名单进了队伍编组再认；凹度档位的规矩也照旧（该撤退重开时会撤退）。
        最终首领还是只有勾了「使用门票」才打。"""
        r = self.r
        how = "点了「出发」直接回到了一局的地图" if self.departed else "游戏已经停在一局的地图上"
        self.departed = self.seen_confirm = self.seen_pick3 = True
        self.took_over, self.pass_unsure, self.pass_block = True, True, None
        self.mid_area = True
        if self.passes is not None:                  # 迷宫首页上读到的是这一局扣过以后的数：按出发前的算（留几张门票的规矩才对得上）
            self.passes += 1
        self.fighting = self.arriving = False
        self.pending, self.tb = None, None
        self.map_idle = self.arrive_wait = 0
        r.log.shot(s.img, "takeover", png=True)
        r.log.say(f"      {how}：有一局正在进行中。这一次勾了「接着打进行中的一局」，从这里接手——")
        r.log.say("      · 后面和工具自己开的局一样走，凹度档位的规矩也一样：该撤退重开的时候会撤退，这一局就没了；")
        r.log.say("      · 前面走过的格子、打过的战斗我没看到：区域按地图上的数字来，名单进了队伍编组再认，估分只按地图上现在的数字算；")
        r.log.say("      · 最终首领还是只有勾了「使用门票」才打，没勾就停在它跟前。")
        r.log.event("takeover", how=how, passes=self.passes)

    def _on_map(self, s: Seen) -> None:
        r = self.r
        if not self.seen_confirm:
            if not self.resume:
                raise Halt("点了出发就直接到了地图，说明有一局正在进行中。这一次没有勾「接着打进行中的一局」，所以不动它，停下"
                           "（想让工具从这里接着打：开始前勾上那一项；命令行是加 --resume）")
            self._take_over(s)
            return                                   # 回主循环重新看一眼地图，照常往下走
        if self.ended:
            r.wait_leave(s.page, 20.0 * self.patience)
            return
        if not self.seen_pick3:
            r.wait_leave(s.page, 4.0 * self.patience)
            return
        if self.arriving:
            # 确认移动后，人物走过去的那一两秒里地图还露着，目的地那格也还亮着：这时候什么都不点，等这一格的内容弹出来
            self.arrive_wait += 1
            if self.arrive_wait <= 4:
                r.wait_leave(s.page, 3.0 * self.patience)
                return
            r.log.say("      走到格子上以后一直没弹出内容，按“这一格已经处理完”继续。")
            r.log.event("arrive_timeout", moves=len(self.moves))
            self.arriving = False
        tiles = TL.find_tiles(r.book, s.img)
        rc = TL.reachable(tiles)
        area = TL.area_number(r.book, s.img)
        r.log.event("tiles", area=area, reachable=[[t.x, t.ly, t.label, t.color] for t in rc], total=len(tiles))
        if area and area != self.area and rc:        # 进了新的区域：路线要重新排
            self.area, self.col, self.cur_ly, self.area_map, self.plan = area, 0, None, None, None
        if rc:                                       # 有发光的格子 = 这一格的内容处理完了，数字是稳定的
            self._read_hud(s.img)
            if self.ev_before is not None:
                self._after_event()
        if (self.scout and self.scout_step < 2 and rc and area == 1 and not self.moves and not self.want_retreat
                and self.team_mode == "role" and self._scout_bosses(s)):
            return
        if rc and any(t.label == "boss" for t in rc) and not self.want_retreat and not self._boss_ok():
            if self.area == 5 and self.final_stop:           # 最终首领跟前：没勾门票就停下；勾了看分数——够了打，不够撤退重打
                self.at_final = True
                r.log.shot(s.img, "before_final_boss", png=True)
                if self.final_score is None:
                    self._say_final_score()
                self._final_gate()
            if not self._boss_ok():
                self.want_retreat, self.why_retreat = True, self.why_retreat if self.settled == "redo" else self._boss_stop_reason()
                self.at_final = self.area == 5
                r.log.say(f"      {self.why_retreat}，到这里撤退。")
                if self.at_final and not self.settled:
                    r.log.shot(s.img, "before_final_boss", png=True)
                    self._say_final_score()
        if not self.want_retreat and self.steps > 0 and len(self.moves) >= self.steps:
            self.want_retreat, self.why_retreat = True, f"已经走满 {self.steps} 格"
        if self.survey and self.area_map is None and rc and area and not self.want_retreat:
            self._do_survey(s, rc)
            if self.steps == 0 and self.area_map is not None and not self.want_retreat:
                self.want_retreat, self.why_retreat = True, "只看全图，不走"
            return                                   # 地图拖回来了，回主循环重新看一眼再走
        if not self.want_retreat and self.steps == 0:
            self.want_retreat, self.why_retreat = True, "只看全图，不走"
        if self.want_retreat:
            if rc or self.map_idle >= 2:             # 有发光的格子 = 这一格的内容已经处理完了
                self._tap_wait(s, BOX["map.retreat"], f"撤退（无报酬）——{self.why_retreat}")
                self.map_idle = 0
            else:
                self.map_idle += 1
                r.wait_leave(s.page, 3.0 * self.patience)
            return
        if not rc:                                   # 格子内容还没弹出来 / 镜头还在动：等一等
            self.map_idle += 1
            if self.map_idle > 6:
                r.log.shot(s.img, "map_no_glow", png=True)
                raise Halt("地图上一直没看到发光（能走）的格子。如果地图被拖动过，请拖回人物所在的位置再试")
            r.wait_leave(s.page, 3.0 * self.patience)
            return
        self.map_idle = 0
        t = self._choose_tile(rc)
        if t is None:
            return
        names = "、".join(f"{x.row_name}:{LABEL_NAMES[x.label]}" for x in rc)
        r.log.say(f"      能走的格子有 {len(rc)} 个（{names}）"
                  + (f"；按路线走{t.row_name}边，后面是 {self._plan_text(self.plan)}" if self.plan and self.plan.path else ""))
        self.pending = t
        self._tap_wait(s, t.tap_box, f"第 {len(self.moves) + 1} 格：{t.row_name}边那格（{LABEL_NAMES[t.label]}）", think=True, timeout=6.0)

    def _scout_bosses(self, s: Seen) -> bool:
        """刚到区域 1 的地图：点进度条上的 BOSS 图标看这一局的首领。返回 True = 这一步点了图标（回主循环等「魔物详情」）。"""
        r = self.r
        key, box = f"map_boss{self.scout_step + 1}", BOX[f"map.boss{self.scout_step + 1}"]
        which = "区域 3 首领" if self.scout_step == 0 else "最终首领"
        if self.scout_wait:                          # 上一下点了图标，结果还在地图上：没点开
            self.scout_miss += 1
            self.scout_wait = False
        if key not in r.book.marks or not r.book.has_mark(s.img, key) or self.scout_miss >= 2:
            r.log.say(f"      进度条上没找到{which}的图标（或者点了两次都没打开）：这一局不看首领了，照常走。")
            r.log.event("scout_skip", step=self.scout_step, miss=self.scout_miss)
            self.scout_step = 2
            self._after_scout()
            return False
        self.scout_wait = True
        self._tap_wait(s, box, f"进度条上的 BOSS 图标（看这一局的{which}是谁）", timeout=4.0)
        return True

    def _on_monster(self, s: Seen) -> None:
        """「魔物详情」：开局看首领时读一下名字，然后关掉。"""
        r = self.r
        if self.scout_wait and self.scout_step < 2:
            got = EN.read_monster(r.book, s.img, self.counters)
            which = "区域 3 首领" if self.scout_step == 0 else "最终首领"
            self.bosses[self.scout_step] = got["name"]
            if got["name"]:
                r.log.say(f"      这一局的{which}：{got['name']}。攻略里的对策：{(self.counters.get(got['name']) or {}).get('guide', '')}")
            else:
                r.log.shot(s.img, "boss_unknown", png=True)
                r.log.say(f"      这一局的{which}没认出来（读到的字：{got['text'] or '没读出来'}），画面已存下来。")
            r.log.event("scout", which="mid" if self.scout_step == 0 else "final", name=got["name"], how=got["how"], text=got["text"])
            self.scout_wait, self.scout_miss = False, 0
            self.scout_step += 1
            if self.scout_step >= 2:
                self._after_scout()
        self._tap_wait(s, BOX["monster.close"], "关闭（魔物详情）")

    def _after_scout(self) -> None:
        """两个首领看完了：要重开的重开；不重开就记下它们要什么，招募时对应着拿。"""
        r = self.r
        why = TR.boss_verdict(self.bosses, self.reroll["boss_want"] if self.tier.reroll else [], self.boss_avoid)
        if why:
            self.want_retreat, self.restart = True, True
            self.why_retreat = why
            r.log.say(f"      {self.why_retreat}：撤退重开。")
            r.log.event("scout_restart", bosses=list(self.bosses))
            return
        roles: list[str] = []
        tags: list[str] = []
        for b in self.bosses:
            tw = self.counters.get(b or "") or {}
            for x in list(tw.get("always") or []) + list(tw.get("need") or []):
                if x in ST.GUARD and x not in roles:
                    roles.append(x)
            for x in tw.get("want") or []:
                if x not in tags:
                    tags.append(x)
        self.boss_wants = {"roles": roles, "tags": tags}
        if roles or tags:
            r.log.say("      为这两个首领，招募时名单里还没有的话优先拿："
                      + "、".join([("有奶的人（不一定是纯治疗）" if x == "heal" else ST.ROLE_CN_S.get(x, x)) for x in roles]
                                  + [ST.TAG_CN.get(x, x) for x in tags]) + "。")
        r.log.event("scout_done", bosses=list(self.bosses), wants=self.boss_wants)

    def _on_move(self, s: Seen) -> None:
        r = self.r
        key, score, sure = r.book.classify(s.img, MOVE_KEYS)
        if key is None or sure < 0.25:
            r.log.shot(s.img, "move_type_unreadable", png=True)
            raise Halt(f"「移动目标确认」里写的格子类型没认出来（相似度 {score:.2f}，把握 {sure:.2f}）")
        kind = key[5:]
        r.log.say(f"      这一格是：{MOVE_NAMES[kind]}")
        r.log.event("move_type", kind=kind, score=round(score, 3), sure=round(sure, 3))
        if kind == "boss" and not self._boss_ok() and self.area == 5 and self.final_stop and not self.settled:
            self.at_final = True                     # 地图上没认出下一格是首领、到了确认框才知道：在这里按分数定
            if self.final_score is None:
                self._say_final_score()
            self._final_gate()
        if kind == "boss" and not self._boss_ok():
            self.want_retreat, self.why_retreat = True, self.why_retreat if self.settled == "redo" else self._boss_stop_reason()
            self.at_final = self.area == 5
            if self.at_final and self.final_score is None:
                self._say_final_score()
            self._tap_wait(s, BOX["move.cancel"], "取消（这个首领不打）")
            return
        if r.tap(s, BOX["move.ok"], f"确认（移动到{MOVE_NAMES[kind]}）") != "changed":
            self.moves.append(kind)
            if kind == "event":                      # 事件完了以后回到地图，拿前后的数字算这个事件给了多少
                self.ev_before, self.ev_area = dict(self.hud), self.area
                self.slot_bets, self.bet_watch = 0, 0
            self.attempt, self.boss_extra = 0, 0
            self.enemy, self.tweak, self.enemy_done, self.enemy_tries = None, None, False, 0
            self.weak = None
            self.eff_tank = False
            self.lost_how = None
            self.tries, self.hp_log = [], []
            self.targets = None
            self.battle_kind = kind if kind in ("normal", "extreme", "boss") else "extreme"   # 事件里的战斗按极难对待
            self.arriving, self.arrive_wait = True, 0
            self.col += 1
            self.cur_ly = self.pending.ly if self.pending is not None else None
            if self.area_map is not None and self.cur_ly is not None and kind in ("normal", "extreme"):
                self.area_map.set_tile(self.col, self.cur_ly, kind, True)
            self.pending = None
            r.wait_leave(s.page)

    def _team_settling(self, tv: TM.TeamView) -> bool:
        """刚点了名单里的一格：成员栏要多一个人、那一格要盖上对勾，画面才算跟上。没跟上就再等等，免得把人点下场。

        只盯刚点的那一格，不要求整张名单的对勾数等于成员数——角色多了以后名单一屏放不下，上场的人不一定都看得见。
        """
        if self.team_expect is None:
            return False
        want, cx, cy = self.team_expect
        ok = tv.members >= want and any(c.selected and abs(c.cx - cx) <= 12 and abs(c.cy - cy) <= 12 for c in tv.cells)
        if not ok and self.team_retry < 6:
            self.team_retry += 1
            self.r.pause(0.4 * self.patience)
            return True
        self.team_expect, self.team_retry = None, 0
        return False

    def _on_boss_team(self, s: Seen, tv: TM.TeamView) -> None:
        """首领战的队伍编组：三个页签，右下角的按钮依次是「队伍2」「队伍3」「战斗开始」。要编几队由 _boss_teams 定，其余留空。"""
        r = self.r
        want = self._boss_teams()
        r.log.event("team_boss", tab=tv.tab, want=want, members=tv.members, empty=tv.empty_slots, listed=len(tv.cells),
                    free=[c.index for c in tv.free])
        fill = tv.tab <= want
        if fill:
            if self._team_settling(tv):
                return
            if tv.empty_slots > 0 and tv.free:
                c = tv.free[0]
                if r.tap(s, c.tap_box, f"队伍 {tv.tab} 上场：名单第 {c.index + 1} 格（成员栏还空 {tv.empty_slots} 个）") != "changed":
                    self.team_changed = True
                    self.team_expect = (tv.members + 1, c.cx, c.cy)
                r.pause(self.beat)
                return
            if tv.tab == 1 and tv.members == 0:
                raise Halt("首领战的队伍编组里一个能上场的角色都没有" + self._no_cards_why(s))
            if tv.members > 0 and self.team_changed and not self.equip_done and self.auto_equip:
                self._tap_wait(s, BOX["team.equip"], f"特别装备（队伍 {tv.tab} 换过人，自动装备一次）")
                return
        self.team_expect, self.team_retry = None, 0
        note = f"{tv.members} 人" if fill and tv.members else "留空"
        if tv.tab < 3:
            # 换页签以后还是「队伍编组」这个页面，所以点完不等“离开页面”，停一拍再看
            if r.tap(s, BOX["team.start"], f"队伍{tv.tab + 1}（队伍 {tv.tab}：{note}）") != "changed":
                self.team_changed = self.equip_done = self.auto_done = False      # 下一队重新算
            r.pause(self.beat + 0.3 * self.patience)
        elif self._faces(s) and r.tap(s, BOX["team.start"], f"战斗开始（首领战，队伍 3：{note}）") != "changed":
            self.fighting = True
            r.wait_leave(s.page)

    def _find_guild(self, s: Seen) -> NBox | None:
        """公会选择页上要选的那个公会的「选择」按钮在哪。先用名字的模板（只有慈乐之音有），没有模板或者没对上就让文字识别在那一排名字里找
        （名字在卡片下半截、按钮上面；王宫骑士团的名字是两行；按公会的关键字认，见 guilds.py）。按钮整个露在画面里才算找到。"""
        r = self.r
        if self.guild_mark and self.guild_mark in r.book.marks:
            score, mbox = r.book.find_mark(s.img, self.guild_mark)
            if score >= float(r.book.marks[self.guild_mark].get("thr", 0.8)):
                return guild_button(mbox)
        if ocr.available():
            for text, box, sc in ocr.read_items(to_norm(s.img)):
                cx, cy = box[0] + box[2] / 2.0, box[1] + box[3] / 2.0
                if sc >= 0.5 and 425 <= cy <= 520 and 110 <= cx <= 1170 and GD.matches(self.guild_name, text):
                    return (cx - 70.0, 550.0, 140.0, 42.0)      # 「选择」在名字正下方，高度是固定的（真机截图上按钮中心 y≈845 → 563）
        return None

    def _sync_hands(self) -> None:
        """你动过模拟器（我停手让过）以后：我记着的“这一页做到哪一步了”不一定还对得上画面——清掉，照现在的画面重新来。

        2026-11-25 有用户：切窗口时点到了模拟器，我让了 12 秒，接着还按原来排到一半的编队计划走，
        一看成员栏是空的，就报“队伍编组里一个能上场的角色都没有”停了。现在让过手以后编队从头来（重新看名单、重新排）。"""
        h = getattr(self.r, "hands", None)
        # 两种都算“画面被你动过”：你自己点了模拟器、我让过手；有个画面我认不出来、请你手动点过去的（runner.hand_asks）
        n = len(getattr(h, "waits", None) or ()) + len(getattr(self.r, "hand_asks", None) or ())
        if n == self.hands_seen:
            return
        self.hands_seen = n
        redo = []
        if self.tb is not None:
            self.tb = None
            redo.append("队伍从头排")
        self.team_expect, self.team_retry, self.team_empty = None, 0, 0
        if self.shop is not None:                            # 商店本来就是每一步都重新看货架；只把“拖到哪了”这些忘掉
            self.shop.update(bottom=False, drag_from=None, said=False, blur=0)
            redo.append("商店的货架重新看")
        self.guild_view = None
        self.r.log.say("      你动过画面，我记着的进度不一定还对得上——" + ("、".join(redo) if redo else "照现在的画面接着来") + "。")
        self.r.log.event("hands_resync", redo=redo)

    def _fix_sort(self, s: Seen) -> bool:
        """队伍编组右上角的排序不是「等级」：点开「分类」把它换回来。动了手返回 True（外面重新看画面）。

        工具找名单里的卡片，靠的是每张卡左上角的“等级”两个字。排序选了别的（战力、★数、攻击力……十几种），那里写的可能就不是这两个字了，
        一张卡都找不到（2026-11-26 玩家排查包：排序是「战力」，报“队伍编组里一个能上场的角色都没有”停了）。
        用户定的：不去认别的写法，**只要不是等级就一律换回「等级」**（21:30；有的排序——比如「编组顺序」——卡片上还是“等级”，也一样换，不分情况）。"""
        r = self.r
        state, box, lv = TM.sort_state(r.book, s.img)
        if state != "other" or box is None:
            return False
        if self.sort_tries >= 2:
            r.log.shot(s.img, "sort_stuck", png=True)
            raise Halt("队伍编组右上角的排序不是「等级」，我点开改了 2 次都没改过来——请手动把它改成「等级」再开始")
        self.sort_tries += 1
        r.log.shot(s.img, "sort_not_level", png=True)
        r.log.say("      队伍编组右上角的排序不是「等级」（我认卡片靠的是卡片左上角的“等级”两个字）：点开排序，改回「等级」。")
        r.log.event("sort_fix", what="open", n=self.sort_tries, lv=round(lv, 3))
        if r.tap(s, box, "排序（点开「分类」，把显示顺序改回「等级」）") != "changed":
            r.wait_leave(s.page, 4.0 * self.patience + 2.0)
        return True

    def _on_sort(self, s: Seen) -> None:
        """「分类」对话框（队伍编组右上角的排序按钮点开的）：选“显示顺序”里的「等级」，点「确认」。
        「等级」不在老地方（列表被拖过、版面变了）就不乱点：点「取消」，停下交给你。上面“排序方式”那两个选项不碰。"""
        r = self.r
        if not r.book.has_mark(s.img, "sort_opt_lv") or self.sort_taps >= 3:
            r.log.shot(s.img, "sort_unsure", png=True)
            why = "点了 3 次「等级」都没选上" if self.sort_taps >= 3 else "没在老地方看到“等级”这个选项"
            r.log.event("sort_fix", what="give_up", why=why)
            self._tap_wait(s, BOX["sort.cancel"], f"取消（「分类」里{why}，不乱点）")
            raise Halt(f"想把队伍编组的排序改回「等级」，可是「分类」里{why}——请手动把排序改成「等级」再开始")
        if not TM.sort_lv_selected(s.img):
            self.sort_taps += 1
            r.tap(s, BOX["sort.lv"], "等级（显示顺序）")
            r.pause(0.4 * self.patience + self.beat)
            return
        self.sort_taps = 0
        if self._tap_wait(s, BOX["sort.ok"], "确认（按等级排序）") != "changed":
            self.tb = None                           # 名单的顺序变了：编队从头看、从头排
            self.team_expect, self.team_retry, self.team_empty = None, 0, 0
            r.log.event("sort_fix", what="done")

    def _no_cards_why(self, s: Seen) -> str:
        """名单里一张卡都没认出来，可画面上明明有头像：多半是卡片左上角写的不是“等级”（右上角的排序选了别的）。停下时把这句带上。"""
        try:
            if TM.list_has_faces(s.img) and not TM.card_labels(self.r.book, s.img):
                return "（名单里有头像，可是卡片左上角写的不是“等级”——请把队伍编组右上角的排序改成「等级」再开始）"
        except Exception:  # noqa: BLE001 —— 说不出原因不影响停下
            pass
        return ""

    def _team_empty_again(self, s: Seen) -> bool:
        """队伍里一个人都没有、名单里也没挑出人来。可能只是这一眼没看清（名单还在动、刚有东西盖着）：先重新看两遍，一直这样才停。
        返回 True = 这一次先不停，重新看。"""
        self.team_empty += 1
        if self.team_empty > 2:
            self.r.log.shot(s.img, "team_empty", png=True)
            return False
        self.r.log.say(f"      队伍里还没有人，名单里也没挑出能上场的，等一下重新看名单（第 {self.team_empty} 次）。")
        self.tb = None
        self.team_expect, self.team_retry = None, 0
        self.r.pause(0.8 * self.patience + self.beat)
        return True

    def _on_relic_effect(self, s: Seen) -> None:
        """「迷宫遗物效果」：手里某件遗物生效、送了东西。只是告诉一声——记一笔，点「关闭」。

        2026-11-26 真机（用拉比林斯开局）：开局三人加入以后弹“凭借拉比林斯之主的效果，获得了以下道具。 噬魂手斧 × 1”。
        以前不认识这个对话框，等 20 秒就停，所以拉比林斯一直用不了。版面和「出发奖励」是同一个大对话框，「关闭」在同一个位置。
        送的遗物是哪个系列这里不读（和出发奖励里送的遗物一样，不算进自己记的系列等级）；别的遗物生效时弹的也是这个标题，一样处理。"""
        r = self.r
        if time.time() - self.effect_said > 8.0:             # 同一个对话框只记一次（点了没反应再来一遍时不重复记）
            self.effect_said = time.time()
            what = ""
            if ocr.available():
                rows = [(b[1], b[0], t) for t, b, sc in ocr.read_items(to_norm(s.img))
                        if sc >= 0.5 and 330 <= b[0] + b[2] / 2 <= 950 and 90 <= b[1] + b[3] / 2 <= 560]
                what = " ".join(t for _y, _x, t in sorted(rows))
            r.log.say("      迷宫遗物效果" + (f"：{what}" if what else "（有遗物生效，送了东西）"))
            r.log.event("relic_effect", text=what)
        self._tap_wait(s, BOX["depart_reward.close"], "关闭（迷宫遗物效果）")

    def _guild_names_seen(self, s: Seen) -> dict[str, float]:
        """公会选择页上这一屏读得到哪几个公会的名字、各在哪（名字中心的 x，1280 宽的坐标）。"""
        out: dict[str, float] = {}
        for text, box, sc in ocr.read_items(to_norm(s.img)):
            if sc < 0.5 or not 425 <= box[1] + box[3] / 2.0 <= 520:
                continue
            name = self.guild_name if GD.matches(self.guild_name, text) else next((n for n in GD.NAMES if GD.matches(n, text)), None)
            if name:
                out.setdefault(name, box[0] + box[2] / 2.0)
        return out

    @staticmethod
    def _same_guild_view(a: dict[str, float], b: dict[str, float]) -> bool:
        """两次读到的是不是同一屏：公会一样、位置也没挪（差 30 像素以内都算没挪——读字给的位置每次会差一两个像素）。"""
        return set(a) == set(b) and all(abs(a[k] - b[k]) <= 30.0 for k in a)

    def _on_guild_select(self, s: Seen) -> None:
        r = self.r
        btn = self._find_guild(s)
        if btn is not None:
            self.guild_swipes = self.guild_nudges = self.guild_turns = self.guild_blank = 0
            self.guild_dir, self.guild_view = -1, None
            self._tap_wait(s, btn, f"{self.guild_name} 的「选择」")
            return
        if not ocr.available():
            r.log.shot(s.img, "guild_not_found", png=True)
            raise Halt(f"公会选择页上这一屏没看到「{self.guild_name}」，这台机器又没有读字的组件，没法拖着找。请先把它滑到看得见的位置（慈乐之音以外的公会都要靠读字来认）")
        view = self._guild_names_seen(s)
        if not view:
            # 一个公会的名字都没读出来：可能是刚拖完画面还在动，多看两眼；一直读不出来就别瞎拖了，说清楚
            self.guild_blank += 1
            if self.guild_blank <= 3:
                r.pause(0.6 * self.patience + self.beat)
                return
            r.log.shot(s.img, "guild_not_found", png=True)
            why = ocr.items_problem()
            raise Halt(f"公会选择页上一个公会的名字都没读出来，没法找「{self.guild_name}」" + (f"（{why}）" if why else "")
                       + "。请把这次的记录发给我；也可以先自己把它滑到看得见的位置再开始")
        self.guild_blank = 0
        # 名字露出来了、但卡片只露出半张（在画面最左边或最右边）：朝那边拖一小段，把它拖进来
        edge = view.get(self.guild_name)
        if edge is not None and self.guild_nudges < 4:
            self.guild_nudges += 1
            self.guild_view = None
            a, b = ((440.0, 330.0), (760.0, 330.0)) if edge < 640 else ((840.0, 330.0), (520.0, 330.0))
            r.swipe(s, a, b, f"「{self.guild_name}」只露出半张，往{'右' if edge < 640 else '左'}拖一点把它拖进来", duration=0.4)
            r.pause(0.8 * self.patience + self.beat)
            return
        # 这一屏没有：公会是横着排的一长条（一屏三个）。先朝一边拖着找；拖完这一屏和拖之前一模一样 = 这边到头了，掉头朝另一边找；
        # 两头都到过还没有才算找不到。（2026-11-25 用户真机：要选的公会在左边，以前只会先朝右边找，而且在这个页面上动了 3 次就被当成“卡住”停下了）
        at_end = self.guild_view is not None and self._same_guild_view(view, self.guild_view)
        if at_end or self.guild_swipes >= GUILD_ONE_WAY:
            self.guild_turns += 1
            side = "右" if self.guild_dir < 0 else "左"
            if self.guild_turns >= 2:
                r.log.shot(s.img, "guild_not_found", png=True)
                raise Halt(f"公会选择页上左右两头都拖到了，没找到「{self.guild_name}」。请确认这个公会在国服已经开了、名字和游戏里写的一样")
            r.log.say(f"      {side}边{'到头了' if at_end else '拖了 ' + str(self.guild_swipes) + ' 次还没到头'}，没有「{self.guild_name}」，掉头去另一边找。")
            self.guild_dir, self.guild_swipes = -self.guild_dir, 0
        self.guild_swipes += 1
        self.guild_view = view
        left = self.guild_dir < 0
        a, b = ((1000.0, 330.0), (520.0, 330.0)) if left else ((440.0, 330.0), (920.0, 330.0))
        r.swipe(s, a, b, f"这一屏没有「{self.guild_name}」，往{'左' if left else '右'}拖，看{'右' if left else '左'}边的公会（第 {self.guild_swipes} 次）",
                duration=0.5, hold_end=0.25)
        r.pause(0.8 * self.patience + self.beat)

    def _read_loot(self, s: Seen) -> None:
        """打通结算后的「获得道具」：把清单从头读到尾（一屏三行半，往上拖着读），记进战利品账本。
        只在清单上拖，别的不点；读完交回主流程，照旧点对话框外面关掉。"""
        r = self.r
        self.loot_done = True
        shot = r.log.shot(s.img, "loot_list", png=True)
        found: dict[str, int] = {}
        how: dict[str, str] = {}                     # 每件饰品是怎么认出来的（名字 / 图标 / 两边都对上）

        def take(img: np.ndarray) -> list[str]:
            rows, texts = VL.read_rows(img, self.guild_name)
            VL.merge(found, rows)
            for row in rows:
                if row.acc is not None and ("都对上" in row.how or row.name not in how):
                    how[row.name] = row.how
            return texts

        texts = take(s.img)
        screens, still, cur = 1, 0, s
        if not VL.can_read():
            r.log.say("      （这台机器没有读字的组件，也没有饰品图标的模板，战利品清单读不了：只存了截图 loot_list，饰品数不会变。）")
        elif not ocr.available():
            r.log.say("      （这台机器没有读字的组件：清单上只认得出饰品的图标，别的东西和数量读不了，每件饰品按 1 件算。）")
        while VL.can_read() and screens <= VL.MAX_SCROLLS and still < 2:
            if r.swipe(cur, VL.SCROLL[0], VL.SCROLL[1], "把战利品清单往上拖一截（看下面还有什么）", duration=0.5) == "changed":
                break
            r.pause(0.6 * self.patience + self.beat)
            before, cur = cur, r.look()
            if cur.page != "dlg_items":
                break
            if not VL.moved(before.img, cur.img):    # 拖了没动：到底了。再拖一次确认（万一刚才那一下没拖上）
                still += 1
                continue
            still = 0
            r.log.shot(cur.img, "loot_list", png=True)
            texts += take(cur.img)
            screens += 1
        self.loot_items = found
        book = self.loot if self.loot is not None else LT.LootBook()
        # read = 整张清单读全了没有（没有读字的组件时只认得出饰品，别的东西没读到，不算读全）
        info = book.record(found, guild=self.guild_name, tier=self.tier.n, score=self.final_score, read=bool(found) and ocr.available(), shot=shot)
        book.save()
        self.loot_info = info
        r.log.event("loot", guild=self.guild_name, **VL.as_event(found, screens, texts), **info, how=how)
        if not found:
            if ocr.available():
                r.log.say("      战利品清单上一样东西都没读出来（截图存了 loot_list），这一局不计数。")
            elif VL.can_read():
                r.log.say("      战利品清单上没有认出饰品的图标（截图存了 loot_list）。")
            return
        r.log.say("      战利品：" + "、".join(f"{n} ×{c:,}" for n, c in found.items()) + "。")
        acc = info["accessories"]
        r.log.say("      其中饰品：" + ("、".join(f"{n} ×{c}" + (f"（{how[n]}）" if how.get(n) else "") for n, c in acc.items()) if acc else "这一局没有") + "。")
        odd = [n for n in acc if n in AC.BY_NAME and AC.BY_NAME[n].guild != self.guild_name and self.guild_name in [x.guild for x in AC.SERIES]]
        if odd:
            r.log.say(f"      ! {'、'.join(odd)} 按目录不是「{self.guild_name}」的宝箱出的。照认出来的记了，但请看一眼截图 loot_list：是认错了，还是目录要改。")
            r.log.event("loot_odd", guild=self.guild_name, names=odd)
        if info["unknown"]:
            r.log.say("      没见过的东西：" + "、".join(info["unknown"]) + "（要是其中有饰品，把名字告诉我，或者写进设置里的 farm.accessory_words）。")

    def _on_result(self, s: Seen) -> None:
        """最终首领打完后的 RESULT：先是「下一步」，分数数完以后是「关闭」。按钮没出来的时候不点。"""
        r = self.r
        self.cleared = True
        for key, name in (("result_next", "下一步"), ("result_close", "关闭")):
            if r.book.has_mark(s.img, key):
                if key == "result_close":
                    r.log.shot(s.img, "result_final", png=True)      # 最后的分数页留一张原图
                self._tap_wait(s, BOX["result.btn"], f"{name}（结算）")
                return
        r.wait_leave(s.page, 3.0 * self.patience)

    def _on_chest(self, s: Seen) -> None:
        """宝箱开封结果：宝箱一开始是盖着的，点一下翻开，翻开以后才有「确认」。"""
        r = self.r
        self.cleared = True
        if r.book.has_mark(s.img, "chest_ok"):
            r.log.shot(s.img, "chest_result", png=True)
            self._tap_wait(s, BOX["chest.ok"], "确认（宝箱开封结果）")
            return
        self.chest_taps += 1
        if self.chest_taps > 4:
            raise Halt("宝箱开封结果点了 4 次还没出现「确认」，停下")
        r.tap(s, BOX["chest.open"], "点一下翻开宝箱")
        r.pause(1.2 * self.patience + self.beat)

    # ---- 阶段 3：按职能和属性编队 ----
    def _new_tb(self, boss: int) -> dict[str, Any]:
        # pool 里每一项是（页签, 在这个页签里排第几张, 卡片）——名单是一行 8 张从上往下排的，往下翻着看时新看到的卡就是接着往后排的；
        # scroll = 这个页签已经往下翻了几次；seek = 为了找某张卡已经翻了几次
        return {"phase": "clear" if boss else "scan", "tabs": None, "ti": 0, "pool": [], "queue": [], "pending": None, "tries": 0,
                "boss_tab": boss, "plan": None, "tab_taps": 0, "clears": 0, "eff": None, "scroll": 0, "scrolls": 0, "seek": 0, "screens": 1}

    def _tap_tab(self, s: Seen, tb: dict[str, Any], name: str, boss: bool) -> None:
        tb["tab_taps"] += 1
        if tb["tab_taps"] > 30:
            self.r.log.shot(s.img, "team_tab_stuck", png=True)
            raise Halt("队伍编组上面的页签点了很多次都没切过去，停下")
        if self.r.tap(s, CD.tab_box(name, boss), f"名单页签「{TAB_CN[name]}」") != "changed":
            tb["scroll"], tb["seek"] = 0, 0          # 换了页签，名单回到最上面
        self._settle_list(name, boss)

    def _settle_list(self, name: str, boss: bool) -> None:
        """换了页签以后等名单换好。以前是死等 beat（0.7 秒，那是给“对勾盖上去”留的）；换页签用不了那么久——
        盯着看：这个页签亮起来了、名单连续两眼一样，就接着往下做。最多还是等 beat 那么久。"""
        r = self.r
        end = time.time() + self.beat
        prev = None
        r.pause(min(0.12, self.beat))
        while time.time() < end:
            s = r.look()
            if s.page != "dlg_team":                 # 弹出了别的东西：交回主流程照常看
                return
            thumb = cv2.resize(cv2.cvtColor(to_norm(s.img)[140:500, 40:1240], cv2.COLOR_BGR2GRAY), (96, 30), interpolation=cv2.INTER_AREA).astype(np.int16)
            if CD.active_tab(s.img, boss) == name and prev is not None and float(np.abs(thumb - prev).mean()) < 1.5:
                r.settled = "dlg_team"               # 已经等稳了：主循环下一眼不用再多看一次
                return
            prev = thumb
            r.pause(0.08)
        r.settled = "dlg_team"

    def _scroll_list(self, s: Seen, tb: dict[str, Any], down: bool, boss: bool, dist: float | None = None) -> None:
        """把名单往下翻（down=True）或者往上翻回去，dist = 翻多少（1280×720 的像素；不给就是看名单时的一步）。
        拖完按住一下再抬手，名单就不会被甩出去继续滑。起手、落手都不高过 y=232：再往上是「用角色名搜索」的输入框可能露出来的地方。"""
        tb["scrolls"] += 1
        if tb["scrolls"] > 80:
            self.r.log.shot(s.img, "team_scroll_stuck", png=True)
            raise Halt("队伍编组的名单翻了很多次还没弄完，停下")
        x, y = LIST_DRAG
        step = min(float(dist if dist is not None else LIST_STEP[bool(boss)]), y - 232.0)
        a, b = ((x, y), (x, y - step)) if down else ((x, y - step), (x, y))
        if self.r.swipe(s, a, b, f"名单往{'下' if down else '上'}翻{'一屏' if dist is None else f' {step / ROW_STEP[bool(boss)]:.0f} 行'}",
                        duration=0.55, hold_end=0.25) != "changed":
            tb["scroll"] += 1 if down else -1
        self.r.pause(self.beat + 0.3 * self.patience)

    def _find_card(self, s: Seen, tb: dict[str, Any], u: ST.Unit) -> Any:
        """名单上现在看得见的卡里，哪一张是 u（按头像认，翻过页、位置差几个像素都不怕）。看不见返回 None。"""
        fp = tb["pool"][u.key[4]][2].fp
        best, score = None, 0.0
        for c in CD.list_cards(self.r.book, s.img):
            v = CD.same_card(c.fp, fp)
            if v > score:
                best, score = c, v
        return best if score >= CD.FP_SAME else None

    def _visible_seqs(self, s: Seen, tb: dict[str, Any], tab: str) -> list[int]:
        """名单上现在看得见的卡，在这个页签里各排第几张（按头像对回看名单时记下的那些卡）。"""
        known = [(k, c.fp) for t, k, c in tb["pool"] if t == tab]
        out = []
        for c in CD.list_cards(self.r.book, s.img):
            best = max(known, key=lambda e: CD.same_card(c.fp, e[1]), default=None)
            if best is not None and CD.same_card(c.fp, best[1]) >= CD.FP_SAME:
                out.append(best[0])
        return out

    def _seek_card(self, s: Seen, tb: dict[str, Any], u: ST.Unit, boss: bool) -> bool:
        """u 那张卡现在看不见：看现在看得见的是第几行，往它那一行翻（差几行翻几行，不多拉）。
        返回 False = 翻了好多次还是找不到，放弃这张卡。"""
        tb["seek"] += 1
        if tb["seek"] > 14:
            return False
        tab, seq = u.key[0], u.key[1]
        vis = self._visible_seqs(s, tb, tab)
        if vis:
            lo, hi = min(vis) // CD.COLS, max(vis) // CD.COLS
            row = seq // CD.COLS
            down = row > hi
            rows = (row - hi) if down else max(1, lo - row)
            if not down and lo == 0:                 # 第一行已经看得见了还没找到：不再往上拉（会拉出搜索框），当成这张卡认不出来了
                return False
            self._scroll_list(s, tb, down, boss, dist=max(1, rows) * ROW_STEP[bool(boss)])
        else:                                        # 一张认识的卡都没看见（不该发生）：往下翻一行试试，再不行放弃
            if tb["seek"] > 3:
                return False
            self._scroll_list(s, tb, True, boss, dist=ROW_STEP[bool(boss)])
        return True

    def _ime_open(self, img: np.ndarray) -> bool:
        """是不是把游戏的输入法弹出来了（按到了名单顶上的「用角色名搜索」）：画面最下面一整条是白的。"""
        x, y, w, h = IME_ROI
        p = to_norm(img)[y:y + h, x:x + w]
        return float((p.min(axis=2) > 235).mean()) > 0.92

    def _on_team_role(self, s: Seen) -> None:
        """认名单里每张卡的职能和属性，按 strategy.choose_team 挑 5 个人，把队伍换成那 5 个，再自动装备、开打。

        名单一屏放得下（不到 16 张）就只看「全部」；放不下就把 火 / 水 / 风 / 光 / 暗 五个页签各看一遍。
        首领战先把成员栏清空再挑（已经上场的卡上盖着“队伍N”，职能图标被挡住，读不出来）。
        """
        r = self.r
        if self._ime_open(s.img):                    # 输入法被弹出来了：什么都没打，点「确定」收起来（搜索框是空的，名单不会变）
            self.ime_taps += 1
            r.log.shot(s.img, "team_ime_open", png=True)
            if self.ime_taps > 2:
                raise Halt("队伍编组里弹出了输入法，点「确定」也收不起来，停下")
            r.log.say("      注意：名单顶上的搜索框被按到了、弹出了输入法。什么都没输入，点「确定」把它收起来。")
            r.log.event("team_ime", n=self.ime_taps)
            r.tap(s, IME_OK, "确定（收起输入法，搜索框是空的）")
            r.pause(self.beat + 0.5 * self.patience)
            return
        boss = TM.boss_tab(s.img)
        is_boss = boss > 0
        tb = self.tb
        if tb is None or tb["boss_tab"] != boss:
            tb = self.tb = self._new_tb(boss)
            self.full_tabs = set()
            if is_boss and boss > 1:
                self.team_changed = self.equip_done = self.auto_done = False
            if is_boss and "eff_tank" in r.book.marks and r.book.has_mark(s.img, "eff_tank") and not self.eff_tank:
                self.eff_tank = True
                r.log.say("      游戏在「对首领的有效效果」里写着“坦克型”"
                          + ("：这个首领默认就带一个站最前面的坦克。" if "tank" in ((self.tweak or {}).get("always") or [])
                             else "：第一次照样全输出、不上坦克，打输了又看不出是怎么输的时候先加坦克。"))
                r.log.event("boss_effect", tank=True)
        members = CD.member_cards(r.book, s.img)
        n_mem = sum(1 for m in members if m is not None)
        fill = (not is_boss) or boss <= self._boss_teams()

        if tb["phase"] == "clear":                   # 首领战，或者这一队要留空：把成员栏里的人都点下去
            if n_mem > 0:
                tb["clears"] += 1
                if tb["clears"] > 8:
                    r.log.shot(s.img, "team_clear_stuck", png=True)
                    raise Halt("成员栏里的人点了好几次都没下去，停下")
                last = max(i for i, m in enumerate(members) if m is not None)
                r.tap(s, members[last].tap_box, f"成员栏第 {last + 1} 个先下场（{'这一队重新编' if fill else '这一队留空'}）")
                self.team_changed = True
                r.pause(self.beat)
                return
            tb["phase"] = "scan" if fill else "done"

        if tb["phase"] == "scan":
            cur = CD.active_tab(s.img, is_boss)
            cards = CD.list_cards(r.book, s.img)
            if tb["tabs"] is None:
                if cur is None:
                    self._tap_tab(s, tb, "all", is_boss)
                    return
                tb["tabs"] = ["all"] if (cur == "all" and len(cards) < CD.page_size(is_boss)) else ["fire", "water", "wind", "light", "dark"]
            want = tb["tabs"][min(tb["ti"], len(tb["tabs"]) - 1)]
            if tb["ti"] < len(tb["tabs"]) and cur != want:
                self._tap_tab(s, tb, want, is_boss)
                return
            if tb["ti"] < len(tb["tabs"]):
                known = [e[2] for e in tb["pool"] if e[0] == want]
                fresh = [c for c in cards if not any(CD.same_card(c.fp, k.fp) >= CD.FP_SAME for k in known)]
                tb["pool"] += [(want, len(known) + j, c) for j, c in enumerate(fresh)]
                tb["screens"] = max(tb["screens"], tb["scroll"] + 1)
                # 一个页签里的人要全部看到（2026-11-19 用户定的）：只要看得见的最下面一行是满的（8 张），后面就可能还有，往下翻了再看；
                # 翻了以后一张新面孔都没有，才算到底了。（以前按“这一屏满 16 张”算，名单被挤下来只露出一行时会漏）
                last_y = max((c.cy for c in cards), default=0)
                row_full = sum(1 for c in cards if abs(c.cy - last_y) <= 6) >= CD.COLS
                if row_full and (fresh or not known):
                    if tb["scroll"] < MAX_LIST_SCROLL:
                        self._scroll_list(s, tb, True, is_boss)
                        return
                    self.full_tabs.add(want)                               # 翻到上限了还是满的
                tb["ti"] += 1
                if tb["ti"] < len(tb["tabs"]):
                    self._tap_tab(s, tb, tb["tabs"][tb["ti"]], is_boss)
                    return
            # 攻略点名要某种特定效果（持续伤害、降魔攻、降物攻）的敌人：再看一眼「有效效果」页签，名单里对得上的人优先带
            eff_n = int((self.tweak or {}).get("effect", 0) or 0)
            want = frozenset((self.tweak or {}).get("want") or [])
            if eff_n > 0 and want and tb["eff"] is None:        # 认得出名字、角色表里写着有这种效果的人已经够数：不用再翻页签
                have = sum(1 for _t, _k, c in tb["pool"] if not c.busy and want & self.chars.tags(self.chars.identify(c.fp)[0]))
                if have >= eff_n:
                    tb["eff"] = []
            if eff_n > 0 and tb["eff"] is None:
                if cur != "effect":
                    self._tap_tab(s, tb, "effect", is_boss)
                    return
                tb["eff"] = [c.fp for c in cards if c.fp is not None]
            eff = tb["eff"] or []
            units = []
            for i, (tab, k, c) in enumerate(tb["pool"]):
                if c.busy:
                    continue
                name, sc = self.chars.identify(c.fp, c.role, c.attr)
                if name:
                    self.chars.refine(name, c.fp, sc)
                units.append(ST.Unit((tab, k, c.cx, c.cy, i), c.role, c.attr, c.selected, order=i, name=name,
                                     tags=self.chars.tags(name), atk=self.chars.atk(name), base=CH.base_of(name) if name else None,
                                     hit=self.chars.hit(name), pos=self.chars.pos(name),
                                     func=self.chars.role_as(name), aid=self.chars.aid(name), power=self.chars.power(name),
                                     heal=self.chars.heal(name), tough=self.chars.tough(name), pvp=self.chars.is_pvp(name),
                                     tough_p=self.chars.tough_vs(name, "phys"), tough_m=self.chars.tough_vs(name, "magic"),
                                     effective=any(CD.same_card(c.fp, e) >= CD.FP_SAME for e in eff), owned=self.chars.owns(name)))
                if name and not self.chars.knows(name):
                    self.no_info.add(name)
            if not is_boss:
                self.roster = ST.roster_counts(units)
                self.recruit_side = ST.roster_side(units)
            self.roster_tags = set().union(*[u.tags for u in units]) if units else set()
            self.unknown_joins = 0
            self.roster_scanned = True
            self.roster_heal = any(ST.can_heal(u) for u in units)
            if not is_boss or boss == 1:             # 这一局现在有哪些人（选印记属性时要用）
                self.run_units.update({u.name: (u.attr, u.kind) for u in units if u.name})
                self.run_unnamed = [(u.attr, u.kind) for u in units if not u.name]
            tweak = TR.with_guards(self.tier, self._team_tweak(), self.battle_kind)      # 第四档：极难 / 首领第一次就带坦克、治疗
            sides = (tweak or {}).get("sides") or []
            side = sides[boss - 1] if is_boss and 0 < boss <= len(sides) else None        # 对策表里写了这一队该是物理队还是法队
            # 这一次怎么打看前面是怎么输的：一个个倒 → 加坦克；一起崩 → 加治疗；时间到 → 保命的留着、输出换一批（加过的不再拿掉）
            profile, tweak2, avoid, why_retry = ST.plan_retry(self.battle_kind, self.tries, tweak)
            if self.run_wins:
                tweak2["proven"] = dict(self.run_wins)
            if self.battle_kind == "extreme" and self.tweak:      # 2026-11-27 用户定的：极难关按攻略来（和攻略点名的要求每差一个都重扣；名单里做不到的不算）
                tweak2["strict"] = True
            plan, swapped = ST.choose_new_team(units, self.battle_kind, self.weak, self.attempt, lost=[t.get("team") or [] for t in self.tries],
                                               tweak=tweak2, side=side, targets=self.targets, profile=profile, avoid=avoid)
            if swapped:
                why_retry = (why_retry + "；" if why_retry else "") + "排出来的队和输过的那一队一模一样，换了人再排"
            remembered = self._remembered(units)     # 真机上打赢过的队，凑得齐就直接上：比规则和估算都可靠
            if remembered is not None:
                plan = ST.plan_of(units, remembered["units"], plan.profile, self.weak, tweak2, self.targets)
                why_retry = (why_retry + "；" if why_retry else "") + "上以前打赢过这个敌人的那一队"
            est = self._estimate(units, plan, tweak2, side, avoid) if remembered is None and not (is_boss and self._boss_teams() > 1) else None
            self.last_est = None
            if est is not None:
                rule_names = [u.name for u in plan.team]
                lacks = TR.missing_guards(self.tier, [(u.kind, ST.can_heal(u)) for u in est["pick"]]) if est["pick"] is not None else []
                if lacks:                            # 保通关档：估算挑的队没带齐保命的人，不换，上规则排的那队（规则那边已经按这一档带上了）
                    est["lines"].append(f"        不过{self.tier.name}要求第一次就带{'、'.join('坦克' if g == 'tank' else '治疗' for g in lacks)}，"
                                        f"估算挑的这队没带，所以不换，上规则排的那一队。")
                    est["event"]["kept_rule"] = lacks
                elif est["pick"] is not None:
                    plan = ST.plan_of(units, est["pick"], plan.profile, self.weak, tweak2, self.targets)
                    why_retry = (why_retry + "；" if why_retry else "") + "按战斗估算换了队"
                self.last_est = est["event"]
                for line in est["lines"]:
                    r.log.say(line)
                r.log.event("estimate", battle=self.battle_kind, enemy=self.enemy, attempt=self.attempt, rule=rule_names, **est["event"])
            tb["plan"] = plan
            tabs_order = {t: i for i, t in enumerate(tb["tabs"])}
            by_tab = lambda u: (tabs_order.get(u.key[0], 0), u.key[1])           # noqa: E731  同一个页签、同一屏里的放一起点，少翻
            tb["queue"] = [("drop", u) for u in sorted(plan.drop, key=by_tab)] + [("add", u) for u in sorted(plan.add, key=by_tab)]
            def show(u: ST.Unit) -> str:
                base = f"{CD.ROLE_CN[u.role]}/{CD.ATTR_CN[u.attr]}"
                mark = "、".join(([f"强度 {u.power:g}"] if u.power >= 3 else []) + [ST.TAG_CN.get(t, t) for t in sorted(u.tags)]
                                + ([HIT_CN[u.hit]] if u.hit in HIT_CN and u.kind in ST.DAMAGE else [])
                                + (["有奶"] if u.heal >= 1 and u.kind != "heal" else [])
                                + ([f"按{ROLE_NAMES[u.func]}用"] if u.func and u.func != u.role else [])
                                + (["不是你自己的角色"] if u.owned is False else []))
                mark = mark or ("有效效果" if u.effective else "")
                return (f"{u.name}[{base}]" if u.name else base) + (f"（{mark}）" if mark else "")

            who = "、".join(show(u) for u in plan.team)
            self.last_team = [u.name or f"{CD.ROLE_CN[u.role]}/{CD.ATTR_CN[u.attr]}" for u in plan.team]
            self.last_roles = {u.name: u.kind for u in plan.team if u.name}
            sub0 = ST.stand_in_tank(plan.team) if "tank" in ((tweak2 or {}).get("need") or []) and not any(u.role == "tank" for u in units) else None
            self.last_front = (sub0.name, sub0.tough) if sub0 is not None else None        # 这一场是谁在顶坦克的位置（没有坦克、拿肉的前排顶时才有）
            # 这一队带着哪种保命的人（打输了要用：已经带了还那样倒，下一次就不能只是“带一个”）
            self.last_had = (["tank"] if ST.tank_in_front(plan.team) or sub0 is not None else []) + (["heal"] if any(ST.can_heal(u) for u in plan.team) else [])
            named = sum(1 for u in units if u.name)
            vs = f"打{self.enemy}，" if self.enemy else ""
            side_cn = (f"，{ST.SIDE_CN[plan.side]}" if plan.side else "") + (f"；{ST.TARGETS_CN[self.targets]}" if self.targets in ST.TARGETS_CN else "")
            mech = (tweak2 or {}).get("mech")
            route = (f"；队伍路线：{plan.concept}" if plan.concept else "") + ("（这一关机制强，攻略点名的效果先带齐）" if mech else "") \
                + (f"（攻略说这个敌人吃{ST.SIDE_CN[tweak2['side']]}）" if (tweak2 or {}).get("side") in ST.SIDE_CN else "")
            r.log.say(f"      名单 {len(units)} 人。这一场（{KIND_CN.get(self.battle_kind, self.battle_kind)}，{vs}第 {self.attempt + 1} 次打，"
                      f"{PROFILE_CN[plan.profile]}{side_cn}{route}）带：{who}；要换下 {len(plan.drop)} 个、换上 {len(plan.add)} 个。"
                      + (f"名单里认得出名字的有 {named} 个。" if named else ""))
            lent_all = [u for u in units if u.owned is False]
            if lent_all:                             # 2026-11-27 用户定的：最优先上玩家自己有的角色（没有的在黎明界也能用，但练度低）
                lent_in = [u.name for u in plan.team if u.owned is False]
                r.log.say(f"      名单里有 {len(lent_all)} 个不是你自己的角色（借来的，练度低），最优先上你自己有的："
                          + ("这一队里一个借来的都没有。" if not lent_in else f"自己有的凑不齐这一队，还是上了 {'、'.join(lent_in)}。"))
            elif not self.own_said and not self.chars.owned():
                self.own_said = True
                r.log.say("      （还没扫描过角色——或者上一次没读完——分不出哪些是你自己的角色、哪些是黎明界借的。"
                          "在界面「其他」里点「扫描角色」读完一遍以后，编队会最优先上你自己的角色。）")
            if "heal" in (tweak2.get("need") or []):
                hs = [u for u in plan.team if ST.can_heal(u)]
                r.log.say("      这一场要带奶：" + ("、".join(f"{u.name or CD.ROLE_CN[u.role]}（{'职能是治疗' if u.kind == 'heal' else f'有 {u.heal:g} 个能给全队回血的技能'}）" for u in hs)
                                              if hs else "名单里没有会给全队回血的人，带不了") + "。")
            if why_retry:
                r.log.say(f"      {why_retry}。")
            if any(u.role == "tank" for u in plan.team) and "tank" in (tweak2.get("need") or []):
                front = ST.tank_in_front(plan.team)
                tk = min((u for u in plan.team if u.role == "tank" and u.pos is not None), key=lambda u: u.pos, default=None)
                if front and tk is not None:
                    r.log.say(f"      坦克 {tk.name} 站最前面（站位 {tk.pos}，队里其他人最靠前的是 "
                              f"{min((u.pos for u in plan.team if u.role != 'tank' and u.pos is not None), default='?')}）。")
                elif front is False:
                    r.log.say("      注意：名单里的坦克都站不到最前面（有输出比坦克站得还靠前），这一场的坦克挡不了刀。")
            elif "tank" in (tweak2.get("need") or []):                       # 这一场要坦克，可队里没有坦克
                has_tank = any(u.role == "tank" for u in units)
                sub = ST.stand_in_tank(plan.team) if not has_tank else None
                if sub is not None:
                    behind = min((u.pos for u in plan.team if u is not sub and u.pos is not None), default="?")
                    r.log.say(f"      名单里没有坦克：让够肉的 {sub.name} 站最前面顶着（站位 {sub.pos}，队里其他人最靠前的是 {behind}；"
                              f"耐打程度 {sub.tough:g}，一般坦克是 1，一般的输出只有 0.1 左右）。")
                elif not has_tank:
                    r.log.say("      注意：名单里没有坦克，也没有够肉、能站到最前面的人可以顶（耐打程度到 "
                              f"{ST.TOUGH_MIN:g} 才算），这一场前面没人挡。")
                else:
                    r.log.say("      注意：名单里有坦克，但这一场排出来的队没带上。")
            known_pos = [u for u in plan.team if u.pos is not None]
            if (tweak2 or {}).get("pack") and len(known_pos) == len(plan.team) and plan.team:
                ps = sorted(u.pos for u in plan.team)
                r.log.say(f"      这一关要站位集中（攻略：伤害看最前面的人和其他人离得多远）：这一队站位 {ps[0]}～{ps[-1]}，"
                          f"最前面的人和第二个人差 {ps[1] - ps[0] if len(ps) > 1 else 0}。")
            gap2 = float((tweak2 or {}).get("spread") or 0.0)
            near2 = ST.crowd(plan.team, gap2) if gap2 > 0 else None
            if gap2 > 0 and len(known_pos) == len(plan.team) and plan.team:
                ps = sorted(plan.team, key=lambda u: u.pos)
                r.log.say(f"      这一关要把站位拉开（攻略：一个人站最前面，其余的都放后排；它的大招打最前面的人和她周围）：最前面是 {ps[0].name}（站位 {ps[0].pos}），"
                          f"其余的人站位 {'、'.join(str(u.pos) for u in ps[1:])}"
                          + ("，都离她 %g 以上。" % gap2 if not near2 else f"；名单里凑不出四个离得够远的人，还有 {near2} 个人站在离她 {gap2:g} 以内。"))
            if plan.profile != "fast" and len(known_pos) == len(plan.team) and plan.team:
                fr = min(plan.team, key=lambda u: u.pos)
                if "selfharm" in fr.tags:
                    r.log.say(f"      注意：站最前面的 {fr.name} 是自损的角色（技能会扣自己的血 / 降自己的防），名单里排不出别人站她前面。")
            hits2 = (tweak2 or {}).get("hits") or {}
            if hits2.get("n") and plan.profile != "fast" and len(known_pos) == len(plan.team) and plan.team:
                hk = hits2.get("type") if hits2.get("type") in ST.SIDES else None
                zone = sorted(plan.team, key=lambda u: u.pos)[:int(hits2["n"])]
                r.log.say(f"      敌人的技能（按游戏里的敌人说明）打我方最前面 {int(hits2['n'])} 个位置"
                          f"{'，是' + {'phys': '物理', 'magic': '魔法'}[hk] + '伤害' if hk else ''}：这几个位置上是 "
                          + "、".join(f"{u.name or '？'}（耐打 {ST.tough_vs(u, hk):g}）" for u in zone) + "。")
            kept = [u.name for u in plan.team if u.name and self.run_wins.get(u.name)]
            if kept and plan.profile != "fast":
                r.log.say(f"      这一队里这一局赢过的人：{'、'.join(f'{n}（{self.run_wins[n]} 场）' for n in kept)}。")
            if any(u.pvp for u in plan.team):
                r.log.say(f"      注意：{'、'.join(u.name for u in plan.team if u.pvp)} 是纯竞技场用的角色，名单里没有别人可上才带的。")
            if self.full_tabs:
                r.log.say(f"      注意：「{'、'.join(TAB_CN[t] for t in sorted(self.full_tabs))}」页签往下翻了 {MAX_LIST_SCROLL} 屏还没到底，"
                          f"后面可能还有没看到的角色，这一场只从看到的人里挑。")
            if eff_n > 0:
                tagged = sum(1 for u in units if want & u.tags)
                r.log.say(f"      攻略点名要的效果：按名字认出 {tagged} 个有这种效果的角色；"
                          + (f"「有效效果」页签里看到 {len(eff)} 张卡，名单里对上 {sum(u.effective for u in units)} 个。" if eff else "没有去翻「有效效果」页签。"))
            must = self._must_tags()
            if must and not any(must & u.tags for u in units) and not any(u.effective for u in units):
                self.no_mech = True
                what = "、".join(ST.TAG_CN.get(t, t) for t in sorted(must))
                r.log.say(f"      注意：这个敌人非要{what}不可，名单里按名字一个都没对上，「有效效果」页签里也没有——多半打不动。"
                          "名单里有我认不出的人，所以还是打这一次试试；输了就不重打了，直接撤退重开。")
                r.log.event("no_mech", enemy=self.enemy, must=sorted(must), sure=False, roster=len(units))
            r.log.event("team_plan", battle=self.battle_kind, attempt=self.attempt, profile=plan.profile, weak=self.weak,
                        enemy=self.enemy, listed=len(units), tabs=tb["tabs"], screens=tb["screens"], team=[[u.role, u.attr] for u in plan.team],
                        names=[u.name for u in plan.team], named=named, side=plan.side, atks=[u.atk for u in plan.team],
                        targets=self.targets, hits=[u.hit for u in plan.team], pos=[u.pos for u in plan.team],
                        concept=plan.concept, heals=[u.heal for u in plan.team], mech=bool((tweak2 or {}).get("mech")),
                        stand_in=self.last_front[0] if self.last_front else None, front_lost=(tweak2 or {}).get("front_lost"),
                        had=list(self.last_had), swapped=swapped, pack=bool((tweak2 or {}).get("pack")), pvp=[u.name for u in plan.team if u.pvp],
                        spread=gap2 or None, crowd=near2, need_hit=(tweak2 or {}).get("need_hit"),
                        lent=[u.name for u in plan.team if u.owned is False], lent_all=len(lent_all),
                        proven=[self.run_wins.get(u.name or "", 0) for u in plan.team], selfharm=[u.name for u in plan.team if "selfharm" in u.tags],
                        tough=[u.tough for u in plan.team], hit_zone=dict(hits2) if hits2 else None,
                        tough_vs=[ST.tough_vs(u, hits2.get("type")) for u in plan.team] if hits2 else None,
                        tank_front=ST.tank_in_front(plan.team), lost_how=self.lost_how, tries=[t.get("how") for t in self.tries],
                        power=[u.power for u in plan.team], avoid=sorted(avoid),
                        need=list(tweak2.get("need") or []), full_tabs=sorted(self.full_tabs),
                        add=len(plan.add), drop=len(plan.drop), roster=dict(self.roster), score=round(plan.score, 1),
                        effective=[sum(u.effective for u in units), sum(u.effective for u in plan.team)] if eff_n > 0 else None)
            tb["phase"] = "apply"

        if tb["phase"] == "apply":
            cur = CD.active_tab(s.img, is_boss)
            pend = tb["pending"]
            if pend is not None:
                act, u = pend
                tab = u.key[0]
                if cur != tab:
                    self._tap_tab(s, tb, tab, is_boss)
                    return
                card = self._find_card(s, tb, u)
                ok = card is not None and card.selected == (act == "add")
                if not ok:
                    tb["tries"] += 1
                    if tb["tries"] <= 3:             # 对勾要半秒左右才变：再等等
                        r.pause(0.4 * self.patience)
                        return
                    if tb["tries"] == 4 and card is not None:
                        r.tap(s, card.tap_box, f"再点一次（刚才那一下{'没上场' if act == 'add' else '没下场'}）")
                        r.pause(self.beat)
                        return
                    r.log.shot(s.img, "team_tap_no_effect", png=True)
                    raise Halt("点了名单里的角色，对勾一直没有变化，停下")
                tb["pending"], tb["tries"] = None, 0
                self.team_changed = True
            if tb["queue"]:
                act, u = tb["queue"][0]
                tab = u.key[0]
                if act == "add" and n_mem >= CD.SLOTS:           # 队伍是满的：有名单上没看到的人占着位置，先请下去
                    slot = self._extra_member(members, tb["plan"])
                    if slot is None:
                        raise Halt("队伍已经满了，但是分不出该请谁下场，停下")
                    tb["clears"] += 1
                    if tb["clears"] > 8:
                        raise Halt("成员栏里的人点了好几次都没下去，停下")
                    r.tap(s, members[slot].tap_box, f"成员栏第 {slot + 1} 个下场（{members[slot].text}，不在这一场的名单里）")
                    self.team_changed = True
                    r.pause(self.beat)
                    return
                if cur != tab:
                    self._tap_tab(s, tb, tab, is_boss)
                    return
                what = f"{CD.ROLE_CN[u.role]}/{CD.ATTR_CN[u.attr]}"
                card = self._find_card(s, tb, u)
                if card is None:                                 # 这张卡不在现在这一屏：翻到它那一屏去
                    if not self._seek_card(s, tb, u, is_boss):
                        r.log.shot(s.img, "team_card_lost", png=True)
                        r.log.say(f"      名单里找不到刚才看到的那张卡了（{u.name or what}），这一个不{'上' if act == 'add' else '下'}了，接着弄别的。")
                        r.log.event("team_card_lost", role=u.role, attr=u.attr, name=u.name, act=act)
                        tb["queue"].pop(0)
                        tb["seek"] = 0
                    return
                tb["seek"] = 0
                box = (card.cx - 36.0, card.cy - 30.0, 72.0, 60.0)
                # 上场要“想一想”的只有这一队的第一个人（挑谁是一次想好的，后面几个是接着点）；想的时间从看到名单那一刻算起，
                # 排队伍、推演花掉的已经算在里面（Runner._react）
                first = act == "add" and not tb.get("added")
                if r.tap(s, box, f"{'上场' if act == 'add' else '下场'}：{what}", think=first) != "changed":
                    tb["queue"].pop(0)
                    tb["pending"], tb["tries"] = (act, u), 0
                    if act == "add":
                        tb["added"] = int(tb.get("added", 0)) + 1
                r.pause(self.beat)
                r.settled = "dlg_team"               # 对勾盖上去的时间已经等过了：主循环下一眼不用再多看一次
                return
            tb["phase"] = "done"

        # ---- 队伍定了：自动装备，然后开打（首领战是翻到下一队） ----
        if fill and n_mem == 0:
            if self._team_empty_again(s):
                return
            raise Halt("队伍编组里一个能上场的角色都没有" + self._no_cards_why(s))
        self.team_empty = 0
        if fill and self.team_changed and not self.equip_done and self.auto_equip:
            self._tap_wait(s, BOX["team.equip"], "特别装备（队伍换过人，重新自动装备一次）")
            return
        if is_boss and boss < 3:
            note = f"{n_mem} 人" if fill else "留空"
            if boss == 1:
                self._faces(s, boss_tab=1)
            if r.tap(s, BOX["team.start"], f"队伍{boss + 1}（队伍 {boss}：{note}）") != "changed":
                self.team_changed = self.equip_done = self.auto_done = False
            r.pause(self.beat + 0.3 * self.patience)
            return
        label = f"战斗开始（首领战，队伍 3：{n_mem} 人）" if is_boss else f"战斗开始（{n_mem} 人）"
        self._faces(s, boss_tab=3 if is_boss else 0)
        if r.tap(s, BOX["team.start"], label) != "changed":
            self.fighting = True
            r.wait_leave(s.page)

    @staticmethod
    def _extra_member(members: list, plan: ST.TeamPlan | None) -> int | None:
        """成员栏里哪一个不在打算带的 5 个人里（按 职能 + 属性 对）。都对得上就返回最左边那个。"""
        left: dict[tuple, int] = {}
        for u in (plan.team if plan else []):
            if u.selected:
                left[(u.role, u.attr)] = left.get((u.role, u.attr), 0) + 1
        for i, m in enumerate(members):
            if m is None:
                continue
            sig = (m.role, m.attr)
            if left.get(sig, 0) > 0:
                left[sig] -= 1
            else:
                return i
        return next((i for i, m in enumerate(members) if m is not None), None)

    def _learn_join(self, s: Seen) -> bool:
        """「角色加入」：把每一行的名字读下来，和小头像一起记进头像库。返回 False = 名字还没读全，等一下再读。"""
        r = self.r
        if self.join_seen is not None or not ocr.available():
            return True
        rows = CD.join_rows(s.img)
        reads = [self.chars.read_name(s.img, row["name_box"], ink="dark") for row in rows]      # 对话框里是白底深色字
        raw = [g["raw"] for g in reads]
        got = [(row, g["name"]) for row, g in zip(rows, reads)]                                 # 只认正式名单里有的名字
        if (not rows or any(not n for _row, n in got)) and self.join_tries < 2:      # 对话框还在弹出来，字没显示全
            self.join_tries += 1
            r.pause(0.4 * self.patience)
            return False
        out = []
        for row, name in got:
            how = self.chars.learn(name, row["fp"]) if name else "skip"
            out.append([name, how])
            if name and name not in self.run_units:  # 这一局多了谁（属性按资料站的；职能等下一次编队看名单时补上）
                self.run_units[name] = (self.chars.attrs.get(name), self.chars.role_as(name))
                self.roster_heal = self.roster_heal or self.chars.heal(name) >= 1
        self.join_seen = out
        self.chars.resolve_sightings()               # 「读角色」里还分不出版本的头像，这下可能对上了
        self.chars.save()
        ok = [n for n, _h in out if n]
        if ok:
            new = [n for n, h in out if h == "new"]
            r.log.say(f"      加入的角色：{'、'.join(ok)}" + (f"（头像库新认识 {len(new)} 个，现在一共 {len(self.chars.names())} 个）" if new else ""))
        if len(ok) < len(rows):
            self.unknown_joins += len(rows) - len(ok)
            guess = [g["guess"] for g in reads if not g["name"] and g["guess"]]
            r.log.shot(s.img, "join_name_unread", png=True)
            r.log.say(f"      「角色加入」里有 {len(rows) - len(ok)} 行名字没认出来"
                      + (f"（读到的是 {'、'.join(guess)}，正式名单里没有：是新角色的话先点一次菜单 17「更新角色」）" if guess else "") + "，画面已存下来。")
        r.log.event("joined", names=out, rows=len(rows), raw=raw)
        return True

    def _recruit_names(self, s: Seen, cards: list) -> list:
        """招募三选一：读三张卡下面的名字（读不出来的是 None），顺手记进头像库。"""
        if not ocr.available():
            return [None] * len(cards)
        names = []
        for i, c in enumerate(cards):
            g = self.chars.read_name(s.img, CD.recruit_name_box(i), ink="dark", lines=2)      # 卡片下面两行：名字 /（版本）
            name = g["name"] or None
            if name and c.fp is not None:
                self.chars.learn(name, c.fp, c.role, c.attr)
            else:
                name = name or self.chars.identify(c.fp)[0]          # 字没读出来：头像库里认识也行
            names.append(name)
        return names

    def _retries(self) -> int:
        """这一场打输以后最多再打几次：对策表里给这个敌人单独写了次数就用它（比如美空：攻略说打一两次不过就撤）。"""
        if self.no_mech:                             # 没有对应机制的角色：换谁上都一样，输了不重打
            return 0
        n = (self.tweak or {}).get("retries")
        return self.defeat_retries if n is None else max(0, min(int(n), self.defeat_retries))

    def _read_enemy(self, s: Seen) -> bool:
        """「战斗准备」：认一下是哪个敌人，查对策表。返回 False = 名字还没显示出来，等一下再来。"""
        r = self.r
        if not self.enemy_done and self.team_mode == "role":
            # 页面中间有一条血条 = 一个大敌人；没有 = 一排敌人站开（普通战的小怪、带小怪的首领、装置那几组）
            self.targets = "single" if EN.has_name_bar(s.img) else "multi"
        if self.enemy_done or self.team_mode != "role" or self.battle_kind not in ("extreme", "boss"):
            return True
        got = EN.read_enemy(r.book, s.img, self.counters)
        while got["bar"] and not got["name"] and self.enemy_tries < 2:   # 血条有了、名字没认出来：可能画面还在淡入，等一下再看
            self.enemy_tries += 1
            r.pause(0.4 * self.patience)
            again = r.observe()
            if again.page != s.page:
                return False
            s = again
            got = EN.read_enemy(r.book, s.img, self.counters)
        self.enemy_done = True
        self.enemy = got["name"]
        if not self.enemy and self.battle_kind == "boss":        # 首领战的页面上没认出来：开局点进度条看过这一局的首领是谁，用那个
            known = self.bosses[0 if self.area <= 3 else 1] if self.area else None
            if known and known in self.counters:
                self.enemy, got = known, {**got, "name": known, "how": "scout"}
                r.log.say(f"      首领战的页面上认不出是谁，开局看过这一局的{'区域 3 首领' if self.area <= 3 else '最终首领'}是 {known}，按它来。")
                if not got["bar"]:
                    r.log.shot(s.img, "enemy_lineup")            # 画面留一张，之后补上按画面认
        self.tweak = self.counters.get(self.enemy) if self.enemy else None
        self.targets = (self.tweak or {}).get("targets") or ("single" if got["bar"] else "multi")      # 对策表里写了的（多部位、带小怪）以表为准
        self.weak = CD.weak_attr(r.book, s.img) if got["bar"] else None           # 名字那一栏“弱点”后面有属性图标就是它怕的属性（一条横线 = 没有）
        if self.weak:
            r.log.say(f"      这个敌人的弱点是{CD.ATTR_CN[self.weak]}属性：这个属性的角色优先。")
        kind = KIND_CN.get(self.battle_kind, self.battle_kind)
        if self.tweak:
            r.log.say(f"      敌人：{self.enemy}（{kind}）。攻略里的对策：{self.tweak.get('guide', '')}")
        elif got["bar"]:
            r.log.shot(s.img, "enemy_unknown", png=True)
            seen = f"读到的字是“{got['text']}”" if got["text"] else "名字没读出来"
            r.log.say(f"      这个敌人（{kind}）不在对策表里（{seen}），按默认的全输出打法编队（输了再换稳妥的）。画面已存下来，之后补进对策表。")
        elif self.battle_kind == "extreme" and self.unseen_group:
            # 极难格子里的一排敌人 = 六组“装置 + 几个角色”里的一组，或者带一个装置的蜂后 / 美空。2026-11-27 傍晚起这些都有模板；
            # 还是认不出时按“要范围输出”排，不用什么都不管的默认打法（2026-11-27：玩家在区域 5 遇到带回复的那一组，上了一队打单体的，打到时间到）
            self.tweak = dict(self.unseen_group)
            self.targets = self.tweak.get("targets") or self.targets
            r.log.shot(s.img, "enemy_lineup")
            r.log.say(f"      这一场（{kind}）是一组敌人，页面上没有名字，画面也对不上认得的那几组（六组装置、蜂后、美空）。"
                      "按“要范围输出”编队（会打一群的输出至少带 3 个，名单里没那么多就有几个带几个）。画面已存下来。")
        else:
            r.log.shot(s.img, "enemy_lineup")
            r.log.say(f"      这一场（{kind}）是一组敌人，页面上没有名字，认不出是哪一组，按默认的全输出打法编队（输了再换稳妥的）。")
        r.log.event("enemy", battle=self.battle_kind, name=self.enemy, how=got["how"], text=got["text"], bar=got["bar"])
        return True

    def _defeat_box(self, s: Seen, which: str) -> NBox:
        """失败页面上「重新挑战」（which="retry"）/「结束」（"end"）按钮的位置。首领战的失败页面按钮比普通战低一截，所以现找。"""
        sc, (x, y, _w, _h) = self.r.book.find_mark(s.img, f"btn_defeat_{which}") if f"btn_defeat_{which}" in self.r.book.marks else (0.0, (0, 0, 0, 0))
        if sc <= 0:
            return BOX[f"defeat.{which}"]
        return (x - (60.0 if which == "retry" else 80.0), y - 6.0, 230.0, 40.0)

    def _loss_cause(self, s: Seen) -> tuple[str | None, list[float]]:
        """这一场是怎么输的。首领战的失败页面上有每个人的血条：还有人活着 = 时间到了（伤害不够）；全空 = 队伍倒了。
        普通战的失败页面上没有这些，看不出来，返回 None。"""
        book = self.r.book
        if "btn_defeat_retry" not in book.marks:
            return None, []
        sc, (_x, y, _w, _h) = book.find_mark(s.img, "btn_defeat_retry")
        if sc <= 0 or y < 652:                       # 按钮在上面那个位置：普通战的失败页面
            return None, []
        hp = CD.defeat_hp(s.img)
        return ("timeout" if any(v > 0.02 for v in hp) else "wiped"), hp

    def _estimate(self, units: list[ST.Unit], plan: ST.TeamPlan, tweak: dict[str, Any] | None, side: str | None,
                  avoid: dict[str, float] | None) -> dict[str, Any] | None:
        """按战斗估算挑队。返回 {"pick": 要换成的队（不用换是 None）, "lines": 写进日志的话, "event": 记进记录的数}；这一场估算不了返回 None。
        用户 2026-11-19 夜定的：以前的选人规则都推倒，按模拟来。所以规则排出来的几种队（全输出、带坦克、带奶、都带 × 不限 / 物理队 / 法队）
        只当搜索的起点，对策表里的 side / need / always 不再限制它；从最好的起点出发在整个名单里换人推演（AD.ROUNDS 轮），上估算最好的。"""
        adv = self.advisor
        if adv is None or self.battle_kind not in ("extreme", "boss") or not self.enemy:
            return None
        stage = adv.stage(self.enemy, self.area or None)
        if stage is None:
            return None
        if (tweak or {}).get("no_est"):              # 这个敌人的推演和真机对不上（对策表里写了 no_est）：不拿它挑队，照攻略对策排的那一队上
            self.r.log.say(f"      （{self.enemy}：战斗估算和真机上的结果对不上，这一关不用估算，上按攻略对策排的这一队。）")
            return None
        known = [u for u in units if adv.knows(u.name)]
        if len(known) < 5 or len(plan.team) != 5:
            return None
        seeds: list[list[ST.Unit]] = [list(plan.team)]
        base = {k: v for k, v in (tweak or {}).items() if k not in ("need", "always", "heal_min", "heals", "strict", "_facts")}

        def variants(tw: dict[str, Any], sides: tuple) -> list[list[ST.Unit]]:
            out = []
            for need in ([], ["tank"], ["heal"], ["tank", "heal"]):
                for sd in sides:
                    try:
                        p = ST.choose_team(known, self.battle_kind, self.weak, 1, tweak={**tw, "need": list(need)}, side=sd, targets=self.targets,
                                           profile="burst", avoid=avoid)
                    except Exception:  # noqa: BLE001
                        continue
                    if len(p.team) == 5:
                        out.append(list(p.team))
            return out

        seeds += variants(base, (None, "phys", "magic"))
        lost = [t.get("team") or [] for t in self.tries] + (self.wins.lost(self.enemy) if self.wins is not None else [])
        mods = self._mods()
        cache: dict = {}
        try:
            # 玩家自己没有的角色（借来的，练度低）：推演是把她当满练度算的，所以先扣——最优先上自己有的（一队里起码的输出位不够时除外）
            own_n = ST.own_dealers(known)
            own_fit = (lambda team: AD.OFF_OWN * ST.unowned_cost(team, own_n)) if any(u.owned is False for u in known) else None
            got = adv.search(known, stage, mods, seeds, lost=lost, wins=self.run_wins, fit=own_fit, cache=cache)
        except Exception as e:  # noqa: BLE001
            self.r.log.say(f"      战斗估算出错了（{type(e).__name__}: {e}），这一场照规则排的队上。")
            return None
        if got is None:
            return None
        # 极难关按攻略来（2026-11-27 用户定的两句：“把所有极难关按攻略优化一下”“秒不掉 boss 的情况就走机制”）：
        # 推演最好的那一队合攻略点名的要求 → 就上它；不合 → 秒得掉（按真机用时折算，敌人放大招之前就打完）就不管机制，秒不掉就在合攻略的队里重新挑
        guide: dict[str, Any] | None = None
        free = got
        if self.battle_kind == "extreme" and tweak:
            facts = ST.roster_facts(known, tweak)
            gaps = ST.guide_gaps(got["team"], facts, tweak)
            guide = {"mode": "fits", "gaps": [g for g, _ in gaps]}
            if gaps:
                own = self.wins.est_factor(self.enemy) if self.wins is not None else None
                real_x = max(float(tweak.get("real_x") or AD.REAL_X), float(own[0]) if own else 0.0)
                fast = False
                if not tweak.get("no_burst"):
                    try:
                        fast, _bn, _bp = adv.burstable([u.name for u in got["team"]], stage, mods, real_x)
                    except Exception:  # noqa: BLE001
                        fast = False
                guide.update(mode="burst" if fast else "mech", real_x=real_x, no_burst=bool(tweak.get("no_burst")))
                if not fast:
                    fit = lambda team: (AD.OFF_GUIDE * sum(n for _, n in ST.guide_gaps(team, facts, tweak))      # noqa: E731
                                        + (own_fit(team) if own_fit is not None else 0.0))
                    try:
                        again = adv.search(known, stage, mods, [list(plan.team)] + variants({**base, "strict": True}, (None,)) + seeds,
                                           lost=lost, wins=self.run_wins, fit=fit, cache=cache, budget=AD.GUIDE_BUDGET)
                    except Exception:  # noqa: BLE001
                        again = None
                    if again is not None:
                        got = again
                        got["tried"] = len(cache)
                    guide["left"] = [g for g, _ in ST.guide_gaps(got["team"], facts, tweak)]
        rule = [u.name for u in plan.team]
        pick = [u.name for u in sorted(got["team"], key=lambda z: z.order)]
        rule_res = None
        if all(adv.knows(n) for n in rule):
            _v, rn, rp = adv.run(rule, stage, mods)
            rule_res = (rn, rp)
        same = set(rule) == set(pick)
        lines = [f"      战斗估算（按技能数值推演，不是真打；推演了 {got['tried']} 队；秒是游戏计时器走的秒，不是现实时间）："]
        if rule_res is not None:
            lines.append(f"        原来规则会排的队 {'、'.join(rule)}：{AD.say(rule_res[0])}；往坏里估（敌人再疼四成、我方输出打七五折）：{AD.say(rule_res[1])}。")
        front_of = lambda team: min(team, key=lambda z: z.pos if z.pos is not None else 9999).name      # noqa: E731
        if guide is not None and guide["mode"] == "mech":
            fnames = [u.name for u in sorted(free["team"], key=lambda z: z.order)]
            lines.append(f"        只看推演的话最快的是 {'、'.join(fnames)}（{AD.say(free['nom'])}），但它不合攻略点名的打法：{'；'.join(guide['gaps'])}。")
            lines.append("        " + ("这一关的机制从开打就起作用（或者推演没在真机上核过），不看秒不秒得掉" if guide["no_burst"]
                                     else f"按真机的用时折算（这个敌人真机上大约是推演的 {guide['real_x']:g} 倍），它放大招之前打不完，秒不掉") + "：按攻略的机制来。")
            lines.append(f"        合攻略的队里推演最好的是 {'、'.join(pick)}（最前面 {front_of(got['team'])}）：{AD.say(got['nom'])}；往坏里估：{AD.say(got['pes'])}。"
                         + ("就是规则排的那一队。" if same else "上这一队。"))
            if guide.get("left"):
                lines.append(f"        （名单里凑不齐攻略的全部要求，这一队还差：{'；'.join(guide['left'])}。）")
        elif same:
            lines.append("        在名单里换人推演下来没有比它更好的，就上这一队。")
        else:
            lines.append(f"        估算最好的是 {'、'.join(pick)}（最前面 {front_of(got['team'])}）：{AD.say(got['nom'])}；往坏里估：{AD.say(got['pes'])}。上这一队。")
        if guide is not None and guide["mode"] == "burst":
            lines.append(f"        这一队不合攻略点名的打法（{'；'.join(guide['gaps'])}），但按真机的用时折算（大约是推演的 {guide['real_x']:g} 倍）"
                         "它放大招之前就打得完、没人倒：秒得掉，不用管机制。")
        # 估算准不准，拿真机上的记录核一下：这个敌人以前实际用时是估算的几倍；乘上去超过 90 秒，就是“估算说能打完、真机上打不完”
        distrust = None
        fac = self.wins.est_factor(self.enemy) if self.wins is not None else None
        fac_all = self.wins.est_factor_all() if self.wins is not None else None
        if fac is not None and got["nom"].win and got["nom"].time * fac[0] > WN.TIME_LIMIT:
            distrust = fac[0]
            lines.append(f"        但是这个敌人真机上的用时是估算的 {fac[0]:g} 倍左右（看了 {fac[1]} 场的记录），照这个算这一队要 {got['nom'].time * fac[0]:.0f} 秒，90 秒里打不完："
                         "估算对它不准，这一场不按估算换队，上按攻略对策排的那一队。")
        elif fac is not None and abs(fac[0] - 1.0) >= 0.3:
            lines.append(f"        （这个敌人真机上的用时是估算的 {fac[0]:g} 倍左右，这一队实际大约要 {got['nom'].time * fac[0]:.0f} 秒。）")
        elif fac is None and fac_all is not None and got["nom"].win and abs(fac_all[0] - 1.0) >= 0.3:
            lines.append(f"        （以往打赢的 {fac_all[1]} 场里，实际用时是估算的 {fac_all[0]:g} 倍左右，这一队实际大约要 {got['nom'].time * fac_all[0]:.0f} 秒。）")
        skipped = sorted(set(got["nom"].skipped) | set(got["pes"].skipped))
        if guide is not None and guide["mode"] != "fits":
            guide["free"] = [u.name for u in sorted(free["team"], key=lambda z: z.order)]
        if distrust is not None:
            event = {"stage": stage, "pick": rule, "nom": AD.brief(got["nom"]), "pes": AD.brief(got["pes"]), "tried": got["tried"], "distrust": distrust,
                     "rule_nom": AD.brief(rule_res[0]) if rule_res else None, "rule_pes": AD.brief(rule_res[1]) if rule_res else None, "skipped": skipped, "guide": guide,
                     "mods": {k: (round(v, 3) if isinstance(v, (int, float)) else v) for k, v in mods.items()}}
            return {"pick": None, "lines": lines, "event": event}
        event = {"stage": stage, "pick": pick, "nom": AD.brief(got["nom"]), "pes": AD.brief(got["pes"]), "tried": got["tried"], "mods": {k: (round(v, 3) if isinstance(v, (int, float)) else v) for k, v in mods.items()},
                 "rule_nom": AD.brief(rule_res[0]) if rule_res else None, "rule_pes": AD.brief(rule_res[1]) if rule_res else None, "skipped": skipped, "guide": guide}
        return {"pick": None if same else got["team"], "lines": lines, "event": event}

    def _remembered(self, units: list[ST.Unit]) -> dict[str, Any] | None:
        """这个敌人以前在真机上打赢过的队里，现在名单凑得齐、这一场还没输过的最快的那一队。没有返回 None。"""
        if self.wins is None or not self.enemy or self.battle_kind not in ("extreme", "boss"):
            return None
        if self.battle_kind == "boss" and self._boss_teams() > 1:
            return None
        if self.tier.guards:                         # 保通关档自己有一套带人的规矩（第一次就带坦克、治疗），不套用别的档位赢过的队
            return None
        by = {u.name: u for u in units if u.name}
        rec = self.wins.best(self.enemy, set(by), skip=[set(t.get("team") or []) for t in self.tries])
        if rec is None:
            return None
        took = f"最快游戏里 {rec['game']} 秒" if rec["game"] is not None else (f"最快现实 {rec['real']:.0f} 秒" if rec["real"] is not None else "用时没记到")
        self.r.log.say(f"      这个敌人（{self.enemy}）以前在真机上用 {'、'.join(rec['team'])} 打赢过 {rec['wins']} 次"
                       + (f"、输过 {rec['losses']} 次" if rec["losses"] else "") + f"（{took}），名单里凑得齐：直接上这一队，不再推演。")
        self.r.log.event("remembered_team", enemy=self.enemy, team=rec["team"], wins=rec["wins"], losses=rec["losses"], game=rec["game"])
        return dict(rec, units=[by[n] for n in rec["team"]])

    def _remember(self, win: bool) -> None:
        """这一场打完：先记进这一趟的战斗清单（小结里列“输了哪几场、哪几场最慢”用）；再把上场的队和结果按敌人记进账本
        （账本只记极难和单队打的首领战，五个人都认得出名字的）。"""
        self.fights.append({"area": self.area, "kind": self.battle_kind, "enemy": self.enemy, "win": bool(win), "game": self.last_game,
                            "real": self.last_secs, "attempt": self.attempt, "how": None if win else self.lost_how})
        if self.wins is None or not self.enemy or self.battle_kind not in ("extreme", "boss"):
            return
        if self.battle_kind == "boss" and self._boss_teams() > 1:
            return
        team = [n for n in self.last_team if "/" not in n]
        if len(team) != 5 or len(team) != len(self.last_team):
            return
        est = None                                   # 开打前战斗估算说这一队几秒打完（上的是规则排的队就看规则那一队的估算）
        le = self.last_est or {}
        res = le.get("rule_nom") if (le.get("kept_rule") or le.get("distrust")) else le.get("nom")
        if isinstance(res, dict) and res.get("win") and isinstance(res.get("sec"), (int, float)):
            est = float(res["sec"])
        self.wins.record(self.enemy, team, win, game=self.last_game, real=self.last_secs, area=self.area, tier=self.tier.n, kind=self.battle_kind,
                         est=est, how=None if win else self.lost_how)
        self.wins.save()

    def _mods(self) -> dict[str, Any]:
        """这一场推演用的条件：遗物、输过几次、按真机伤害校出来的每个角色的校正。"""
        mods: dict[str, Any] = AD.mods_for(self.series, self.attempt + self.tier.caution)     # 第三、四档：往坏处多想几档
        sims = self.dmg.sims() if self.dmg is not None else {}
        if sims:
            mods["unit_out"] = sims
        return mods

    # ---- 真机伤害 ----
    def _faces(self, s: Seen, boss_tab: int = 0) -> bool:
        """开打之前：把成员栏里每个位置的头像截下来、认一下是谁（打完去伤害报告里找同一张脸）。总是返回 True。
        首领战要翻三个页签才到「战斗开始」，那时成员栏里是第 3 队（常常是空的）：所以首领战在离开第 1 队的页签时就截（boss_tab=1），
        到点「战斗开始」时（boss_tab=3）已经有第 1 队的头像就不再截。"""
        self.report_done = False                     # 新的一场：伤害报告还没看
        self.last_secs = self.last_game = None
        self.last_shares = {}
        if boss_tab >= 2 and self.faces_tab == 1 and any(f is not None for f in self.faces):
            return True
        self.faces, self.face_names, self.faces_tab = [], [], boss_tab
        if not self.report_on or self.team_mode != "role":
            return True
        try:
            self.faces = RP.member_faces(s.img)
            norm = to_norm(s.img)
            for i, f in enumerate(self.faces):
                name = None
                if f is not None:
                    name, _score = self.chars.identify(CD.fingerprint(norm, TM.SLOT_X0 + TM.SLOT_DX * i, TM.SLOT_Y))
                self.face_names.append(name if name in self.last_team else None)
        except Exception as e:  # noqa: BLE001  这一步出什么错都不该挡住开打
            self.faces, self.face_names = [], []
            self.r.log.say(f"      （记成员栏头像时出错：{type(e).__name__}: {e}——这一场不看伤害报告）")
        return True

    def _damage_report(self, s: Seen, where: str = "win") -> bool:
        """点开「伤害报告」，读每个人打了多少，记下来，点「确认」关掉。点开过返回 True（主流程重新看画面）。
        where：win = 普通战 / 极难的 WIN!（按钮在右上角）；boss = 首领战的 WIN!（按钮在「第 N 战 胜利」那一行）；defeat = 战斗失败（右上角）。
        只点这一个按钮和弹窗里的「确认」；弹窗开着却认不出来、也关不掉，就停下（拿不准就停）。"""
        r = self.r
        if self.report_done or not self.report_on or self.team_mode != "role":
            return False
        if not any(f is not None for f in self.faces):
            self.report_done = True
            return False
        if where == "boss":
            if not RP.boss_button(to_norm(s.img)):   # 还没显示出来：这一轮先不看，下一轮再瞧
                return False
            box = RP.BTN_BOSS
        else:
            seen, note = RP.button_seen(s.img, r.book)
            if not seen:                             # 这张画面上没有「伤害报告」（已经翻到「获得道具」那张了，或者按钮没认出来）
                self.report_done = True
                r.log.say(f"      这张画面右上角没看到「伤害报告」（{note}），这一场不看伤害。")
                r.log.event("damage_report", ok=False, why="no_button", note=note, where=where)
                return False
            box = RP.BTN_WIN
        self.report_done = True                      # 一场只看一次
        if r.tap(s, box, "伤害报告（看这一场每个人打了多少）") == "changed":
            return True
        back = ("defeat",) if where == "defeat" else ("win", "win_next", "win_crown")
        rep, s2, last = None, s, None
        for i in range(6):                           # 弹窗弹出来、条长到位要一点时间：两次看到的条一样长才算稳了
            r.pause(0.9 if i == 0 else 0.45)
            s2 = r.look()
            rep = RP.read_report(s2.img, self.faces, numbers=False)
            if rep.open and rep.rows:
                now = [x["ratio"] for x in rep.rows]
                if now == last:
                    break
                last = now
            elif rep.close is not None and (rep.matched or i >= 1):
                break
        if rep.open and rep.rows:
            rep = RP.read_report(s2.img, self.faces)     # 稳了：这一次连数字一起读
        shot = r.log.shot(s2.img, "damage_report", png=True)
        if rep.close is None:
            if s2.page in back and not rep.title:
                r.log.say("      点了「伤害报告」但弹窗没出来，这一场不看了。")
                r.log.event("damage_report", ok=False, why="not_opened", shot=shot, where=where)
                return True
            # 弹窗开着但不是认识的样子：读到了多少先记多少，再按“只有一个按钮的大弹窗，按钮在下面正中”的位置点一下试试；点了两次还回不去才停。
            if rep.matched:
                self._record_damage(rep, shot, where)
            for _ in range(2):
                r.tap(s2, RP.CLOSE_GUESS, "确认（弹窗不是认识的样子，按大弹窗的按钮常在的位置点）")
                r.pause(0.9 * self.patience + self.beat)
                s2 = r.look()
                if s2.page in back:
                    r.log.say("      伤害报告的弹窗不是我认识的样子，按常见的位置点掉了（截图存了，把记录给我，我照着把读法对上）。")
                    r.log.event("damage_report", ok=False, why="close_by_guess", shot=shot, texts=rep.texts[:40], where=where)
                    return True
            r.log.event("halt", why="damage_report", shot=shot, texts=rep.texts[:40])
            raise Halt("点开了「伤害报告」，但弹窗不是我认识的样子，按常见的位置点了两次也没关掉——请手动把它关掉再重新开始，截图在记录里。"
                       "（不想让它看伤害：界面上把「看伤害报告」的勾去掉）")
        self._record_damage(rep, shot, where)
        for _ in range(3):                           # 点「确认」；万一没关掉就再看一次再点
            x, y, w, h = rep.close
            r.tap(s2, (float(x), float(y), float(w), float(h)) if rep.open else (x - 8.0, y - 5.0, w + 16.0, h + 10.0), "确认（关掉伤害报告）")
            r.pause(0.8)
            s2 = r.look()
            if s2.page in back:
                break
            rep = RP.read_report(s2.img, [], numbers=False)
            if rep.close is None:                    # 弹窗已经不在了：正在收起来，交回主流程等它
                break
        return True

    def _record_damage(self, rep: "RP.Report", shot: str, where: str = "win") -> None:
        r = self.r
        slots = [k for k, f in enumerate(self.faces) if f is not None]          # 空位不算人
        names = [self.face_names[k] if k < len(self.face_names) else None for k in slots]
        damage = [rep.damage[k] if k < len(rep.damage) else None for k in slots]
        roles = [self.last_roles.get(n) if n else None for n in names]
        result = "lose" if where == "defeat" else "win"
        sim_share = None
        stage = (self.last_est or {}).get("stage")
        if self.advisor is not None and stage and all(n and self.advisor.knows(n) for n in names) and len(names) == 5:
            try:
                _v, nom, _p = self.advisor.run([n for n in names if n], stage, self._mods())
                tot = float(sum(nom.dealt.values()))
                sim_share = {n: nom.dealt.get(n, 0.0) / tot for n in names if n} if tot > 0 else None
            except Exception:  # noqa: BLE001
                sim_share = None
        res = self.dmg.record([n or "?/?" for n in names], roles, damage, sim_share, battle=self.battle_kind, enemy=self.enemy, area=self.area,
                              attempt=self.attempt, seconds=self.last_secs, game=self.last_game, result=result, shot=shot, unit=rep.unit,
                              raw=[v for v, _b in rep.numbers][:30])
        self.dmg.save()
        self.chars.rates = self.dmg.rates()
        r.log.event("damage_report", ok=bool(res["full"]), shot=shot, team=names, roles=roles, shares={n: round(v, 4) for n, v in res["shares"].items()},
                    sim_shares={n: round(v, 4) for n, v in (sim_share or {}).items()}, rate=res["rate"], sim=res["sim"], where=where, result=result,
                    **RP.as_event(rep))
        self.last_shares = dict(res["shares"]) if res["full"] else {}
        if not res["full"]:
            r.log.say(f"      伤害报告：弹窗里有 {len(rep.rows) or len(rep.numbers)} 行，上场的 {len(names)} 个人里对上了 {sum(1 for d, n in zip(damage, names) if d is not None and n)} 个"
                      "——没对全，这一场只存截图和原始数字，不调比重。")
            return
        total = float(sum(d for d in damage if d is not None))
        order = sorted(zip(names, damage), key=lambda z: -(z[1] or 0))
        if rep.unit == "bar":
            r.log.say("      伤害报告（数字没读出来，按每个人那根条的长度算的占比）：" + "、".join(f"{n} {d / total * 100:.0f}%" for n, d in order))
        else:
            r.log.say("      伤害报告：" + "、".join(f"{n} {d / total * 100:.0f}%（{d / 1e4:.0f} 万）" for n, d in order)
                      + (f"；合计 {total / 1e4:.0f} 万" if total else ""))
        if sim_share:
            off = sorted(((n, sim_share.get(n, 0.0), res["shares"].get(n, 0.0)) for n in names), key=lambda z: -abs(z[1] - z[2]))
            r.log.say("        战斗估算原来以为：" + "、".join(f"{n} {a * 100:.0f}%" for n, a, _b in sorted(off, key=lambda z: -z[1]))
                      + f"。差得最多的是 {off[0][0]}（估算 {off[0][1] * 100:.0f}%，实际 {off[0][2] * 100:.0f}%）。")
        if res["rate"]:
            r.log.say("        输出角色的比重：" + "、".join(f"{n} {a:g}→{b:g}" for n, (a, b) in res["rate"].items()) + "（增益、坦克、治疗不参加这个比较）")

    def _weak_dealers(self) -> tuple[list[str], list[str]]:
        """刚看的那张伤害报告里，哪几个输出角色打得少（下一次换掉）、谁打得多（留着）。只拿“该打输出的人”（攻击 / 破防）来比，
        增益、减益、坦克、治疗不看她自己打了多少。返回（打得少的, 打得多的）；报告没读全返回 ([], [])。"""
        shares = getattr(self, "last_shares", None) or {}
        if len(shares) < 2:
            return [], []
        even = 1.0 / len(shares)
        dealers = [(n, v) for n, v in shares.items() if self.last_roles.get(n) in DM.DAMAGE_ROLES]
        weak = [n for n, v in dealers if v < 0.6 * even]
        if not weak and len(dealers) >= 2:
            weak = [min(dealers, key=lambda z: z[1])[0]]
        strong = [n for n, v in shares.items() if v >= 1.5 * even and n not in weak]
        return weak, strong

    def damage_lines(self, top: int = 40) -> list[str]:
        """到现在为止记过伤害的输出角色（一局结束时写进日志）。"""
        if self.dmg is None:
            return []
        rows = [x for x in self.dmg.table() if x.get("role") in DM.DAMAGE_ROLES]
        if not rows:
            return []
        return ["      真机伤害记录（输出角色，按比重从高到低；比重 1 = 没调过）："] + [
            f"        {x['name']}：比重 {float(x.get('rate', 1.0)):g}，记了 {x['n']} 场，平均占全队 {float(x.get('share', 0)) * 100:.0f}%" for x in rows[:top]]

    def _team_tweak(self) -> dict[str, Any] | None:
        """这一场编队用的对策：对策表里这个敌人的那一条；首领战页面上游戏自己写着“坦克型”的，再加一条“要带坦克”。"""
        tw = self.tweak
        if self.eff_tank and "tank" not in ((tw or {}).get("need") or []):
            tw = dict(tw or {})
            tw["need"] = list(tw.get("need") or []) + ["tank"]
        return tw

    def _on_defeat(self, s: Seen) -> None:
        """战斗失败：先换一套打法「重新挑战」；超过次数就「结束」，回地图撤退（不带奖励，通行证退回），外面再重开。"""
        r = self.r
        if self.fighting:                            # 这一场刚输：只记一次
            self.fighting = False
            if not self.battle_logged:
                r.log.event("battle_end", n=self.battles + 1, seconds=None, result="lose", battle=self.battle_kind, attempt=self.attempt,
                            team=list(self.last_team), enemy=self.enemy, est=self.last_est)
                self.chars.record_battle([n for n in self.last_team if "/" not in n], self.battle_kind, None, False)
                self.chars.save()
                self.last_secs = self.last_game = None
                self._remember(False)
            self.battle_logged = False
            self.losses += 1
            self.attempt += 1
            r.log.shot(s.img, "defeat", png=True)
            page_how, hp = self._loss_cause(s)
            log = list(self.hp_log)
            if page_how is None and log:             # 普通战 / 极难的失败页面上没有血条：看战斗中最后一次读到的
                alive = [v for v in log[-1][1] if v > 0.02]
                if not (len(alive) >= 2 and sum(alive) / len(alive) > 0.3):      # 只剩一个残血的：当作倒光了（最后一下没赶上读）
                    log.append((log[-1][0] + 0.5, [0.0] * len(log[-1][1])))
            self.lost_how = ST.loss_cause(log, hp if page_how is not None else None)
            say = {"timeout": f"时间到了输的：还有 {sum(v > 0.02 for v in (hp or (log[-1][1] if log else [])))} 个人活着——伤害不够，不是扛不住。保命的人不动，输出换一批",
                   "front": "从最前面开始一个个倒的（第一个人倒下时后面的人血还多）：下一次加一个站最前面的坦克",
                   "collapse": "全队血量一起崩的（第一个人倒下时其他人也没剩多少血）：下一次加治疗",
                   "wiped": "队伍倒了，但战斗中的血量没读清，分不出是怎么倒的：先加攻略点名的，没有就先坦克后治疗"}.get(self.lost_how or "")
            if say:
                r.log.say(f"      这一场是{say}。")
            self.tries.append({"how": self.lost_how, "team": [n for n in self.last_team if "/" not in n], "had": list(self.last_had),
                               **({"front": self.last_front[0], "front_tough": self.last_front[1]} if self.last_front else {})})
            r.log.event("defeat_cause", how=self.lost_how, hp=hp, battle=self.battle_kind, attempt=self.attempt,
                        hp_log=[[t, v] for t, v in log[:: max(1, len(log) // 40)]])
            self.tb = None
            self.team_changed = self.equip_done = self.auto_done = False
            self.defeat_report = self.lost_how == "timeout" and not self.no_mech     # 伤害不够输的：点「重新挑战」之前先看伤害报告，下一次换谁有个依据（不重打的就不看了）
            if self.attempt <= self._retries() and self.battle_kind == "boss" and (self.area == 5 or self.tier.boss_more):
                self.boss_extra += 1                 # 最终首领：下一次多编一队。区域 3 首领第一、二档只用一队打（凹分要一队过），第三、四档输了可以多编
        if self.defeat_report:
            self.defeat_report = False
            if self._damage_report(s, "defeat"):
                weak, strong = self._weak_dealers()
                if self.tries and (weak or strong):
                    self.tries[-1]["weak"], self.tries[-1]["strong"] = weak, strong
                    sh = self.last_shares
                    r.log.say("      伤害不够，看了伤害报告：" + ("、".join(f"{n}（{sh.get(n, 0) * 100:.0f}%）" for n in weak) + " 打得少，下一次换掉" if weak else "输出角色之间差不多")
                              + ("；" + "、".join(f"{n}（{sh.get(n, 0) * 100:.0f}%）" for n in strong) + " 打得多，留着" if strong else "") + "。")
                return
        kind = KIND_CN.get(self.battle_kind, self.battle_kind) + (f"·{self.enemy}" if self.enemy else "")
        if self.attempt <= self._retries():
            r.log.say(f"      这一场（{kind}）输了，已经打了 {self.attempt} 次。换一套队伍再打（最多再打 {self._retries() - self.attempt + 1} 次）。")
            self._tap_wait(s, self._defeat_box(s, "retry"), "重新挑战（换一套队伍）")
        else:
            self.want_retreat, self.restart = True, True
            self.why_retreat = f"{kind}打了 {self.attempt} 次都没打过" + ("（名单里没有它非要不可的那种角色，不重打）" if self.no_mech else "")
            self.arriving = False
            r.log.say(f"      {self.why_retreat}：不打了，撤退重开。")
            r.log.event("gave_up_battle", battle=self.battle_kind, attempts=self.attempt)
            self._tap_wait(s, self._defeat_box(s, "end"), "结束（不再打这一场）")

    def _on_team(self, s: Seen) -> None:
        if self.team_mode == "role":
            self._on_team_role(s)
            return
        r = self.r
        tv = TM.read_team(r.book, s.img)
        if tv.tab:
            self._on_boss_team(s, tv)
            return
        checked = len(tv.cells) - len(tv.free)
        r.log.event("team", members=tv.members, empty=tv.empty_slots, listed=len(tv.cells), checked=checked, free=[c.index for c in tv.free])
        if self._team_settling(tv):
            return
        if tv.empty_slots > 0 and tv.free:
            c = tv.free[0]
            if r.tap(s, c.tap_box, f"上场：名单第 {c.index + 1} 格（成员栏还空 {tv.empty_slots} 个）") != "changed":
                self.team_changed = True
                self.team_expect = (tv.members + 1, c.cx, c.cy)
            r.pause(self.beat)
        elif tv.members == 0:
            if self._team_empty_again(s):
                return
            raise Halt("队伍编组里一个能上场的角色都没有" + self._no_cards_why(s))
        elif self.team_changed and not self.equip_done and self.auto_equip:
            self._tap_wait(s, BOX["team.equip"], "特别装备（队伍换过人，重新自动装备一次）")
        else:
            self._faces(s)
            if r.tap(s, BOX["team.start"], f"战斗开始（{tv.members} 人）") != "changed":
                self.fighting = True
                r.wait_leave(s.page)

    def _on_choice3(self, s: Seen, what: str) -> None:
        r = self.r
        btns = r.book.find_all(s.img, "btn_choose")
        if not btns:
            self.choice_wait += 1                    # 页面刚出来时按钮还在飞进来：等一等再看
            if self.choice_wait <= 6:
                r.pause(0.6 * self.patience)
                return
            r.hand_over(s, f"「{what}」页面上没找到「选择」按钮，这一步请你来选")
            r.wait_leave(s.page, 15.0)
            return
        if self.team_mode != "role":
            self.choice_wait = 0
            self._tap_wait(s, choose_button(btns[0][1]), f"选择（{what}，{len(btns)} 选 1，先选最左边）", think=True)
            return
        # 阶段 3：按规则选
        pick, label, after = 0, "", None
        if what == "角色加入奖励":
            cards = CD.recruit_cards(r.book, s.img)
            if all(c.role is None for c in cards) and self.choice_wait < 4:      # 卡片还在飞进来，图标没到位
                self.choice_wait += 1
                r.pause(0.5 * self.patience)
                return
            names = self._recruit_names(s, cards)
            show = [f"{n}[{c.text}]" if n else c.text for n, c in zip(names, cards)]
            # 职能按实际用法算（有的强力增益被游戏标成了治疗）；增益、强化、减益型看她帮的是物理队还是法队
            roles = [self.chars.role_as(n) or c.role for n, c in zip(names, cards)]
            sides = [self.chars.atk(n) if (r in ST.DAMAGE or not self.chars.aid(n)) else self.chars.aid(n) for n, r in zip(names, roles)]
            wants = {"roles": [x for x in (self.boss_wants.get("roles") or []) if not (x == "heal" and self.roster_heal)],      # 名单里已经有“有奶”的人就不用再专门拿奶
                     "tags": [t for t in (self.boss_wants.get("tags") or []) if t not in self.roster_tags]}
            pick, why = ST.choose_recruit([(r, c.attr) for r, c in zip(roles, cards)], self.roster, tags=[self.chars.tags(n) for n in names],
                                          atks=sides, side=self.recruit_side, wants=wants,
                                          powers=[1.0 if self.chars.is_pvp(n) else self.chars.power(n) for n in names],     # 纯竞技场用的角色：招募时按最低强度算
                                          heals=[self.chars.heal(n) for n in names], owned=[self.chars.owns(n) for n in names])
            label = f"选择第 {pick + 1} 个（{show[pick]}，{why}；三个是 {'、'.join(show)}）"
            r.log.event("recruit", cards=[[c.role, c.attr] for c in cards], names=names, pick=pick, roster=dict(self.roster),
                        atks=[self.chars.atk(n) for n in names], side=self.recruit_side, power=[self.chars.power(n) for n in names], wants=wants,
                        owned=[self.chars.owns(n) for n in names])
            after = ("role", roles[pick], names[pick], cards[pick].attr)
        else:
            marks = CD.mark_attrs(r.book, s.img)
            if any(m is not None for m in marks):
                values = self._mark_values()
                pick, why = ST.choose_mark(marks, values=values)
                label = f"选择第 {pick + 1} 个（{CD.ATTR_CN[marks[pick]]}属性的印记；三个是 {'、'.join(CD.ATTR_CN[m] for m in marks)}）"
                r.log.say(f"      选哪个属性的印记：{why}。" + ("" if values else "（账号里有哪些角色还不知道——先点一次「读角色」，之后就按账号里的角色来选。）"))
                r.log.event("mark_pick", attrs=marks, pick=pick, values=values or None)
            else:
                opts = CD.relic_options(r.book, s.img)
                if all(o[0] is None for o in opts) and self.choice_wait < 4:
                    self.choice_wait += 1
                    r.pause(0.5 * self.patience)
                    return
                pick, why = ST.choose_relic(opts, self.series)
                label = (f"选择第 {pick + 1} 个（{CD.SERIES_CN[opts[pick][0]]} ★{opts[pick][1]}，{why}；"
                         f"三个是 {'、'.join(f'{CD.SERIES_CN[o[0]]}★{o[1]}' for o in opts)}）")
                r.log.event("relic_pick", options=[[o[0], o[1]] for o in opts], pick=pick, levels=dict(self.series))
                after = ("series", opts[pick])
        self.choice_wait = 0
        pick = min(pick, len(btns) - 1)
        if self._tap_wait(s, choose_button(btns[pick][1]), label, think=True) != "changed" and after is not None:
            if after[0] == "role" and after[1]:
                self.roster[after[1]] = self.roster.get(after[1], 0) + 1
                if after[2]:
                    self.run_units[after[2]] = (after[3], after[1])
                    self.roster_heal = self.roster_heal or after[1] == "heal" or self.chars.heal(after[2]) >= 1
            elif after[0] == "series" and after[1][0]:
                self.series[after[1][0]] = self.series.get(after[1][0], 0) + max(1, after[1][1])

    def _mark_values(self) -> dict[str, dict[str, float]]:
        """连结印记选哪个属性：按账号主人有哪些角色来算（没读过角色就返回空的，那就按固定顺序）。
        随机印记是从账号里还没进这一局的角色里抽的，所以看每个属性“还能抽到的角色”平均有多强，再看这一局已经有几个这个属性的人。"""
        owned = self.chars.owned()
        if not owned:
            return {}
        cb = self.chars
        pool = [(cb.attrs.get(n) or (cb.roster.get(n) or {}).get("attr"), cb.power(n), cb.role_as(n) or (cb.roster.get(n) or {}).get("role"))
                for n in owned if n not in self.run_units]
        return ST.attr_values(pool, list(self.run_units.values()) + list(self.run_unnamed))

    # ---- 商店 ----
    def _shop_note(self, sh: dict[str, Any]) -> str:
        n_relic = sum(1 for b in sh["bought"] if b[0] == "relic")
        n_char = len(sh["bought"]) - n_relic
        parts = ([f"遗物 {n_relic} 个"] if n_relic else []) + ([f"随机印记 {n_char} 个（多 {n_char} 名角色）"] if n_char else [])
        return (("买了 " + "、".join(parts)) if parts else "什么都没买") + (f"，更新 {sh['refreshes']} 次" if sh["refreshes"] else "") \
            + f"，一共花了 {sh['spent']:,} 金币" + (f"，还剩 {sh['coins']:,}" if sh["coins"] is not None else "")

    def _shop_close(self, s: Seen, why: str) -> None:
        sh = self.shop
        assert sh is not None
        if not sh["closing"]:
            sh["closing"] = True
            self.r.log.say(f"      这家商店：{self._shop_note(sh)}。（{why}）")
            done = {"area": self.area, "bought": [list(b) for b in sh["bought"]], "refreshes": sh["refreshes"], "spent": sh["spent"],
                    "coins": sh["coins"], "skipped": [list(k) for k in sh["skip"]], "why": why}
            self.shops.append(done)
            self.r.log.event("shop_done", **done)
        self._tap_wait(s, BOX["shop.close"], "关闭（商店逛完了）")

    def _on_shop(self, s: Seen) -> None:
        """商店：看一眼商品 → 买一件 / 更新一批 / 关闭。每次只做一步，做完回到主循环重新看。"""
        r = self.r
        if not self.shop_buy:
            self._tap_wait(s, BOX["shop.close"], "关闭（设置里关了商店购买，不买东西）")
            return
        if self.shop is None:
            self.shop = {"refreshes": 0, "bought": [], "skip": set(), "pending": None, "refresh_wait": False, "no_refresh": False,
                         "blur": 0, "swipes": 0, "closing": False, "coins": None, "spent": 0, "misses": 0, "said": False,
                         "need_top": True, "top_tries": 0, "bottom": False, "drag_from": None}
        sh = self.shop
        if sh["closing"]:
            self._tap_wait(s, BOX["shop.close"], "关闭（商店逛完了）")
            return
        pend = sh["pending"]
        if pend is not None:
            if not pend.get("done"):                 # 点了「购买」却没买成（对话框没弹出来，或者取消了）
                sh["misses"] += 1
            sh["pending"] = None
        sh["refresh_wait"] = False
        view = SH.read_shop(r.book, s.img)
        r.pause(0.25 * self.patience)                # 列表拖完会回弹、买完东西会重新排：隔一小会儿再看一眼，两眼一样才动手
        again = SH.read_shop(r.book, r.look().img)
        steady = again.rows == view.rows and [it.as_list() for it in again.items] == [it.as_list() for it in view.items]
        if not steady or not view.rows or any(it.state == "unknown" or (it.state != "sold" and it.price is None) for it in view.items):
            sh["blur"] += 1                          # 还在动 / 商品还没显示全 / 有东西挡着：等一下再看
            if sh["blur"] <= 6:
                r.pause(0.4 * self.patience)
                return
            r.log.shot(s.img, "shop_unreadable", png=True)
            self._shop_close(s, "商品看不清，不买了")
            return
        sh["blur"] = 0
        if view.coins is not None:
            sh["coins"] = view.coins
        # 商品是一排一排的（普通商店 2 排，卖 ★4 遗物的那种 3 排），一眼最多看全两排的价格。做法是从最上面往下扫：
        # 这一眼里有要买的就买（卖掉的会排到最后，下面的会补上来，位置不变接着看）；没有了就往下拖一截；拖到底还没有，才考虑更新 / 离开。
        if sh["need_top"]:                           # 刚进来 / 刚更新完：应该停在最上面（只看得到第一排的价格）；不在就先拖回去
            if (len(view.rows) == 1 and abs(view.rows[0] - SH.ROW_TOP) <= 4) or sh["top_tries"] >= 3:
                sh["need_top"] = False
            else:
                sh["top_tries"] += 1
                sh["swipes"] += 1
                r.swipe(s, SHOP_DRAG[1], (SHOP_DRAG[0][0], SHOP_DRAG[0][1] + 70.0), "把商品列表拖回最上面", duration=0.5, hold_end=0.3)
                r.pause(self.beat + 0.3 * self.patience)
                return
        if sh["drag_from"] is not None:              # 上一步往下拖过：画面一点没动，说明已经到底了
            if view.rows == sh["drag_from"]:
                sh["bottom"] = True
            sh["drag_from"] = None
        at_bottom = sh["bottom"] or view.rows[-1] >= SH.ROW_BOTTOM - 14
        if not sh["said"]:
            sh["said"] = True
            r.log.say("      商店里看到：" + "、".join(it.text + ("" if it.state == "buy" else f"（{SH.STATE_CN[it.state]}）") for it in view.items)
                      + (f"；手里有 {view.coins:,} 金币" if view.coins is not None else "；金币数没读出来"))
            r.log.event("shop", area=self.area, items=[it.as_list() for it in view.items], coins=view.coins, refresh=view.refresh, rows=view.rows)
        if len(sh["bought"]) >= SHOP_MAX_BUYS or sh["misses"] >= 4:
            self._shop_close(s, "买的件数到上限了" if len(sh["bought"]) >= SHOP_MAX_BUYS else "点了几次「购买」都没买成，不买了")
            return
        # 这家店打了几折（公会效果，一局里不变）：货架上认得出来的商品一算就知道；这一眼算不出来（都卖完了、只剩不认识的）就沿用这一局前面算出来的
        seen_f = ST.shop_discount([it.as_list() for it in view.items])
        if seen_f < 1.0 or self.shop_factor is None:
            if seen_f < 1.0 and (self.shop_factor is None or abs(seen_f - self.shop_factor) > 0.02):
                r.log.say(f"      这家商店打折：价是平常的 {seen_f * 100:.0f}%。买不买照平常的价来判断，要留的钱按折后的算。")
            self.shop_factor = seen_f
        act, idx, why = ST.choose_shop([it.as_list() for it in view.items], view.coins, view.refresh and not sh["no_refresh"],
                                       sh["refreshes"], self.area >= 5, tuple(sh["skip"]), self.shop_rate, self.shop_factor)
        if act == "buy" and idx is not None:
            it = view.items[idx]
            sh["pending"] = {"item": it.as_list(), "text": it.text, "coins": view.coins, "tries": 0}
            self._tap_wait(s, it.box, f"购买（{it.text} 金币，{why}）")
        elif not at_bottom and sh["swipes"] < 24:    # 这一眼里没有要买的：往下看
            sh["swipes"] += 1
            sh["drag_from"], sh["said"] = list(view.rows), False
            r.swipe(s, SHOP_DRAG[0], SHOP_DRAG[1], "把商品列表往上拖（看下面一排的价格）", duration=0.5, hold_end=0.3)
            r.pause(self.beat + 0.3 * self.patience)
        elif act == "refresh":
            sh["refresh_wait"] = True
            self._tap_wait(s, BOX["shop.refresh"], f"更新商品（{why}）")
        else:
            self._shop_close(s, why)

    def _on_buy(self, s: Seen) -> None:
        """购买确认：先核对——花的是阿尔法金币、持有数和买完剩的数读得出来、差额正好是商品上的价格——才点「确认」；对不上就「取消」。"""
        r = self.r
        sh = self.shop
        pend = sh["pending"] if sh else None
        if sh is None or pend is None or pend.get("done"):
            r.log.shot(s.img, "buy_unexpected", png=True)
            self._tap_wait(s, BOX["buy.cancel"], "取消（这个「购买确认」不是我点出来的）")
            return
        price = pend["item"][4]
        have, left = SH.read_buy(r.book, s.img)
        ok = (r.book.has_mark(s.img, "buy_alpha") and have is not None and left is not None and have - left == price
              and (pend["coins"] is None or pend["coins"] == have))
        if ok:
            what = pend["text"].rsplit(" ", 1)[0]
            if r.tap(s, BOX["buy.ok"], f"确认（花 {price:,} 阿尔法金币买 {what}，买完剩 {left:,}）") != "changed":
                pend["confirmed"], pend["left"] = True, left
                r.wait_leave(s.page)
            return
        pend["tries"] += 1
        if pend["tries"] <= 4:                       # 数字上可能正盖着点击的光效：等一下再读
            r.pause(0.4 * self.patience)
            return
        r.log.shot(s.img, "buy_mismatch", png=True)
        r.log.say(f"      「购买确认」上的数对不上（商品上的价格 {price}，这里读到 持有 {have} → 剩 {left}），这件不买。")
        r.log.event("shop_buy_cancel", item=pend["item"], have=have, left=left, coins=pend["coins"])
        sh["skip"].add(tuple(pend["item"][:5]))
        pend["done"] = True                          # 这一件到此为止（不算“没买成”）
        self._tap_wait(s, BOX["buy.cancel"], "取消（金额对不上）")

    def _on_bought(self, s: Seen) -> None:
        r = self.r
        sh = self.shop
        pend = sh["pending"] if sh else None
        if sh is not None and pend is not None and pend.get("confirmed") and not pend.get("done"):
            pend["done"] = True
            kind, stars, series, role, price, _ = pend["item"]
            sh["bought"].append(pend["item"][:5])
            sh["spent"] += price
            sh["coins"] = pend.get("left", sh["coins"])
            if kind == "relic" and series:
                self.series[series] = self.series.get(series, 0) + max(1, stars)
            elif kind == "random" and role:
                self.roster[role] = self.roster.get(role, 0) + 1
            r.log.event("shop_buy", item=pend["item"][:5], left=pend.get("left"), n=len(sh["bought"]))
        self._tap_wait(s, BOX["bought.ok"], "确认（购买完毕）")

    def _on_refresh(self, s: Seen) -> None:
        """更新确认：核对花的是阿尔法金币、要花多少读得出来而且不超过上限，才点「确认」。"""
        r = self.r
        sh = self.shop
        if sh is None or not sh["refresh_wait"]:
            r.log.shot(s.img, "refresh_unexpected", png=True)
            self._tap_wait(s, BOX["refresh.cancel"], "取消（这个「更新确认」不是我点出来的）")
            return
        cost, have = SH.read_refresh(r.book, s.img)
        ok = (r.book.has_mark(s.img, "refresh_alpha") and cost is not None and have is not None
              and 0 < cost <= self.shop_refresh_max and have >= cost)
        if ok:
            if r.tap(s, BOX["refresh.ok"], f"确认（花 {cost} 阿尔法金币更新商品，手里有 {have:,}）") != "changed":
                sh["refreshes"] += 1
                sh["spent"] += cost
                sh["coins"] = have - cost
                sh["said"], sh["refresh_wait"] = False, False
                sh["need_top"], sh["top_tries"], sh["bottom"], sh["drag_from"] = True, 0, False, None
                r.log.event("shop_refresh", cost=cost, have=have, n=sh["refreshes"])
                r.wait_leave(s.page)
            return
        sh["blur"] += 1
        if sh["blur"] <= 4:
            r.pause(0.4 * self.patience)
            return
        sh["blur"] = 0
        sh["no_refresh"], sh["refresh_wait"] = True, False
        r.log.shot(s.img, "refresh_mismatch", png=True)
        r.log.say(f"      「更新确认」上读到要花 {cost}、手里有 {have}：读不出来或者超过上限（{self.shop_refresh_max}），这家商店不更新了。")
        r.log.event("shop_refresh_cancel", cost=cost, have=have)
        self._tap_wait(s, BOX["refresh.cancel"], "取消（不更新）")

    def _unsure_event(self, s: Seen, btns: list, what: str) -> None:
        """事件里拿不准选哪个：截图留底；按设置要么交给你，要么先选第 1 项（这个流程最后会撤退，选错也不带走）。"""
        r = self.r
        r.log.shot(s.img, "event_unsure", png=True)
        if self.unknown_event == "first" and btns:
            r.log.say(f"      {what}。先选第 1 项往下走（这一趟最后会撤退，不带走奖励）；截图已经留下，之后补上认法。")
            self._tap_wait(s, choose_button(btns[0][1]), f"选择（{what}，先选第 1 项）", think=True)
            return
        r.hand_over(s, f"{what}，这一步请你来选")
        r.wait_leave(s.page, 15.0)

    def _role_pick(self, s: Seen, btns: list) -> tuple[int, str] | None:
        """公会管理协会：认出左右两边各是什么职能，按规则选一边。返回（第几项, 说明）；认不全返回 None。"""
        # “想要坦克型”和“想要治疗型”五个字里有三个一样，所以每一边都把认得的职能各比一遍，取最像的，而且要明显领先
        gray = cv2.cvtColor(to_norm(s.img), cv2.COLOR_BGR2GRAY)
        sides: dict[int, str] = {}
        for side, x0 in ((0, 380), (1, 750)):
            roi = gray[190:250, x0:x0 + 180]
            scores = sorted(((float(cv2.matchTemplate(roi, self.r.book.tmpl[key], cv2.TM_CCOEFF_NORMED).max()), role)
                             for role, key in ROLE_KEYS.items()), reverse=True)
            if scores[0][0] >= 0.9 and (len(scores) < 2 or scores[0][0] - scores[1][0] >= 0.08):
                sides[side] = scores[0][1]
        if len(sides) != 2:
            return None
        pair = {sides[0], sides[1]}
        for roles, want in ROLE_RULE:
            if pair == roles:
                idx = 0 if sides[0] == want else 1
                return idx + 1, f"{ROLE_NAMES[sides[0]]} / {ROLE_NAMES[sides[1]]} 里选{ROLE_NAMES[want]}"
        return None

    def _slot_pick(self, s: Seen) -> tuple[int, str]:
        """「再较量一次！」选哪边。默认选左边“挑战结束”，不押——用户 2026-11-26 21:30 定的（“第二次不押”）：
        第一步赢的 2000 是当场进口袋的，押的 2000 要从口袋里掏，输了就把刚赢的赔回去。
        设置里 walk.slot_bet = true 才押（19:28 做的那套留着）：只押“消耗 2000 赌 4000”这一步、一个事件格里只押一次，而且手里的金币够；
        别的情况（已经押过、按钮上不是 2000、金币不够或者没读出来）都选左边。"""
        if not self.slot_bet:
            return 1, "到这里收手，不押金币"
        ok, whole, digit = slot_cost_is_2000(self.r.book, s.img)
        coins = self.hud.get("coins")
        if self.slot_bets >= 1:
            return 1, "这个事件里已经押过一次了，到这里收手"
        if not ok:
            return 1, f"右边按钮上不是“消耗 {SLOT_BET_COST}”（整块 {whole:.2f}、首位 {digit:.2f}）——只押 {SLOT_BET_COST} 这一步，收手"
        if coins is None or coins < SLOT_BET_COST:
            return 1, ("金币没读出来" if coins is None else f"金币只有 {coins:,}") + f"，不够押 {SLOT_BET_COST}，收手"
        return 2, f"押 {SLOT_BET_COST} 金币赌 4000（手里有 {coins:,}；只押这一次）"

    def _on_event(self, s: Seen) -> None:
        r = self.r
        key, score, _ = r.book.classify(s.img, EVENT_KEYS)
        btns = r.book.find_all(s.img, "btn_choose")
        if key is None and self.slot_bets >= 1 and len(btns) >= 2:
            # 押完金币以后接着出来的事件，标题没见过：有不花金币的选项（按钮上没有“消耗 N”那一行）就选它——到这里收手，不再押。
            # 截图留底，以后照着它补上正式的认法
            free = [i for i, (_sc, b) in enumerate(btns) if b[1] >= PAID_LABEL_Y]
            if free and len(free) < len(btns):
                pick = free[0] + 1
                r.log.shot(s.img, "event_unsure_after_bet", png=True)
                r.log.event("event", id="after_bet", options=len(btns), pick=pick, score=round(score, 3), free=[i + 1 for i in free])
                r.log.say(f"      押完以后接着出来的事件标题我还没见过：第 {pick} 项不花金币，选它收手（不再押）；截图已经留下。")
                self._tap_wait(s, choose_button(btns[pick - 1][1]), f"选择（押完以后的事件，选不花金币的第 {pick} 项）", think=True)
                return
        if key is None:
            r.log.event("event_unknown", score=round(score, 3), options=len(btns))
            self._unsure_event(s, btns, "这个事件我还没见过")
            return
        ev = key[3:]
        if len(btns) != EVENT_OPTIONS[ev]:
            r.log.event("event", id=ev, options=len(btns), pick=None)
            r.hand_over(s, f"事件「{EVENT_NAMES[ev]}」应该有 {EVENT_OPTIONS[ev]} 个选项，画面上找到 {len(btns)} 个，这一步请你来选")
            r.wait_leave(s.page, 15.0)
            return
        if ev == "guild_office":
            got = self._role_pick(s, btns)
            r.log.event("event", id=ev, options=len(btns), pick=got[0] if got else None)
            if got is None:
                self._unsure_event(s, btns, "事件「公会管理协会」这一组职能我还没见过")
                return
            self._tap_wait(s, choose_button(btns[got[0] - 1][1]), f"事件「公会管理协会」：{got[1]}（第 {got[0]} 项）", think=True)
            return
        if ev == "slot2":
            pick, why = self._slot_pick(s)
            r.log.event("event", id=ev, options=len(btns), pick=pick, why=why, coins=self.hud.get("coins"), bets=self.slot_bets)
            if pick == 2:
                r.log.shot(s.img, "event_bet", png=True)
            if self._tap_wait(s, choose_button(btns[pick - 1][1]), f"事件「再较量一次」：{why}（第 {pick} 项）", think=True) != "changed" and pick == 2:
                self.slot_bets += 1
                self.bet_watch = 8
            return
        pick = self.event_defaults.get(ev, 1)
        r.log.event("event", id=ev, options=len(btns), pick=pick)
        if not 1 <= pick <= len(btns):
            r.hand_over(s, f"事件「{EVENT_NAMES[ev]}」的默认选法是第 {pick} 项，但画面上只有 {len(btns)} 个选项，这一步请你来选")
            r.wait_leave(s.page, 15.0)
            return
        self._tap_wait(s, choose_button(btns[pick - 1][1]), f"事件「{EVENT_NAMES[ev]}」：选第 {pick} 项", think=True)

    # ---- 主循环 ----
    def run(self) -> dict[str, Any]:
        t_start = time.time()
        try:
            return self._loop(t_start)
        except Hold as e:                            # 分数够了、等用户自己打最终首领：这一趟到此为止，游戏停在地图上
            r = self.r
            self.result = {"ok": True, "cleared": False, "at_final": True, "hold": True, "pass_diff": 0.0, "taps": r.taps,
                           "moves": list(self.moves), "battles": self.battles, "why": str(e), "restart": False,
                           "surveys": self.surveys, "seconds": round(time.time() - t_start, 1),
                           "hud": dict(self.hud), "score_if_cleared": self.final_score, "losses": self.losses, "fights": list(self.fights),
                           "shops": list(self.shops), "settled": self.settled, "took_over": self.took_over}
            for line in self.damage_lines():
                r.log.say(line)
            r.log.event("done", **self.result)
            return self.result

    def _loop(self, t_start: float) -> dict[str, Any]:
        r = self.r
        last, same = "", 0
        last_bet_page = ""
        while True:
            s: Seen = r.observe()
            page = s.page
            self._sync_hands()
            same = same + 1 if page == last else 1
            last = page
            if same > SAME_LIMIT.get(page, SAME_DEFAULT):
                r.log.shot(s.img, f"stuck_{page}", png=True)
                raise Halt(f"在「{s.res.name}」上点了 {same - 1} 次画面都没变（按钮可能是灰的，或者这个页面我处理得不对），停下")
            if self.bet_watch > 0:                   # 刚押过金币：后面出什么画面还没见过，各存一张原图（回到地图为止）
                if page == "map":
                    self.bet_watch = 0
                elif page != last_bet_page:
                    self.bet_watch -= 1
                    last_bet_page = page
                    r.log.shot(s.img, f"unsure_after_bet_{page}", png=True)
            else:
                last_bet_page = ""
            if page != "win":
                self.win_wait = 0
            if page != "dlg_join":
                self.join_seen, self.join_tries = None, 0
            if page in ("battle_ready", "relic_pick", "recruit_pick", "event", "scene", "dlg_shop", "dlg_items", "dlg_join"):
                self.arriving = False
            if page in ("win", "win_next") and self.fighting:
                self.fighting = False
                self.battles += 1
                if not self.battle_logged:
                    r.log.event("battle_end", n=self.battles, seconds=None, result="win", battle=self.battle_kind, attempt=self.attempt,
                                team=list(self.last_team), enemy=self.enemy, est=self.last_est)
                    self.chars.record_battle([n for n in self.last_team if "/" not in n], self.battle_kind, None, True)
                    self.chars.save()
                    self.last_secs = self.last_game = None
                    self._remember(True)
                self.battle_logged = False

            if page == "dlg_daychange":
                self._on_daychange(s)
                last, same = "", 0
                continue
            if self.afk is not None and self.afk.recovering:
                self.rejoin = True                   # 连接出错那种是 Runner 里直接处理的，这里补上记号
            if self.rejoin and page not in OUTSIDE:
                self._rejoined(s)

            if page == "lab_home":
                resume = self.rejoin and self.departed and self.seen_confirm and not self.ended
                if self.afk is not None and self.afk.recovering and not resume:
                    self.afk.done(s.res.name)        # 原来那一局还要接着打的，等回到一局里面再算“走回来了”（路上万一弹“要不要继续”还归它管）
                if resume:
                    # 换日 / 掉线以后走回来的，原来那一局还没打完：有进行中的一局时，点「出发」直接回到地图
                    self.rejoin_taps += 1
                    if self.rejoin_taps > 3:
                        raise Halt("回到迷宫首页以后点了 3 次「出发」都没回到原来那一局，停下")
                    if r.tap(s, BOX["lab_home.go"], "出发（接着打刚才那一局）") != "changed":
                        r.wait_leave(page)
                    last, same = "", 0
                    continue
                if self.departed and self.seen_confirm:
                    r.log.shot(s.img, "lab_home_after", png=True)
                    # 撤退回来：通行证应该不比出发前少。打通结算回来：这一局用掉了 1 张（多出来的是游戏按时间发的，不算错）
                    ok, diff, pass_note, pass_after = self._pass_check(s.img)
                    if pass_note:
                        r.log.say(f"      通行证：{pass_note}。")
                    self.result = {"ok": ok, "cleared": self.cleared, "at_final": self.at_final, "pass_diff": round(diff, 2), "taps": r.taps,
                                   "pass_note": pass_note, "pass_before": self.passes, "pass_after": pass_after,
                                   "moves": list(self.moves), "battles": self.battles,
                                   "why": "打完最终首领，已结算" if self.cleared else self.why_retreat, "restart": self.restart,
                                   "surveys": self.surveys, "seconds": round(time.time() - t_start, 1),
                                   "hud": dict(self.hud), "score_if_cleared": self.final_score, "losses": self.losses, "fights": list(self.fights),
                                   "shops": list(self.shops), "settled": self.settled, "took_over": self.took_over}
                    for line in self.damage_lines():
                        r.log.say(line)
                    r.log.event("done", **self.result)
                    return self.result
                self.pass_before = r.book.crop(s.img, "pass_count")
                r.log.shot(s.img, "lab_home_before", png=True)
                self.passes = self._read_passes(s.img)
                if self.passes is not None:
                    r.log.say(f"      通行证：{self.passes} 张。")
                    r.log.event("passes", n=self.passes, keep=self.keep_passes, spending=self.boss == "all")
                    block = None
                    if self.passes <= 0:
                        block = "通行证是 0 张，出发不了，停下"
                    elif self.boss == "all" and self.passes <= self.keep_passes:
                        block = f"通行证只剩 {self.passes} 张，设置里说要留 {self.keep_passes} 张（farm.keep_passes），这一局会用掉 1 张，所以不出发，停下"
                    if block and not self.resume:
                        raise Halt(block)
                    if block:                        # 勾了「接着打进行中的一局」：那一局的通行证早就扣过了，这里的数字不作数。先点「出发」看是不是直接回到那一局
                        self.pass_block = block
                        r.log.say("      通行证不够再开一局；先点「出发」看看是不是有进行中的一局（有就接着打，没有就停下）。")
                if r.tap(s, BOX["lab_home.go"], "出发") != "changed":
                    self.departed = True
                    r.wait_leave(page)
            elif page in ("home", "adventure") and (not self.departed or self.rejoin):
                if same >= 2 and self.afk is not None and self.afk.nudge(s):
                    r.pause(0.8 * self.patience + self.beat)      # 点了没反应：上面多半盖着弹窗，先把它弄掉
                    last, same = "", 0
                elif page == "home":
                    self._tap_wait(s, BOX["home.adventure"], "冒险")
                else:
                    self._tap_wait(s, BOX["adventure.lab"], "黎明界迷宫")
            elif page == "guild_select" and self.rejoin and self.seen_pick3:
                raise Relap("回到迷宫以后点「出发」到了公会选择页，说明原来那一局已经不在了")
            elif page == "guild_select" and self.departed:
                if self.pass_block:                  # 没有进行中的一局，通行证又不够开新的
                    raise Halt("没有进行中的一局可以接着打；" + self.pass_block)
                if self.resume and not self.took_over and not self.resume_said:
                    self.resume_said = True
                    r.log.say("      点了「出发」到了公会选择页：没有进行中的一局，照常开新的一局。")
                self._on_guild_select(s)
            elif page == "dlg_guild_confirm" and self.departed:
                if r.tap(s, BOX["guild_confirm.go"], "出发（会先扣 1 张通行证，撤退时退回）") != "changed":
                    self.seen_confirm = True
                    r.wait_leave(page)
            elif page == "dlg_depart_reward" and self.seen_confirm:
                self._tap_wait(s, BOX["depart_reward.close"], "关闭")
            elif page == "dlg_relic_effect" and self.seen_confirm:
                self._on_relic_effect(s)
            elif page == "dlg_pick3" and self.seen_confirm:
                self._on_pick3(s)
            elif page == "join_splash" and self.seen_confirm:
                r.tap(s, BOX["splash.any"], "点一下翻过登场画面")
                r.pause(self.beat)
            elif page in ("dlg_join", "dlg_items") and self.seen_confirm:
                if page == "dlg_join" and not self._learn_join(s):
                    continue
                if page == "dlg_items" and self.cleared and not self.loot_done:
                    self._read_loot(s)               # 打通结算后的那张清单：先读完再关
                    last, same = "", 0
                    continue
                self._tap_wait(s, BOX["dialog.outside"], f"点对话框外面关掉「{s.res.name}」")
            elif page == "map":
                self._on_map(s)
            elif page == "dlg_move" and self.seen_pick3:
                self._on_move(s)
            elif page == "battle_ready" and self.seen_pick3:
                self.team_changed = self.equip_done = self.auto_done = False
                self.team_retry, self.team_expect = 0, None
                self.tb = None
                self.team_empty = 0
                self.sort_tries = self.sort_taps = 0
                if self.want_retreat:                # 打输了决定撤退：从这里回地图
                    self._tap_wait(s, BOX["ready.map"], "查看地图（不打了，回地图撤退）")
                    continue
                self.weak = CD.weak_attr(r.book, s.img)
                if self.weak:
                    r.log.say(f"      敌人的弱点属性：{CD.ATTR_CN[self.weak]}")
                    r.log.event("weak", attr=self.weak)
                if not self._read_enemy(s):          # 名字还没显示全：等一下再看
                    continue
                if self._no_mech_for_sure():         # 非要某种机制不可的敌人、名单里确定一个带的都没有：不打，回地图撤退重开
                    self._tap_wait(s, BOX["ready.map"], "查看地图（没有对应机制的角色，不打了，回地图撤退）")
                    continue
                self._tap_wait(s, BOX["ready.fight"], "挑战")
            elif page == "defeat" and self.seen_pick3:
                self._on_defeat(s)
            elif page == "dlg_team" and self.seen_pick3:
                if not self._fix_sort(s):            # 排序不是「等级」的话先换回来（认卡片靠的是卡片上的“等级”两个字）
                    self._on_team(s)
            elif page == "dlg_sort" and self.seen_pick3:
                self._on_sort(s)
            elif page == "dlg_equip" and self.seen_pick3:
                if not self.auto_done:
                    self._tap_wait(s, BOX["equip.auto"], "自动装备")
                elif button_lit(s.img, BOX["equip.ok"]):
                    if r.tap(s, BOX["equip.ok"], "装备确定") != "changed":
                        self.equip_done = True
                        r.wait_leave(page)
                else:
                    # 自动装备的结果和现在穿的一样时，「装备确定」是灰的、点不动，只能点「取消」回去
                    r.log.event("equip_unchanged")
                    if r.tap(s, BOX["equip.cancel"], "取消（装备没有变化，「装备确定」是灰的）") != "changed":
                        self.equip_done = True
                        r.wait_leave(page)
            elif page == "dlg_autoequip" and self.seen_pick3:
                if r.tap(s, BOX["autoequip.ok"], "确认（自动装备）") != "changed":
                    self.auto_done = True
                    r.wait_leave(page)
            elif page == "battle" and self.seen_pick3:
                self._watch_battle()
            elif page == "win_next" and self.seen_pick3:
                if not self._damage_report(s):
                    self._tap_wait(s, BOX["win.next"], "下一步")
            elif page == "win" and self.seen_pick3:
                self.win_wait += 1                   # 「下一步」要过一会儿才出来；等了两轮还没有就点它该在的位置
                if self.battle_kind == "boss" and self._damage_report(s, "boss"):
                    pass                             # 首领战的 WIN! 上「伤害报告」在「第 N 战 胜利」那一行：看过了，回主循环重新看画面
                elif self.win_wait >= 3:
                    self._tap_wait(s, BOX["win.next"], "下一步（按钮还没显示，点它的位置）")
                else:
                    r.wait_leave(page, 4.0 * self.patience)
            elif page == "recruit_pick" and self.seen_pick3:
                self._on_choice3(s, "角色加入奖励")
            elif page == "relic_pick" and self.seen_pick3:
                self._on_choice3(s, "获得道具的机会")
            elif page == "event" and self.seen_pick3:
                self._on_event(s)
            elif page == "scene" and self.seen_pick3:
                self._tap_wait(s, BOX["scene.skip"], "跳过演出")
            elif page == "result" and self.seen_pick3:
                self._on_result(s)
            elif page == "dlg_chest_result" and self.seen_pick3:
                self._on_chest(s)
            elif page == "dlg_shop" and self.seen_pick3:
                self._on_shop(s)
            elif page == "dlg_buy" and self.seen_pick3:
                self._on_buy(s)
            elif page == "dlg_bought" and self.seen_pick3:
                self._on_bought(s)
            elif page == "dlg_refresh" and self.seen_pick3:
                self._on_refresh(s)
            elif page == "dlg_no_reward" and self.seen_pick3:
                # 标题「确认」、正文只有一句“无法获得报酬。”、下面一个「确认」的提示框（事件里选了“挑战结束”以后弹的）。
                # 两样都对上页面库才会报这个名字；别的叫「确认」的框照旧算不认识的对话框，不走这里
                self._tap_wait(s, BOX["notice.ok"], "确认（提示“无法获得报酬”，只有这一个按钮）")
            elif page == "dlg_shop_exit" and self.seen_pick3:
                if self._tap_wait(s, BOX["shop_exit.ok"], "确认（退出商店）") != "changed":
                    self.shop = None
            elif page == "dlg_monster" and self.seen_pick3:
                self._on_monster(s)
            elif page == "dlg_end" and self.seen_pick3 and all(k in r.book.marks and r.book.has_mark(s.img, k) for k in ("end3_refund", "end3_retreat")):
                # 首领战打输后点「结束」出来的那种：取消 / 撤退（无报酬）/ 返回（有报酬）。只点「撤退（无报酬）」——通行证退回；「返回（有报酬）」会结算，不碰
                if r.tap(s, BOX["end3.retreat"], "撤退（无报酬）——不带报酬、退回通行证") != "changed":
                    self.ended = True
                r.wait_leave(page)
            elif page == "dlg_end" and self.seen_pick3:
                if not r.book.has_mark(s.img, "end_refund"):
                    r.log.shot(s.img, "end_without_refund", png=True)
                    raise Halt("「结束确认」里没看到“将返还迷宫通行证”这行字，不点确认，停下")
                if r.tap(s, BOX["end.ok"], "确认（撤退，退回通行证）") != "changed":
                    self.ended = True
                r.wait_leave(page)
            elif page == "battle_ready" and self.resume and not self.departed:
                # 勾了「接着打进行中的一局」，游戏停在这一局的战斗准备上：先回地图，从地图接手（这一格是什么战斗，回头走上去的时候再认）
                self._tap_wait(s, BOX["ready.map"], "查看地图（接着打进行中的一局：先回地图）")
            elif self.resume and not self.departed and page not in OUTSIDE:
                r.log.shot(s.img, f"takeover_{page}", png=True)
                raise Halt(f"要接着打进行中的一局，得从这一局的地图接手；现在游戏停在「{s.res.name}」上，这一步前面发生了什么我没看到，不敢接。"
                           "请你把这一步点完、回到地图（或者退回迷宫首页、主页），再开始")
            else:
                r.log.shot(s.img, f"unexpected_{page}", png=True)
                raise Halt(f"这一步没想到会出现「{s.res.name}」，停下")
