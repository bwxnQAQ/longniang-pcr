"""读角色：把账号里所有角色的名字和头像读一遍，记进头像库（只用来认人）。

先把游戏停在主界面底部的「角色」页（角色一览），再运行。新角色上线、或者给角色换过头像以后，再跑一次就行。
只看不改：只点列表里的第一张卡和「角色强化」页右边的 ▶；强化、升星、装备、显示切换里的选项都不碰。
"""
from __future__ import annotations

import argparse
import os
import sys

import _common  # noqa: F401

from longniang_pcr import chars as CH
from longniang_pcr import config, console, ocr, paths, wiki
from longniang_pcr.device.device import Device, DeviceError
from longniang_pcr.flows.roster import RosterScan
from longniang_pcr.human import Human, HumanParams
from longniang_pcr.runlog import RunLog
from longniang_pcr.runner import Halt
from longniang_pcr.stop import HotkeyWatcher, StopFlag, Stopped
from longniang_pcr.vision.pages import PageBook


def book_path():
    return paths.PROJECT_ROOT / "data" / "learned" / "portraits.json"


def show(log: RunLog, chars: CH.CharBook) -> None:
    names = chars.names()
    st = chars.resolve_sightings()
    log.say(f"  头像库里现在认得出 {len(names)} 个角色（全名）。「读角色」看到过 {st['total']} 张头像："
            f"{st['named']} 张定下了全名，{st['split']} 张只知道本名（有几个版本，等资料站的头像来分），{st['unread']} 张名字没读出来。")
    if names:
        for i in range(0, len(names), 8):
            log.say("    " + "、".join(names[i:i + 8]))
    tagged = [n for n in names if chars.tags(n)]
    log.say(f"  其中攻略表（data/characters.json）里有特点的 {len(tagged)} 个。")


def main() -> int:
    console.setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只看头像库里已经认识哪些角色，不连模拟器")
    ap.add_argument("--max", type=int, default=600, help="最多读多少个角色")
    ap.add_argument("--yes", action="store_true", help="不问“准备好了吗”，直接开始（图形界面用）")
    args = ap.parse_args()
    cfg = config.load()
    key = str(cfg.get("stop_key", "F12"))
    log = RunLog("roster")
    log.say("")
    chars = CH.CharBook(book_path(), CH.load_table(paths.PROJECT_ROOT / "data"))
    wiki.attach(chars, book_path().parent)
    if args.list:
        show(log, chars)
        log.close()
        return 0
    log.say("  读角色：把账号里所有角色的名字和头像读一遍（只用来认人，不读技能）。")
    log.say("  请先把游戏停在主界面底部的「角色」页（角色一览）。工具只点第一张卡和右边的 ▶，别的都不碰。")
    if chars.reset_note:
        log.say("  " + chars.reset_note)
    log.say(f"  头像库里现在有「读角色」看到过的头像 {len(chars.sightings)} 张。一个角色一秒多，全部读完六七分钟。")
    log.say("  注意：横条上只写本名、不带“（夏日）”这种版本，所以这一步读到的是“本名 + 头像”；是哪个版本，读完以后点菜单 17「更新角色」用资料站的头像来分。")
    if not ocr.available():
        log.say(f"  × 文字识别（OCR）没装好，读不了名字：{ocr.why_missing()}")
        log.close()
        return 1
    if not args.yes and not console.yes("  准备好了吗？", True):
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
    stop = StopFlag()
    watcher = HotkeyWatcher(stop, key).start()
    log.say(f"  紧急停止：{'随时按 ' + key + '（在哪个窗口按都行），或' if watcher.active else ''}{'点界面上的「停止」' if os.environ.get('LNPCR_GUI') else '在这个窗口按 Ctrl+C'}。")
    log.say("")
    book = PageBook(paths.PROJECT_ROOT / "assets" / "pages")
    human = Human(dev, HumanParams.from_dict(cfg.get("human")), stop, idle=False)
    flow = RosterScan(dev, book, human, log, stop, chars, max_chars=max(1, args.max))
    code = 0
    try:
        res = flow.run()
        log.say("")
        log.say(f"  ✓ 看了 {res['count']} 个角色：读出本名 {res['read']} 个，头像第一次见的 {res['new']} 个。用时 {res['seconds'] / 60:.1f} 分钟，点了 {res['taps']} 下。")
        if res["unread"]:
            log.say(f"  有 {res['unread']} 个角色的名字没读出来、或者读出来的字名单里没有（第 {'、'.join(str(n) for n in flow.unread[:20])} 个）：头像照记了、没有停，等头像去认。")
        log.say("  游戏停在最后一个角色的强化页，按左上角的返回就回到列表。")
        got = wiki.apply_icons(chars, book_path().parent, log.say)      # 资料站的头像已经下过的话，马上拿来分版本
        log.event("wiki_icons", **{k: v for k, v in got.items() if k != "sight"}, sight=got["sight"])
        if not got["calibrated"]:
            st = chars.resolve_sightings()
            log.say(f"  现在头像库里 {st['total']} 张头像：{st['named']} 张已经定下全名（本名只有一个版本的），"
                    f"{st['split']} 张只知道本名、还分不出是哪个版本。")
            if not (book_path().parent / "icons").exists():
                log.say("  下一步：点菜单 17「更新角色」——它去资料站下每个角色的头像，对上以后版本就分出来了。")
    except Stopped as e:
        log.say(f"\n  已停止：{e}。已经看过的 {flow.count} 个角色都存下来了，下次再点一次会从头再过一遍（见过的头像只是核对一下）。")
        log.event("stopped", why=str(e), read=flow.count)
    except Halt as e:
        log.say(f"\n  停下了：{e}")
        log.say(f"  已经看过的 {flow.count} 个角色都存下来了。游戏停在当前画面，没有继续点。把下面这个文件夹告诉我就行。")
        log.event("halt", why=str(e), read=flow.count)
        log.dump_recent("halt")
        code = 1
    except KeyboardInterrupt:
        log.say("\n  已停止（Ctrl+C）。")
    except DeviceError as e:
        log.say(f"\n  × 设备出错：{e}")
        code = 1
    except Exception as e:  # noqa: BLE001
        log.crash(e, read=flow.count)
        code = 1
    finally:
        chars.save()
        watcher.close()
        dev.close()
    log.say(f"  记录和截图在：{log.dir}")
    log.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
