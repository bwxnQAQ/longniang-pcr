"""更新角色：去资料站找国服现在有哪些角色，把全名、属性和头像加进头像库。

新角色上线以后点一下这一项就行；不用开游戏、不连模拟器。第一次要下七百来张小头像，之后只下新的。
资料站是 pcr.satroki.tech（名单、属性、头像），redive.estertion.win 做头像的备用（见 longniang_pcr/wiki.py 开头）。
这是工具里唯一会上网的一项：只读这两个公开的资料站。新角色什么时候出，看国服官号（界面右上角有链接，工具不读它）。
"""
from __future__ import annotations

import argparse
import sys

import _common  # noqa: F401

from longniang_pcr import chars as CH
from longniang_pcr import config, console, paths, wiki
from longniang_pcr.runlog import RunLog
from longniang_pcr.stop import HotkeyWatcher, StopFlag, Stopped


def main() -> int:
    console.setup()
    ap = argparse.ArgumentParser()
    ap.parse_args()
    log = RunLog("update")
    learned = paths.PROJECT_ROOT / "data" / "learned"
    table = CH.load_table(paths.PROJECT_ROOT / "data")
    book = CH.CharBook(learned / "portraits.json", table)
    log.say("")
    log.say("  更新角色：从资料站（pcr.satroki.tech，头像备用 redive.estertion.win）读国服的角色名单、属性和头像，加进头像库。不开游戏、不连模拟器。")
    if book.reset_note:
        log.say("  " + book.reset_note)
    log.say(f"  头像库里现在认识 {len(book.names())} 个角色，「读角色」看到过 {len(book.sightings)} 张头像。")
    code = 0
    stop = StopFlag()
    watcher = HotkeyWatcher(stop, str(config.load().get("stop_key", "F12"))).start()      # 下头像要几分钟：F12 / 界面上的「停止」随时能停
    try:
        res = wiki.update(book, learned, log.say, stop.check, save_raw=log.dir / "site_units.json", fallback=wiki.builtin_units(table))
        log.event("update", **{k: v for k, v in res.items() if k != "new_names"}, new_names=res["new_names"][:60])
        site = set(wiki.load_index(learned / "wiki.json")["chars"])
        if site:                                   # 【测试】我带的名单 / 角色特点表里，资料站上没有的名字（多半是我抄错的字）：记下来回头改表
            log.event("name_check", site=len(site), builtin=len(table.get("names") or []),
                      names_not_on_site=sorted(set(table.get("names") or []) - site)[:80],
                      traits_not_on_site=sorted(set(table.get("chars") or {}) - site)[:80],
                      site_not_in_builtin=sorted(site - set(table.get("names") or []))[:120])
        if not res["ok"]:
            code = 1
        else:
            log.say("")
            log.say(f"  ✓ 名单 {res['names']} 个角色"
                    + (f"；新下了 {res['icons_new']} 张头像" if res["icons_new"] else "")
                    + (f"（{res['icons_failed']} 张没下下来，下次再点会补）" if res["icons_failed"] else "")
                    + f"；头像库里现在认识 {len(book.names())} 个角色。")
            if not book.sightings:
                log.say("  还没读过角色：把游戏停在「角色」页，点一次菜单 16「读角色」，读完会自动拿这些头像来对。")
            if res.get("gone_names"):
                log.say(f"  上次名单里有、这次没有的名字（多半是旧资料站的写法不一样）：{'、'.join(res['gone_names'][:10])}")
            log.say(f"  新角色什么时候出，看国服官号：{wiki.OFFICIAL}（界面右上角「国服官号」）。出了以后再点一次这一项。")
    except Stopped as e:
        log.say(f"\n  已停止：{e}。已经下好的头像都留着，下次再点会接着下。")
    except KeyboardInterrupt:
        log.say("\n  已停止（Ctrl+C）。已经下好的头像都留着，下次接着来。")
    except Exception as e:  # noqa: BLE001
        log.crash(e)
        code = 1
    finally:
        watcher.close()
        book.save()
    log.say(f"  记录在：{log.dir}")
    log.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
