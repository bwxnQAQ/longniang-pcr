"""设置：config/settings.json。文件不存在或缺项时用默认值。"""
from __future__ import annotations

import json
from typing import Any

from . import paths

DEFAULTS: dict[str, Any] = {
    "stop_key": "F12",                 # 紧急停止键：F1～F12、PAUSE、END、HOME
    "keep_awake": True,                # 运行期间不让电脑自己睡眠（挂机用）
    "notify": True,                    # 跑完了、停下了，在 Windows 右下角弹一条通知、响一声
    "update_check": True,              # 打开界面时自动去 GitHub 看一眼有没有新版本（只读版本标签，不下载；有新的只是提醒）。false = 不查
    "detail_output": False,            # 窗口里（界面的“详细输出”）写多细：False = 只写干了什么；True = 连点在哪个坐标、按了多少毫秒都写（log.txt 里永远是全的）
    # 自动跑的时候你自己动手点了模拟器：工具先停手，等你停够 quiet 秒再重新看画面接着来。on = 要不要这样；
    # match = 模拟器窗口的程序名或标题里带的字（MuMu 不用改；换了模拟器再改）。只看“模拟器窗口在最前面、鼠标在它里面、鼠标键按着”这三件事
    "hands": {"on": True, "quiet": 12, "match": ["mumu", "nemu"]},
    "logs": {"keep_shots": 0},         # 只留最近这么多次运行的截图（更早的只删图，文字记录留着）；0 = 不删。一局的截图有两三百兆
    "drill": {"guild_mark": "guild_cile", "guild_name": "慈乐之音"},
    # unknown_timeout = 认不出的画面先等多少秒；还认不出就请你在模拟器里手动点过去（工具不碰），认出下一个画面接着跑；
    # unknown_wait = 请你来点以后最多再等多少秒（默认 1800 = 半小时），到了还认不出才停。写 0 = 不等，和以前一样到 unknown_timeout 就停
    "limits": {"max_taps": 60, "max_seconds": 600, "unknown_timeout": 20, "wait_timeout": 90, "unknown_wait": 1800},
    # 走几格再撤退：steps = 默认走几格；
    # pick = 开局三人怎么选："auto" 按规则挑（当成一支 3 个人的快攻队：输出、破防、强化、增益优先，坦克和治疗排最后；物理魔法不混）；
    #        也可以直接写三个名字，比如 ["望（解放者）", "纺希（吉奥·矶汉拿）", "千歌（夏日）"]（要先读过角色）；
    #        或者写死成名单里的第几格，比如 [2, 7, 12]（从 1 数，一行 8 格）；
    # team = 战斗前怎么编队："role" 认每张卡的职能和属性按规则挑 5 个人（普通战打快，极难 / 首领按 data/counters.json 的对策）；
    #        "order" 是老办法，按名单顺序把空位填满；
    # defeat_retries = 一场战斗打输以后最多换队重打几次（0～4），再输就撤退重开；
    # battle_timeout = 一场战斗最多等多少秒；survey = 进区域先看全图、按极难排路线；
    # max_restarts = 极难走不到时最多重开几次；
    # unknown_event = 没见过的事件怎么办："first" 先选第 1 项往下走（这个流程最后会撤退，不带走奖励），"ask" 停下交给你
    # boss = "mid" 打区域 3 的首领，最终首领前撤退；"stop" 见到首领就撤退（「打通一局」固定按 "mid"）；
    # boss_teams_mid / boss_teams_final = 区域 3 首领、最终首领各编几队（1～3）；区域 3 首领凹分要一队过，打输了重打也只用一队
    # scout_bosses = 开局先点进度条上的两个 BOSS 图标，看这一局区域 3 首领和最终首领是谁（招募时对应着拿人）；
    # boss_avoid = 遇到就直接撤退重开的首领名字（对策表 data/counters.json 里的名字，比如 ["奇美拉"]），空着就是哪个都打
    # route_values = 极难数相同的路线之间怎么挑：每种格子大约值多少分（难度 5 最终分数），加起来高的那条赢，再一样取靠上的。
    #   normal 普通战（战斗 200 + 1 名角色 200 + 金币约 1,190 折 240）、relic 遗物格（1 个遗物 400）、event 事件（按默认选法算的期望，约 500）、mark 印记格（3 名角色 600）、
    #   shop 商店："auto" = 看手里有多少金币现算（金币多才值得绕过去；见 plan.shop_value），也可以写死成一个数。想让它多走某种格子就把那一项调高
    # shop = 路过商店怎么办：buy = 买不买（false 就和以前一样直接关掉）；
    #   max_rate = 平时只买“每 1 分最终分数不超过这么多金币”的东西（★1 遗物 1,350 金币 +400 分 = 3.4，随机印记 900 金币 +200 分 = 4.5，
    #   ★2 遗物 2,100 金币 = 5.25）；最后一个区域的商店会把剩下的金币也花掉，不受这个数限制；
    #   refresh_max = 「更新」一次最多肯花多少金币（游戏里第一次 300、第二次 600，一家店只能更新两次）
    # damage_report = 每场打赢以后要不要点开「伤害报告」记每个人的伤害、给输出角色调比重（true = 看；false = 不看，也不再调）
    # guild = 打哪个公会：写名字（咲恋救济院 / 王宫骑士团 / 美食殿堂 / 拉比林斯 / 破晓之星 / 慈乐之音 / 恶魔伪王国军 / 伊丽莎白牧场 / 墨丘利财团 / 暮光流星群），
    #         或者 "刷分" = 让工具挑（默认咲恋救济院，攒够几局成绩以后挑平均估分最高的）；空着 = "刷分"（2026-11-25 起；按饰品连续刷空着是“自动”）
    # tier = 凹度档位：1 最高凹分（极难全打；极难走不到、首领不合意、前两个区域的事件给得少都重开）、2 极难全打（只有极难走不到才重开；以前一直用的）、
    #        3 稳着打（极难能走到几个打几个、不重开；区域 3 首领输了可以多编一队）、4 保通关（能不走极难就不走；极难 / 首领第一次就带坦克治疗）；
    # reroll = 第一档凹什么：boss_want 只留这些首领（空 = 不挑）、boss_avoid 遇到就重开的首领、event_min 前 areas 个区域的事件折成分数低于它就重开（0 = 不凹事件）
    # rest_between = 连续打几局时，局与局之间歇多少秒（在这两个数之间随机；[0, 0] = 不歇）；idle = 自动跑的时候偶尔发呆 5～30 秒（更像人，一局多花几分钟；默认不开）
    # start_at / stop_at = 定时："23:30" 这样的钟点。start_at 等到这个点再开始；stop_at 过了这个点就不再开新的一局（正在打的打完）。空着 = 不定时
    # relaunch = 游戏闪退（不在最前面了）或者卡死（很久都没停在能操作的页面上）时，要不要替你重新启动游戏再走回迷宫（一次运行最多 2 次）；
    # recover = 挂机时游戏换日（每天 5 点）、连接出错、退回标题画面，要不要自己走回迷宫接着打（true = 走回来；false = 停下等你）；
    # laps = 黎明界迷宫打几局（1～50；勾了「使用门票」才用得上，成功打完才算一局）；最外面的 keep_awake = 运行期间不让电脑自己睡眠（屏幕照样可以关，程序一退出就恢复）
    # remember_wins = 按敌人记真机上打赢 / 打输过的队（true = 记，下次凑得齐就直接上赢过的那一队、不再上只输没赢过的队；false = 不记也不用）
    # estimate = 极难和区域 3 首领要不要按“战斗估算”挑队（true = 不按规则选人，在整个名单里换人推演、上估算最好的一队；false = 只按规则排）
    "walk": {"steps": 3, "pick": "auto", "team": "role", "defeat_retries": 2, "battle_timeout": 300, "survey": True, "max_restarts": 3, "unknown_event": "first",
             "estimate": True, "remember_wins": True,
             "settle_max_tries": 30,                         # 勾了「使用门票」又定了分数线：最多允许这么多局没到分（都是撤退，不用门票），再多就停
             "damage_report": False, "auto_equip": False,    # 看伤害报告、编完队点「自动装备」：界面上各有一个勾（这里是默认值；2026-11-25 起开关默认都关）
             "recover": False, "relaunch": True, "laps": 1, "rest_between": [20, 60], "idle": False, "start_at": "", "stop_at": "",
             "guild": "", "tier": 2, "reroll": {"boss_want": [], "boss_avoid": [], "event_min": 400, "areas": 2, "auto_avoid": True, "no_shop_areas": [2]},
             "boss": "mid", "boss_teams_mid": 1, "boss_teams_final": 3, "scout_bosses": True, "boss_avoid": [],
             "route_values": {"normal": 640, "relic": 400, "event": 500, "mark": 600, "shop": "auto"},
             "shop": {"buy": True, "max_rate": 5.0, "refresh_max": 600}},
    # 按饰品数量连续刷（菜单 18）：targets = 每种要几个，按“名字里包含的字”算（{"戒指": 2, "火之项链": 1}）；max_runs = 一次最多打通几局；
    # guilds = 可以打的公会名字（和游戏里写的一样；空着 = 只打 drill.guild_name 那个），工具看账本里哪个公会出还差的那种出得多就打哪个；
    # accessory_words = 除了 戒指 / 项链 / 宝珠 / 耳环 / 手镯 以外，名字里还带哪些字的也算饰品。会不会真的用通行证不在这里设：每次在界面上勾
    # keep_passes = 通行证不多于这么多张就不再出发（留着手打用）；迷宫首页上的张数要读得出来才管用
    "farm": {"targets": {}, "max_runs": 10, "guilds": [], "accessory_words": [], "keep_passes": 0},
    "human": {},                       # 想改拟人化参数就写在这里，名字见 longniang_pcr/human.py 的 HumanParams
}


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


# 刚下载时 config/settings.json 里写的就是这些（「重置到初始状态」照着它写回去；自测盯着它和那个文件一字不差）
DEFAULT_FILE = """{
  "stop_key": "F12",
  "drill": {"guild_mark": "guild_cile", "guild_name": "慈乐之音"},
  "walk": {"steps": 3, "pick": "auto", "team": "role", "defeat_retries": 2, "battle_timeout": 300, "survey": true, "max_restarts": 3, "unknown_event": "first",
           "boss": "mid", "boss_teams_mid": 1, "boss_teams_final": 3, "scout_bosses": true, "boss_avoid": [],
           "route_values": {"normal": 640, "relic": 400, "event": 500, "mark": 600, "shop": "auto"},
           "shop": {"buy": true, "max_rate": 5.0, "refresh_max": 600}},
  "limits": {"max_taps": 60, "max_seconds": 600, "unknown_timeout": 20, "wait_timeout": 90},
  "human": {}
}
"""


def load() -> dict[str, Any]:
    f = paths.PROJECT_ROOT / "config" / "settings.json"
    if not f.exists():
        return dict(DEFAULTS)
    try:
        return _merge(DEFAULTS, json.loads(f.read_text(encoding="utf-8-sig")))
    except Exception as e:  # noqa: BLE001
        print(f"  ! config/settings.json 读不了（{type(e).__name__}: {e}），这次先用默认设置")
        return dict(DEFAULTS)
