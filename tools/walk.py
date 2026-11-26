"""走几格再撤退：阶段 2 第一步的验收。

流程：迷宫首页 →「出发」→ 选公会 → 选开局三人 → 往前走 N 格（战斗全程 AUTO，选角色 / 遗物、事件、商店都会经过）
→「撤退（无报酬）」→「确认」→ 回到迷宫首页。出发时扣的 1 张通行证在撤退时原样退回。
每进一个区域先拖动地图看完整层、按极难排路线；有极难走不到就撤退重开（次数有上限）。
区域 3 的首领会打（打完照样能撤退），最终首领不打。走满 N 格就撤退；N 填 0 = 只看全图、排路线，一格不走。
区域 1～3 一共 17 格，第 17 格是区域 3 的首领。加 --full = 不限格数，一直走到最终首领跟前（30 格）再撤退。
开始前请把游戏停在「迷宫首页」（有「出发」按钮的那一页），主页或冒险页也可以。
游戏里有一局打到一半时：默认停下、不动它；加 --resume（界面上勾「接着打进行中的一局」）就从那一局的地图接手往下打。
"""
from __future__ import annotations

import argparse
import os
import random
import re
import sys
import time

import _common  # noqa: F401
from longniang_pcr import advisor as AD
from longniang_pcr import afk as AFK
from longniang_pcr import tiers as TR
from longniang_pcr import wins as WN
from longniang_pcr import accessories as AC
from longniang_pcr import guilds as GD
from longniang_pcr import hands as HD
from longniang_pcr import notify as NT
from longniang_pcr import loot as LT
from longniang_pcr import damage as DM
from longniang_pcr import chars as CH
from longniang_pcr import config, console, ocr, paths, wiki
from longniang_pcr.device.device import Device, DeviceError
from longniang_pcr.flows.walk import MOVE_NAMES, Relap, Walk, load_event_defaults, shops_summary
from longniang_pcr.human import Human, HumanParams
from longniang_pcr import runlog as RL
from longniang_pcr.runlog import RunLog
from longniang_pcr.runner import Halt, Limits, Runner
from longniang_pcr.score import shortfall
from longniang_pcr.stop import HotkeyWatcher, StopFlag, Stopped
from longniang_pcr.vision import enemy as EN
from longniang_pcr.vision.pages import PageBook


def boss_mode(full: bool, farm: bool, spend: bool, cfg_boss: str) -> str:
    """这一趟首领打到哪。最终首领打完游戏会自动结算、用掉 1 张通行证，所以只有「按饰品数量连续刷」并且你明确允许用通行证（--spend）
    时才打（返回 "all"）；别的情况：打通一局固定只打区域 3 的首领（"mid"），走几格按设置（设置里写了 all 也只当 mid）。"""
    if farm and spend:
        return "all"
    if full or farm:
        return "mid"
    return "mid" if cfg_boss not in ("mid", "stop") else cfg_boss


def seconds_until(hhmm: str, now: float | None = None) -> float | None:
    """到下一个 HH:MM 还有多少秒（今天这个点已经过了就是明天的）。写得不对返回 None。"""
    m = re.fullmatch(r"\s*(\d{1,2})[:：](\d{2})\s*", str(hhmm or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    t = time.localtime(now if now is not None else time.time())
    cur = t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec
    want = int(m.group(1)) * 3600 + int(m.group(2)) * 60
    return float(want - cur if want > cur else want - cur + 86400)


KIND_SHORT = {"normal": "普通战", "extreme": "极难", "boss": "首领"}
LOSS_SHORT = {"timeout": "时间到了没打完", "front": "从前面一个个倒的", "collapse": "全队一起崩的", "wiped": "队伍倒了"}


def summary_lines(title: str, started: float, ending: str, rows: list[dict], recoveries: list[str], yields: list[float] | None = None) -> list[str]:
    """一次运行的小结（写进记录文件夹的 summary.txt，第二天不用翻几十万字的流水账）：每一趟一行。"""
    took = time.time() - started
    out = [f"{title}　{time.strftime('%Y-%m-%d %H:%M', time.localtime(started))} 开始，用时 {int(took // 3600)} 小时 {int(took % 3600 // 60)} 分",
           f"怎么结束的：{ending or '你点了停止'}"]
    done = [r for r in rows if r.get("score")]
    if done:
        out.append(f"走完的 {len(done)} 局：平均估分 {sum(r['score'] for r in done) / len(done):,.0f}，最高 {max(r['score'] for r in done):,}")
    for r in rows:
        out.append(f"  第 {r['n']} 趟　{r['guild']}　{r['result']}"
                   + (f"　估分 {r['score']:,}" if r.get("score") else "")
                   + f"　{r['minutes']:.0f} 分钟　{r['moves']} 格、{r['battles']} 场战斗" + (f"（输 {r['losses']} 场）" if r.get("losses") else ""))
        fights = r.get("fights") or []
        name = lambda f: f"区域 {f.get('area')} {KIND_SHORT.get(f.get('kind'), '战斗')}" + (f"·{f['enemy']}" if f.get("enemy") else "")      # noqa: E731
        lost = [f for f in fights if not f.get("win")]
        if lost:
            out.append("      输的：" + "；".join(name(f) + (f"（{LOSS_SHORT.get(f.get('how'), '')}）" if LOSS_SHORT.get(f.get("how")) else "") for f in lost))
        slow = sorted((f for f in fights if f.get("win") and isinstance(f.get("game"), (int, float))), key=lambda f: -f["game"])[:3]
        if slow and slow[0]["game"] >= 30:
            out.append("      赢得最慢的：" + "；".join(f"{name(f)} 游戏里 {f['game']} 秒" for f in slow if f["game"] >= 30))
    if recoveries:
        out.append(f"从游戏外面走回迷宫 {len(recoveries)} 次：" + "；".join(recoveries))
    if yields:
        out.append(f"你中途自己动手点过模拟器，我停手让了 {len(yields)} 次，一共 {sum(yields):.0f} 秒")
    return out


def parse_targets(text: str | None) -> dict[str, int]:
    """界面上填的目标：“火轮赞颂=1, 暗饰=2”（逗号、顿号、空格、换行都能分开；等号也可以写成冒号或 ×）。每一个能写到多细见 accessories.parse_filter。"""
    out: dict[str, int] = {}
    for part in re.split(r"[,，、;；\s]+", text or ""):
        m = re.fullmatch(r"(.+?)[=＝:：×xX*]\s*(\d+)", part.strip())
        if m and int(m.group(2)) > 0:
            out[m.group(1).strip()] = int(m.group(2))
    return out


def main() -> int:
    console.setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto", action="store_true", help="不逐步确认，工具按拟人节奏自己走完")
    ap.add_argument("--steps", type=int, default=-1, help="走几格（不写就问你；默认 3；0 = 只看全图不走）")
    ap.add_argument("--no-survey", action="store_true", help="不看全图，用老办法选路（有极难走极难，否则最上面）")
    ap.add_argument("--full", action="store_true", help="黎明界迷宫：五个区域走到最终首领跟前。不带 --spend 到了就停下、任务结束；带了才打最终首领并结算")
    ap.add_argument("--tier", type=int, default=0, help="凹度档位 1～4（不写就用设置里的 walk.tier，默认 2）")
    ap.add_argument("--boss-want", default="", help="第一档：只留这些首领（名字用顿号或逗号分开；区域 3 首领和最终首领都写进去）")
    ap.add_argument("--boss-avoid", default="", help="第一档：遇到就重开的首领")
    ap.add_argument("--no-shop-reroll", action="store_true", help="第一档：第二层（区域 2）绕不开商店时不重开（默认会重开）")
    ap.add_argument("--start-at", default="", help="定时：等到这个钟点（HH:MM，按电脑的时间）再开始；不写 = 现在就开始")
    ap.add_argument("--stop-at", default="", help="定时：过了这个钟点（HH:MM）就不再开新的一局（正在打的那一局会打完）")
    ap.add_argument("--guild", default="", help="打哪个公会：写名字（十个公会都行），或者写 刷分 = 让工具挑平均估分最高的（默认咲恋救济院）；"
                                                "--farm 时还可以写 自动 = 十个公会里按账本挑。不写就用设置里的 walk.guild，再没有就是 drill.guild_name")
    ap.add_argument("--farm", action="store_true", help="按饰品数量连续刷：打通（打掉最终首领、结算）→ 读战利品 → 没刷够接着打")
    ap.add_argument("--spend", action="store_true", help="使用门票（通行证）。--farm：不加就只说明、不动手；--full：加了才打最终首领并结算，"
                                                         "不加就走到最终首领跟前停下、任务结束（只打这一局）")
    ap.add_argument("--fresh", action="store_true", help="--farm：这一轮从头数（不接着上一轮没刷够的数）")
    ap.add_argument("--targets", default="", help="--farm 的目标，比如 火轮赞颂=1,暗饰=2,轮=3（不写就用设置里的 farm.targets）；能写到多细见 README")
    ap.add_argument("--max-runs", type=int, default=0, help="--farm 最多打通几局（不写就用设置里的 farm.max_runs，默认 10）")
    ap.add_argument("--report", action="store_true", help="这一次每场打完看伤害报告（不管设置里怎么写；设置里默认是不看）")
    ap.add_argument("--no-report", action="store_true", help="这一次不看伤害报告（不管设置里怎么写）")
    ap.add_argument("--recover", action="store_true", help="这一次遇到换日 / 掉线自己走回迷宫（设置里默认是停下）")
    ap.add_argument("--no-recover", action="store_true", help="这一次遇到换日 / 掉线就停下，不自己走回迷宫")
    ap.add_argument("--laps", type=int, default=0, help="打几局：成功打完（打掉最终首领、结算）才算一局，要加 --spend；不加 --spend 只打一局（不写就用设置里的 walk.laps，默认 1）")
    ap.add_argument("--resume", action="store_true", help="接着打进行中的一局：游戏里有一局打到一半时（点「出发」会直接回到地图），从地图接手往下打；"
                                                          "不加就照旧停下、不动那一局。没有进行中的一局时照常开新的。只管这一次，不会记住")
    ap.add_argument("--equip", action="store_true", help="这一次编完队点「特别装备」→「自动装备」（设置里默认是不点）")
    ap.add_argument("--no-equip", action="store_true", help="这一次不点「特别装备」→「自动装备」（你自己配好的装备不会被换掉）")
    ap.add_argument("--settle", type=int, default=0, help="黎明界迷宫（--full）勾了使用门票（--spend）时：走到最终首领跟前估分达到这个数才打它、结算；"
                                                         "不到就撤退重打（门票不用、不算一局）。0 = 不看分数")
    args = ap.parse_args()
    args.auto = True                                 # 单步模式（每一下等你回车）2026-11-24 深夜删了：一律自己走。--auto 还认，只是不用写了
    if args.farm:
        args.full = True
    cfg = config.load()
    wk = cfg.get("walk", {})
    fm = cfg.get("farm") if isinstance(cfg.get("farm"), dict) else {}
    # V1.0（2026-11-25 用户定的）：黎明界迷宫（--full，不是连续刷）走到最终首领跟前不再自动撤退——
    #   没加 --spend（界面上没勾「使用门票」）：停在最终首领跟前，任务结束；只打这一局，不看分数。
    #   加了 --spend：成功打完（打掉最终首领、结算，用 1 张门票）才算一局，打满 --laps 局；--settle 定了分数线的话，没到分的局撤退重打、不算。
    final_stop = bool(args.full and not args.farm)
    settle_spend = bool(final_stop and args.spend)   # 只认这一次命令行上的 --spend（界面上那个勾，每次都要重新勾），不从设置里读
    settle = max(0, int(args.settle or 0)) if settle_spend else 0
    auto_equip = (bool(wk.get("auto_equip", False)) or args.equip) and not args.no_equip
    settle_laps = max(1, min(50, int(args.laps or wk.get("laps", 1) or 1))) if settle_spend else 1
    miss_cap = max(1, int(wk.get("settle_max_tries", 30) or 30))      # 勾了门票、定了分数线：最多允许这么多局没到分（都是撤退，不用门票），再多就停
    key = str(cfg.get("stop_key", "F12"))
    tier = TR.get(args.tier or wk.get("tier", TR.DEFAULT))
    reroll = TR.reroll_of(wk.get("reroll") if isinstance(wk.get("reroll"), dict) else None)
    names_of = lambda text: [x for x in re.split(r"[,，、;；\s]+", text or "") if x]      # noqa: E731
    if args.boss_want.strip():
        reroll["boss_want"] = names_of(args.boss_want)
    if args.boss_avoid.strip():
        reroll["boss_avoid"] = names_of(args.boss_avoid)
    if args.no_shop_reroll:
        reroll["no_shop_areas"] = []
    max_restarts = max(0, int(wk.get("max_restarts", 3)))
    if tier.max_restarts is not None:                # 第一档要凹首领、凹事件，重开次数放宽
        max_restarts = max(max_restarts, tier.max_restarts)
    log = RunLog("farm" if args.farm else "clear" if args.full else "walk")
    log.brief = not bool(cfg.get("detail_output", False))      # 窗口里只写干了什么；点击坐标这类细节只进 log.txt（设置里 "detail_output": true 可以改回来）
    loot = None
    if args.farm:
        # 按饰品数量连续刷（2026-11-24）：这一项每一局都会打最终首领、用门票（通行证），所以先把话说清楚，没明确允许（--spend）就到此为止
        loot = LT.LootBook(paths.PROJECT_ROOT / "data" / "learned" / "loot.json", fm.get("accessory_words"))
        targets = parse_targets(args.targets) or {str(k): int(v) for k, v in (fm.get("targets") or {}).items()}
        log.say("")
        log.say("  按饰品数量连续刷")
        log.say("  每一局：五个区域走完、打掉最终首领、结算 → 开宝箱 → 把「获得道具」清单读下来记账 → 目标没刷够就再来一局。")
        log.say("  每打通一局用掉 1 张门票（最终首领打输了走「撤退（无报酬）」，那一局不扣，也没有战利品）。饰品在红宝箱里，难度 5 平均一局不到一件。")
        if not targets:
            log.say("  还没有目标。在界面上的「按分类选」里挑，或者直接写，比如“火轮赞颂=1, 暗饰=2, 轮=3”；也可以写进 config/settings.json 的 farm.targets。")
            log.say("  饰品一共 50 件：十个公会各出一个系列，每个系列火、水、风、光、暗五件——")
            for s_ in AC.SERIES:
                log.say(f"    {s_.guild}：{s_.name_of('○')}（部位「{s_.slot}」，系列「{s_.suffix}」）")
            log.say("  一个目标可以写到：具体一件（火轮赞颂）、一个系列（赞颂，或者直接写公会名）、一个部位（轮）、一种属性（火）、属性加部位（火轮）、随便哪件（饰品）。")
            for line in loot.lines():
                log.say(line)
            log.close()
            return 0
        odd = [k for k in targets if AC.parse_filter(k) is None]
        loot.begin(targets, fresh=args.fresh)
        loot.save()
        log.say("  目标：")
        for k, v in loot.session["targets"].items():
            log.say(f"    {k} × {v}　= {LT.target_text(k)}")
        if odd:
            log.say(f"  ! {'、'.join(odd)} 不是我认识的饰品写法，会按“名字里包含这几个字的东西”来数（刷材料时这样写没问题；想刷饰品请照上面的写法）。")
        if len(loot.session["targets"]) > 1:
            log.say("  （几个目标各数各的：一件“黎明火轮α赞颂”既算进“火轮赞颂”，也算进“轮”和“火”。）")
        for line in loot.lines():
            log.say(line)
        if not args.spend:
            log.say("  这一次没有勾「使用门票」，所以什么都没做、游戏没动。想开始：在界面上勾上它再点一次。")
            log.close()
            return 0
    log.say("")
    mode = "（自动）" if args.auto else "（单步：每一下都等你回车，中途输入 a 可以改成自动）"
    if args.farm:
        log.say("  （下面每一局的走法和「打通一局」一样，只是到了最终首领不撤退，打掉它。）" + mode)
    elif args.full:
        log.say("  黎明界迷宫" + mode)
        if settle_spend:
            log.say(f"  五个区域一路走到最终首领跟前（一共 30 格），然后打最终首领、结算——每成功打完一局用 1 张门票，一共打 {settle_laps} 局（你这一次勾了「使用门票」）。")
            if settle:
                log.say(f"  分数线 {settle:,}：走到最终首领跟前先算“把它打掉能得多少分”，没到就「撤退（无报酬）」重打——门票不用、不算一局（最多允许 {miss_cap} 局没到分）。")
        else:
            log.say("  五个区域一路走到最终首领跟前（一共 30 格），到了就停下、任务结束——不撤退，也不打最终首领（没有勾「使用门票」，不会用门票）。")
            log.say("  停下以后这一局交给你：自己打掉最终首领就结算；不想要就在地图上点「撤退（无报酬）」。")
        log.say("  中途要不要撤退重开看档位（见下面“档位”那一行）；商店买不买看设置。")
    else:
        log.say("  走几格再撤退" + mode)
        log.say("  会真的打战斗（AUTO）、选角色和遗物；不在商店买东西；区域 3 的首领会打，最终首领不打。最后撤退，门票不会少。")
    if args.resume:
        log.say("  请把游戏停在「迷宫首页」，或者直接停在进行中那一局的地图上。")
        log.say("  这一次勾了「接着打进行中的一局」：游戏里有一局打到一半的话，从地图接手往下打（后面和工具自己开的局一样走，"
                "档位规定要撤退重开的时候照样会撤退，那一局就没了）；没有进行中的一局就照常开新的。")
    else:
        log.say("  请先把游戏停在「迷宫首页」。")
    log.say(f"  档位：{tier.name}——{tier.blurb}。")
    if tier.reroll:
        log.say("  这一档凹的东西：首领" + (f"只留 {'、'.join(reroll['boss_want'])}" if reroll["boss_want"] else "不挑")
                + (f"，遇到 {'、'.join(reroll['boss_avoid'] + list(wk.get('boss_avoid') or []))} 就重开" if reroll["boss_avoid"] or wk.get("boss_avoid") else "")
                + (f"；前 {reroll['areas']} 个区域的事件折成分数低于 {reroll['event_min']:.0f} 就重开" if reroll["event_min"] > 0 and reroll["areas"] > 0 else "；事件不凹")
                + (f"；区域 {'、'.join(str(a) for a in reroll['no_shop_areas'])} 不走商店——有不过商店、极难又一列不落的路就走那条，绕不开就重开"
                   if reroll["no_shop_areas"] else "；路过商店不重开")
                + f"；最多重开 {max_restarts} 次（改这些：config/settings.json 的 walk.reroll）。")
    # 定时（阶段 5）：等到几点再开始；过了几点不再开新的一局
    start_at, stop_at = str(args.start_at or wk.get("start_at") or "").strip(), str(args.stop_at or wk.get("stop_at") or "").strip()
    if start_at:
        wait_s = seconds_until(start_at)
        if wait_s is None:
            log.say(f"  ! 开始时间「{start_at}」看不懂（要写成 23:30 这样），现在就开始。")
        else:
            log.say(f"  定时：等到 {start_at} 再开始（还有 {int(wait_s // 3600)} 小时 {int(wait_s % 3600 // 60)} 分）。"
                    f"这期间电脑不会自己睡眠、屏幕可以关；想取消，{'按 ' + key + ' 或' if sys.platform == 'win32' else ''}点界面上的「停止」。到点时游戏要停在迷宫首页（或者主页、标题画面）。")
            log.event("wait_until", at=start_at, seconds=round(wait_s))
            st0 = StopFlag()
            w0 = HotkeyWatcher(st0, key).start()
            aw0 = AFK.keep_awake(True)
            try:
                st0.sleep(wait_s)
            except Stopped as e:
                log.say(f"  已取消：{e}。还没开始，游戏没动。")
                log.close()
                return 0
            finally:
                w0.close()
                if aw0:
                    AFK.keep_awake(False)
            log.say(f"  {start_at} 到了，开始。")
    stop_ts = None
    if stop_at:
        left_s = seconds_until(stop_at)
        if left_s is None:
            log.say(f"  ! 结束时间「{stop_at}」看不懂（要写成 07:00 这样），不按时间停。")
        else:
            stop_ts = time.time() + left_s
            log.say(f"  定时：过了 {stop_at}（{int(left_s // 3600)} 小时 {int(left_s % 3600 // 60)} 分以后）就不再开新的一局；正在打的那一局会打完。")
    # 记录占的地方：一局的截图有两三百兆。设置里写了 logs.keep_shots（比如 20）就只留最近这么多次运行的截图；没写就只在太大时提醒一句
    keep_shots = int((cfg.get("logs") or {}).get("keep_shots", 0) or 0)
    try:
        cleared, freed = RL.prune_shots(keep_shots, skip=log.dir)
        if cleared:
            log.say(f"  记录：按设置只留最近 {keep_shots} 次运行的截图，清掉了更早 {cleared} 次的（腾出 {freed / 1e9:.1f} GB；文字记录都还在）。")
        runs_n, runs_bytes = RL.usage()
        if runs_bytes > 5e9:
            log.say(f"  记录：logs/runs 里有 {runs_n} 次运行的记录，一共 {runs_bytes / 1e9:.1f} GB。嫌占地方可以把旧的文件夹删掉，"
                    f"或者在 config/settings.json 里写 \"logs\": {{\"keep_shots\": 20}}，以后每次开工只留最近 20 次的截图。")
    except OSError:
        pass
    steps = 99 if args.full else args.steps
    if steps < 0:
        default = int(wk.get("steps", 3))
        s = console.ask(f"  走几格？（直接回车 = {default}；0 = 只看全图不走；区域 1 是 5 格，到区域 2 结束 11 格，打完区域 3 的首领 17 格）> ", str(default))
        try:
            steps = max(0, min(40, int(s)))
        except ValueError:
            steps = default
    survey = bool(wk.get("survey", True)) and not args.no_survey
    what = "走到最终首领跟前" if args.full else (f"走 {steps} 格" if steps else "只看全图")
    if not args.auto and not console.yes(f"  {what}，准备好了吗？", True):
        log.close()
        return 0
    try:
        dev = Device.open(log)
    except DeviceError as e:
        log.say(f"  × 连不上模拟器：{e}")
        log.close()
        return 1
    d = dev.describe()
    log.say(f"  已连接 {d['serial']}（{d['size'][0]}×{d['size'][1]}），截图：{d['screenshot']}，触摸：{d['touch']}")
    log.event("device", **d)
    if not dev.can_touch:
        log.say("  × MuMu 的触摸接口没连上，这一项做不了。先跑一次“连接测试”。")
        dev.close()
        log.close()
        return 1
    if hasattr(dev, "foreground"):                   # 顺手验一下“问系统谁在最前面”这条路（闪退恢复靠它）：结果写进日志
        fg = dev.foreground()
        log.event("foreground", app=fg, game=d.get("game"))
        if fg is None:
            log.say("  ! 问不到现在最前面的是哪个应用（ADB 没回话）：游戏闪退了的话认不出来，别的不受影响。")
        elif d.get("game") and fg != d["game"]:
            log.say(f"  ! 现在最前面的应用是 {fg}，不是游戏（{d['game']}）。请先把游戏切到前面。")
    if tuple(d["size"]) != (1920, 1080):
        log.say(f"  ! 画面不是 1920×1080（现在是 {d['size'][0]}×{d['size'][1]}），识别规则是按 1920×1080 做的，可能认不准。")

    stop = StopFlag()
    watcher = HotkeyWatcher(stop, key).start()
    log.say(f"  紧急停止：{'随时按 ' + key + '（在哪个窗口按都行），或' if watcher.active else ''}{'点界面上的「停止」' if os.environ.get('LNPCR_GUI') else '在这个窗口按 Ctrl+C'}。")
    log.say("")
    book = PageBook(paths.PROJECT_ROOT / "assets" / "pages")
    human = Human(dev, HumanParams.from_dict(cfg.get("human")), stop, idle=bool(wk.get("idle", False)) and bool(args.auto))
    lim = cfg.get("limits", {})
    # 上限跟着格数走：一格最多大约 30 下点击、4 分钟（一场打满的战斗加上前后页面）
    # 看全图每个区域要拖 4～8 下；极难走不到会重开，所以整体再乘上（重开次数 + 1）
    rounds = max_restarts + 1
    n = 30 if args.full else steps                   # 一整局是 31 格，第 31 格是最终首领（不打）
    # 按职能编队要翻页签、换人，一场战斗比原来多点十几下；打输了还会重打，所以每格的额度放宽
    limits = Limits(max_taps=(60 + 55 * n) * rounds, max_seconds=(420.0 + 320.0 * n) * rounds,
                    unknown_timeout=float(lim.get("unknown_timeout", 20)), wait_timeout=float(lim.get("wait_timeout", 90)),
                    unknown_wait=max(0.0, float(lim.get("unknown_wait", 1800))))
    runner = Runner(dev, book, human, log, stop, step_mode=not args.auto, limits=limits)
    if bool(cfg.get("notify", True)):                # 认不出画面、要你手动点过去的时候，右下角叫一声
        runner.on_ask = lambda text: NT.toast("龙娘pcr · 等你点一下", text)
    # 挂机（2026-11-24）：换日、连接出错会把游戏退回标题画面——认得出来就自己走回迷宫接着打；连续打几局；运行期间不让电脑睡过去
    recover_on = (bool(wk.get("recover", False)) or args.recover) and not args.no_recover
    recover_blind = recover_on and not ocr.available()      # 读字的组件不在：看不见“密码 / 验证码 / 支付”这些字，就不许它往回走
    runner.recovery = AFK.Recovery(runner, on=recover_on, relaunch=bool(wk.get("relaunch", True)))
    # 你自己动手点模拟器的时候先让一让（只在自动跑的时候管；单步模式每一下本来就要你点头）
    hd = cfg.get("hands") if isinstance(cfg.get("hands"), dict) else {}
    hands = None
    if args.auto and bool(hd.get("on", True)):
        try:
            quiet = float(hd.get("quiet", HD.QUIET))
        except (TypeError, ValueError):
            quiet = HD.QUIET
        hands = HD.Hands(match=hd.get("match"), quiet=quiet)
        if hands.start():
            runner.hands = hands
        else:
            hands = None
    laps = settle_laps if args.full else 1           # 黎明界迷宫：没勾「使用门票」只打一局；勾了才打 --laps 局（成功打完才算）
    if args.farm:                                    # 连续刷：局数上限用 farm.max_runs
        laps = max(1, min(50, int(args.max_runs or fm.get("max_runs", 10))))
    boss = boss_mode(bool(args.full), bool(args.farm), bool(args.spend), str(wk.get("boss", "mid")))
    dr = cfg.get("drill", {})
    # 公会（2026-11-24 起十个都能选）：命令行 / 界面 > 设置里的 walk.guild > 「刷分」（2026-11-25 用户定的：公会默认是刷分）
    gbook = GD.GuildBook(paths.PROJECT_ROOT / "data" / "learned" / "guilds.json")
    # 按饰品连续刷时没指定公会 = 「自动」：哪个公会出哪种饰品目录里写着（accessories.py），按还差的目标挑
    want_guild = str(args.guild or (GD.AUTO if args.farm else "") or wk.get("guild") or GD.SCORE).strip()
    score_mode = want_guild == GD.SCORE
    auto_guild = want_guild == GD.AUTO and bool(args.farm)
    usual_guild = GD.canon(str(wk.get("guild") or dr.get("guild_name", "慈乐之音"))) or GD.SCORE_DEFAULT      # 平时打的那个：自动挑的时候一样合适就先挑它
    default_guild = (usual_guild if args.farm else GD.SCORE_DEFAULT) if (score_mode or want_guild == GD.AUTO) else (GD.canon(want_guild) or want_guild)
    if not score_mode and want_guild != GD.AUTO and GD.canon(want_guild) is None:
        log.say(f"  ! 公会「{want_guild}」不在我知道的十个公会里（{'、'.join(GD.NAMES)}），照你写的名字去公会选择页上找。")
    for line in gbook.lines():
        log.say(line)
    awake = bool(cfg.get("keep_awake", True)) and AFK.keep_awake(True)
    log.say("  挂机：" + ("游戏换日（每天 5 点）、连接出错、退回标题画面时，我自己走回迷宫接着打（路上只点「确认」「重试」「跳过」「关闭」「冒险」和画面中间；"
                         "见到密码、验证码、实名、支付、充值这些字就停）" if recover_on and not recover_blind
                         else "! 读字的组件没装好，我看不出画面上写的是什么，所以遇到换日、掉线不会自己走回迷宫，会停下（在界面上点一次「准备运行环境」）" if recover_blind
                         else "没勾“自己走回迷宫”，遇到换日、掉线这类画面会停下")
            + (f"；这次连续打 {laps} 局" if laps > 1 else "")
            + ("；运行期间不让电脑自己睡眠（屏幕可以关）。" if awake else "。"))
    if hands is not None:
        log.say(f"  你自己动手：你在模拟器窗口里按鼠标的时候我先停手，等你停够 {hands.quiet:.0f} 秒再重新看画面接着来（不要这样：设置里 \"hands\": {{\"on\": false}}）。")
    raw_pick = wk.get("pick", "auto")
    # "auto" = 按规则挑（输出优先，物理魔法不混）；写名字 = 就选这三个人；写数字 = 名单里的第几格
    if isinstance(raw_pick, str):
        pick = "auto"
    elif any(isinstance(x, str) for x in raw_pick):
        pick = tuple(str(x) for x in raw_pick)
    else:
        pick = tuple(int(x) - 1 for x in raw_pick)
    team_mode = "order" if str(wk.get("team", "role")) == "order" else "role"
    defeat_retries = max(0, min(4, int(wk.get("defeat_retries", 2))))
    counters = EN.load_counters(paths.PROJECT_ROOT / "data")
    if team_mode == "role":
        log.say(f"  编队：认职能和属性按规则挑人；对策表里有 {len(counters['enemies'])} 个敌人（极难 / 首领）。"
                f"敌人名字的文字识别：{'可用' if ocr.available() else '没装好（只认得出见过的几个名字）'}。")
    events = load_event_defaults(paths.PROJECT_ROOT / "data")
    shop_cfg = wk.get("shop") if isinstance(wk.get("shop"), dict) else {}
    log.say("  商店：" + ("会买东西（先买每 1 分花金币少的：★1 遗物、随机印记；能更新就更新；最后一个区域把剩的金币花掉）。"
                         "每次点「确认」前核对金额，对不上就取消。" if shop_cfg.get("buy", True) else "设置里关了购买，路过只关掉。"))
    chars = CH.CharBook(paths.PROJECT_ROOT / "data" / "learned" / "portraits.json", CH.load_table(paths.PROJECT_ROOT / "data"))
    wiki.attach(chars, paths.PROJECT_ROOT / "data" / "learned")
    if team_mode == "role":
        log.say(f"  角色头像库：已经认识 {len(chars.names())} 个角色"
                + ("（还是空的：这一局会边走边从「角色加入」上读名字；想一次认全，先跑菜单 16「读角色」，再点菜单 17「更新角色」）。" if not chars.names() else "。"))
        if chars.reset_note:
            log.say("  " + chars.reset_note)
    advisor = AD.load(paths.PROJECT_ROOT / "data") if team_mode == "role" and bool(wk.get("estimate", True)) else None
    if team_mode == "role":
        log.say("  战斗估算：" + (f"开着（极难和区域 3 首领不按规则选人了：在名单里换人推演，上估算最好的一队；数据里有 {len(advisor.data.units)} 个角色、{len(advisor.data.stages)} 关）。"
                              if advisor is not None else "没开（设置里关了，或者 data/battle.json 不在），照规则排队。"))
    dmg = DM.DamageBook(paths.PROJECT_ROOT / "data" / "learned" / "damage.json") if team_mode == "role" else None
    report_on = (bool(wk.get("damage_report", False)) or args.report) and dmg is not None and not args.no_report
    if dmg is not None:
        chars.rates = dmg.rates()
        log.say("  真机伤害：" + ("每场打赢以后点开「伤害报告」看每个人打了多少，记下来；输出角色（攻击 / 破防）里谁伤害高就调高比重，增益、坦克、治疗不参加比较。"
                              "首领战也看；时间到了没打完（伤害不够）输的那一场也看，下一次照着换人。" + ("" if ocr.available() else "（没有读字的组件：数字读不了，按每个人那根条的长度算占比。）")
                              if report_on else "这一次不看伤害报告（没勾）。")
                + f"到现在记过 {len(dmg.fights)} 场、{len([1 for c in dmg.chars.values() if c.get('n')])} 个角色。")
    owned = chars.owned() if team_mode == "role" else set()
    if len(owned) >= 30:                             # 读过角色才有：按账号里角色的强度估一个档位，只是建议
        want, why = TR.suggest([chars.power(n) for n in owned])
        log.say(f"  按读过的 {len(owned)} 个角色估：{why}，适合{TR.get(want).name}"
                + ("。" if want == tier.n or (want == 2 and tier.n == 1) else f"；现在用的是{tier.name}（界面上可以改）。"))
    wins = WN.WinBook(paths.PROJECT_ROOT / "data" / "learned" / "wins.json") if team_mode == "role" and bool(wk.get("remember_wins", True)) else None
    if wins is not None:
        en, fn, wn = wins.summary()
        log.say(f"  打赢过的队：按敌人记真机上的结果，以后凑得齐就直接上赢过的那一队，只输没赢过的队不再上。到现在记过 {en} 个敌人、{fn} 场（赢 {wn} 场）。")
    if wins is not None:
        hard = wins.never_won("boss", 2)
        if hard and tier.reroll and reroll["auto_avoid"]:
            reroll["boss_avoid"] = reroll["boss_avoid"] + [x for x in hard if x not in reroll["boss_avoid"]]
            log.say(f"  这几个首领真机上打过两次以上、一次都没赢过：{'、'.join(hard)}——{tier.name}遇到它们就重开（不想这样：walk.reroll 里写 \"auto_avoid\": false）。")
        elif hard:
            log.say(f"  提醒：这几个首领真机上打过两次以上、一次都没赢过：{'、'.join(hard)}。想遇到就重开，可以用第一档，或者写进 walk.boss_avoid。")
    log.event("walk", tier=tier.n, steps=steps, pick=pick if pick == "auto" else list(pick), auto=bool(args.auto), survey=survey,
              max_restarts=max_restarts, full=bool(args.full), team=team_mode, defeat_retries=defeat_retries, ocr=ocr.available())
    code = 0
    farm_last = ""                                   # 连续刷：上一局打的公会
    flow = None
    ending = "跑完了"                               # 最后弹通知用：怎么结束的
    rows: list[dict] = []                            # 每一趟一行，最后写小结
    t_begin = time.time()
    base_taps, base_seconds = limits.max_taps, limits.max_seconds
    lap, restarts, relaps, adopt, misses = 1, 0, 0, False, 0
    resume = bool(args.resume)                       # 接着打进行中的一局：只对这一次的第一局有用（撤退重开以后开的都是新的一局）
    try:
        while True:
            if stop_ts is not None and time.time() >= stop_ts:
                log.say("")
                log.say(f"  过了 {stop_at}，不再开新的一局，停在这里。")
                log.event("stop_at", at=stop_at, lap=lap)
                break
            guild = default_guild
            if loot is not None:                     # 连续刷：看账本里哪个公会出还差的那种饰品出得多
                # 候选：设置里的 farm.guilds；没有的话，自动 = 十个公会（还差的是饰品时按目录挑；还差的只有材料、你又没明说「自动」，就用平时打的那个）
                wide = auto_guild and (str(args.guild).strip() == GD.AUTO or any(AC.parse_filter(k) is not None for k in loot.left()))
                cands = [GD.canon(g) or str(g) for g in (fm.get("guilds") or [])] or (list(GD.NAMES) if wide else [default_guild])
                guild, why_guild = loot.pick_guild(cands, farm_last or default_guild)      # 一样合适的时候接着打上一局那个，不来回换
                if not guild:                        # 候选的公会都出不了还差的饰品：硬打只会白花通行证，停
                    log.say("")
                    log.say(f"  ! 不开始：{why_guild}。")
                    log.say("    " + ("你在「公会」里选了固定的一个；改成「自动」，或者把目标改成这个公会出得了的。" if not auto_guild
                                      else "设置里的 farm.guilds 把候选公会限制住了；去掉它，或者改目标。"))
                    log.event("farm_no_guild", why=why_guild, candidates=cands, left=loot.left())
                    ending, code = "停下了：候选的公会出不了还差的饰品", 1
                    break
                farm_last = guild
                log.say(f"  这一局打「{guild}」：{why_guild}。")
            elif score_mode:                         # 刷分：默认咲恋救济院，攒够成绩以后挑平均估分最高的
                guild, why_guild = gbook.pick_for_score()
                log.say(f"  这一局打「{guild}」：{why_guild}。")
            else:
                log.say(f"  公会：{guild}。")
            flow = Walk(runner, GD.mark_of(guild), guild, steps=steps, pick=pick,
                        event_defaults=events, battle_timeout=float(wk.get("battle_timeout", 300)), survey=survey,
                        unknown_event=str(wk.get("unknown_event", "first")), slot_bet=bool(wk.get("slot_bet", False)),
                        boss=boss,                   # 只有连续刷 + 使用门票才是 "all"（见 boss_mode）；黎明界迷宫勾了门票的话，走到最终首领跟前再由 _final_gate 改成 "all"
                        loot=loot, wins=wins, keep_passes=int(fm.get("keep_passes", 0) or 0),
                        teams_mid=int(wk.get("boss_teams_mid", 1)), teams_final=int(wk.get("boss_teams_final", 3)),
                        route_values=wk.get("route_values") or {}, team_mode=team_mode, defeat_retries=defeat_retries,
                        counters=counters, chars=chars,
                        shop_buy=bool(shop_cfg.get("buy", True)), shop_rate=float(shop_cfg.get("max_rate", 5.0)),
                        shop_refresh_max=int(shop_cfg.get("refresh_max", 600)),
                        scout=bool(wk.get("scout_bosses", True)), boss_avoid=list(wk.get("boss_avoid") or []), advisor=advisor,
                        damage=dmg, damage_report=report_on, adopt=adopt, tier=tier, reroll=reroll,
                        auto_equip=auto_equip, settle_score=settle, settle_spend=settle_spend, final_stop=final_stop,
                        resume=resume)
            adopt, resume = False, False
            try:
                res = flow.run()
            except Relap as e:
                relaps += 1
                if relaps > 3:
                    raise Halt(f"{e}；这已经是第 {relaps} 次了，停下") from None
                log.say("")
                log.say(f"  {e}：从公会选择页接着开新的一局（不算重开次数）。")
                log.event("relap", why=str(e), n=relaps)
                adopt = True
                continue
            took = bool(res.get("took_over"))            # 这一局是接手的：是哪个公会、出发前有几张门票，工具都没看到
            pass_note = "这一局是接手的，出发前的门票数量我没看到，没法比（撤退会把这一局的门票退回，可以看一眼）" if took else "门票数量和出发前一样"
            rows.append({"n": len(rows) + 1, "guild": "（接手的一局）" if took else guild, "fights": res.get("fights") or [], "minutes": res.get("seconds", 0) / 60.0, "moves": len(res["moves"]), "battles": res["battles"],
                         "losses": res.get("losses"), "score": res.get("score_if_cleared") if (res.get("cleared") or res.get("at_final")) else None,
                         "result": "打通了" if res.get("cleared") else "停在最终首领跟前" if res.get("hold") else "没到分，撤退重打" if res.get("settled") == "redo"
                         else "走到最终首领跟前，撤退" if res.get("at_final")
                         else f"撤退（{res.get('why') or '没写原因'}）"})
            if (res.get("cleared") or res.get("at_final")) and not took:      # 走完了的一局：按公会记成绩（刷分挑公会用）；接手的那一局不知道是哪个公会，不记
                gbook.record(guild, res.get("score_if_cleared"), res.get("seconds", 0) / 60.0, "cleared" if res.get("cleared") else "final", tier.n)
                gbook.save()
            log.say("")
            route = " → ".join(MOVE_NAMES[m] for m in res["moves"]) or "（一格都没走）"
            log.say(f"  走过的格子：{route}")
            if res.get("cleared"):
                log.say(f"  ✓ 打通了：{len(res['moves'])} 格、{res['battles']} 场战斗，累计点了 {res['taps']} 下，这一趟用时 {res['seconds'] / 60:.0f} 分钟。"
                        f"分数页和宝箱的截图在记录文件夹的 shots 里（result_final、chest_result）。")
                if not res["ok"]:
                    log.say("  ! 回到迷宫首页后门票（通行证）数字那一块和出发前一样，按理应该少 1 张，请看一眼。")
                if loot is not None:
                    loot.save()
                    for line in loot.lines():
                        log.say(line)
                    if loot.done():
                        log.say("  ✓ 目标刷够了，停在这里。")
                        break
                    left = loot.left()
                    log.say("  还差：" + "、".join(f"{k} {n} 个" for k, n in left.items()) + "。")
                elif settle_spend:                   # 黎明界迷宫 + 使用门票：成功打完一局
                    log.say(f"  ✓ 第 {lap} 局打完了：最终首领打掉、已经结算，用了 1 张门票"
                            + (f"（估分 {res['score_if_cleared']:,}" + (f"，分数线 {settle:,}" if settle else "") + "）" if res.get("score_if_cleared") else "") + "。")
                    if lap >= laps:
                        ending = f"{laps} 局都打完了" if laps > 1 else "打完了，已经结算"
            elif res.get("hold"):                    # 没勾「使用门票」（或者门票要留着）：停在最终首领跟前，任务结束
                log.say(f"  ✓ {res['why']}。")
                log.say(f"    这一局：{len(res['moves'])} 格、{res['battles']} 场战斗，用时 {res['seconds'] / 60:.0f} 分钟。工具到这里就不点了。")
                ending = "停在最终首领跟前，交给你了"
                break
            elif res.get("settled") == "redo":       # 勾了门票、定了分数线，这一局没到分：已经撤退（门票没用），不算一局
                misses += 1
                log.say(f"  这一局没到分（估分 {res.get('score_if_cleared') or 0:,}，分数线 {settle:,}）：已经撤退，门票没用，不算一局。")
                if misses >= miss_cap:
                    log.say(f"  已经有 {misses} 局没到分了，到上限（设置里的 walk.settle_max_tries）了，先停在这里。分数线是不是定高了？")
                    ending = f"{misses} 局都没到 {settle:,} 分，停下了"
                    break
                log.say("")
                log.say(f"  —— 再来一局（第 {lap} 局还没打成；没到分的已经有 {misses} 局，上限 {miss_cap}）——")
                continue
            elif not res["ok"]:
                log.say(f"  ! 撤退回来了，但门票（通行证）数字那一块和出发前不一样（差异 {res['pass_diff']}）。请看一眼游戏里的门票数量，并把这个文件夹告诉我。")
                code = 1
                break
            elif res.get("at_final") and settle_spend:       # 勾了门票，但最终首领没打下来：已经撤退（门票没用），不算一局
                restarts += 1
                log.say(f"  最终首领没打下来（{res.get('why') or '撤退了'}）：已经撤退，门票没用，不算一局。")
                if restarts > max_restarts:
                    log.say(f"  已经重开 {max_restarts} 次，到上限了，先停在这里。")
                    ending = "最终首领打不下来，停下了"
                    break
                log.say("")
                log.say(f"  —— 重开第 {restarts} 次（上限 {max_restarts} 次）——")
                continue
            elif res.get("at_final"):
                log.say(f"  ✓ 走到最终首领跟前了：{len(res['moves'])} 格、{res['battles']} 场战斗，累计点了 {res['taps']} 下，这一趟用时 {res['seconds'] / 60:.0f} 分钟。"
                        f"已撤退，{pass_note}。撤退前的地图存了一张原图（shots 里的 before_final_boss）。")
                h = res.get("hud") or {}
                if res.get("score_if_cleared"):
                    log.say(f"  这一局要是把最终首领打掉，最终分数是 {res['score_if_cleared']:,}"
                            f"（角色 {h.get('chars')}、遗物 {h.get('relics')}，普通战 {res['moves'].count('normal')} 场、极难 {res['moves'].count('extreme')} 场）；"
                            f"{shortfall(res['score_if_cleared'])}。")
                else:
                    log.say("  左下角的角色数 / 遗物数没读出来，这一趟算不了分数（撤退前的地图截图在 shots 里，可以对着看）。")
                if shop_cfg.get("buy", True):
                    log.say("  " + shops_summary(res.get("shops") or [], h.get("coins")))
            else:
                log.say(f"  ✓ 这一趟：{len(res['moves'])} 格、{res['battles']} 场战斗，累计点了 {res['taps']} 下；"
                        f"撤退原因：{res['why']}；{pass_note}。")
                if res["restart"]:
                    restarts += 1
                    if restarts > max_restarts:
                        log.say(f"  已经重开 {max_restarts} 次，到上限了，先停在这里。")
                        break
                    log.say("")
                    log.say(f"  —— 重开第 {restarts} 次（上限 {max_restarts} 次）——")
                    continue
            if lap >= laps:
                break
            lap, restarts = lap + 1, 0                # 下一局：点击和时间的额度从头算
            rest = wk.get("rest_between", [20, 60])   # 局与局之间歇一会儿（计划里拟人化的“作息”那一条）；歇完“疲劳”也清零，不会越打越慢
            try:
                lo, hi = float(rest[0]), float(rest[1])
            except (TypeError, ValueError, IndexError):
                lo, hi = 20.0, 60.0
            if hi > 0:
                secs = random.uniform(max(0.0, lo), max(lo, hi))
                log.say("")
                log.say(f"  歇 {secs:.0f} 秒再开下一局。")
                stop.sleep(secs)
            human.t0 = time.time()
            runner.t0, runner.taps = time.time(), 0
            limits.max_taps, limits.max_seconds = base_taps, base_seconds
            log.say("")
            log.say(f"  —— 第 {lap} 局（这次{'最多' if args.farm else '一共'}打 {laps} 局{'' if args.farm else '，成功打完才算'}）——")
            log.event("lap", n=lap, of=laps)
    except Stopped as e:
        ending = ""                                  # 你自己点的停止：不用再通知
        log.say(f"\n  已停止：{e}。手指已经抬起，游戏停在当前画面。")
        log.say("  这一局还在进行中：不想要这一局，在地图上手动点「撤退（无报酬）」即可，门票不会少。")
        log.event("stopped", why=str(e), moves=flow.moves if flow else [])
    except Halt as e:
        ending = f"停下了：{e}"
        log.say(f"\n  停下了：{e}")
        log.say("  游戏停在当前画面，没有继续点。这一局还在进行中：不想要这一局，在地图上手动点「撤退（无报酬）」即可，门票不会少。")
        log.say("  把下面这个文件夹告诉我就行。")
        log.event("halt", why=str(e), moves=flow.moves if flow else [])
        log.dump_recent("halt")
        code = 1
    except KeyboardInterrupt:
        ending = ""
        log.say("\n  已停止（Ctrl+C）。这一局还在进行中，需要的话手动撤退。")
    except DeviceError as e:
        ending = f"设备出错：{e}"
        log.say(f"\n  × 设备出错：{e}")
        code = 1
    except Exception as e:  # noqa: BLE001 —— 程序自己的错：写进记录再停，别让它只在黑窗口里闪一下
        ending = f"工具自己出错了：{type(e).__name__}"
        log.crash(e, moves=flow.moves if flow else [])
        log.say("  这一局还在进行中：不想要这一局，在地图上手动点「撤退（无报酬）」即可，门票不会少。把下面这个文件夹告诉我就行。")
        code = 1
    finally:
        chars.save()
        note = ocr.items_problem()                   # “整张图找字”（挂机恢复、战利品清单、公会名字用）这一趟要是没读成，留下原因
        if note:
            log.say(f"  ! 这一趟“整张图找字”没读成（{note}）。不影响走格子和看伤害报告；挂机时自己走回迷宫、读战利品清单上的名字会受影响——把这次的记录给我。")
            log.event("ocr_items", note=note)
        if flow is not None and getattr(flow, "no_info", None):
            log.say(f"  这一趟认出了名字、但攻略表里还没有资料的角色（{len(flow.no_info)} 个）：{'、'.join(sorted(flow.no_info))}")
            log.event("no_info", names=sorted(flow.no_info))
        try:                                         # 小结：每一趟一行，写进 summary.txt，也打在记录最后
            title = "龙娘pcr · " + ("按饰品连续刷" if args.farm else "黎明界迷宫" if args.full else "走几格") + f" · {tier.name}"
            lines = summary_lines(title, t_begin, ending if ending != "跑完了" or not code else "出错了", rows, list(runner.recovery.log),
                                  list(hands.waits) if hands is not None else None)
            (log.dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            if len(rows) > 1:
                log.say("")
                log.say("  —— 小结 ——")
                for line in lines:
                    log.say("  " + line)
        except Exception:  # noqa: BLE001 —— 小结写不出来不影响别的
            pass
        if ending and bool(cfg.get("notify", True)):
            NT.toast("龙娘pcr · " + ("按饰品连续刷" if args.farm else "黎明界迷宫" if args.full else "走几格"),
                     ending if code or ending != "跑完了" else f"跑完了（第 {lap} 局）。记录在 {log.dir.name}")
        if awake:
            AFK.keep_awake(False)
        if hands is not None:
            hands.stop()
            log.event("hands", what="end", hits=hands.hits, waits=list(hands.waits), seen_emulator=hands.seen_emulator, own_seen=getattr(hands, "own_seen", 0))
            if hands.waits:
                log.say(f"  这一次运行里你自己动手点过模拟器，我停手让了 {len(hands.waits)} 次，一共 {sum(hands.waits):.0f} 秒。")
        if runner.hand_asks:
            log.say(f"  这一次运行里有 {len(runner.hand_asks)} 个画面我认不出来、是你手动点过去的（一共等了 {sum(runner.hand_asks):.0f} 秒）。截图在记录里，把排查包发给我就能补上。")
            log.event("ask_hand", what="end", waits=list(runner.hand_asks))
        if runner.recovery.log:
            log.say(f"  这一次运行里从游戏外面走回迷宫 {len(runner.recovery.log)} 次：{'；'.join(runner.recovery.log)}。")
        watcher.close()
        dev.close()
    log.say(f"  记录和截图在：{log.dir}")
    log.close()
    return code


if __name__ == "__main__":
    code = main()
    console.pause()
    sys.exit(code)
