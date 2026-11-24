"""首次设置：第一次用的时候做一遍——看运行环境、模拟器、挂机要用的几样行不行，最后扫描一次角色。

把原来散着的几项合在这里（2026-11-17 晚用户定的“一次性但必要的内容写到一起，下载好后一次解决”；2026-11-24 深夜做的）：
中文路径测试、连接测试、触摸测试、挂机体检 → 这里的 ①②③，只留“能不能用”，哪项不行直接说怎么改，不写长报告；
读角色、更新角色 → ④（也就是界面上的「扫描角色」）。
不点游戏（④ 除外：那一步只在「角色」页点第一张卡和 ▶）。做完在 data/learned/first_run.json 记一笔，界面上就不再显示这一项；
想重做：龙娘pcr.exe setup。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import numpy as np

import _common  # noqa: F401
from longniang_pcr import afk as AFK, config, console, imgio, notify as NT, ocr, paths
from longniang_pcr.device.device import Device, DeviceError
from longniang_pcr.runlog import RunLog
from longniang_pcr.vision.pages import PageBook, to_norm

WANT_SIZE = (1920, 1080)


def flag_path():
    return paths.PROJECT_ROOT / "data" / "learned" / "first_run.json"


def done() -> bool:
    try:
        return bool(json.loads(flag_path().read_text(encoding="utf-8")).get("done"))
    except Exception:  # noqa: BLE001
        return False


def mark_done(checks: dict[str, Any], how: str = "ran") -> None:
    p = flag_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"done": True, "when": time.strftime("%Y-%m-%d %H:%M:%S"), "how": how, "checks": checks}, ensure_ascii=False, indent=1), encoding="utf-8")


def retry_optional() -> bool:
    """可选组件（读字的那个）再装一次，然后在一个新的 Python 里看它起不起得来。返回现在可不可用。"""
    import subprocess

    try:
        import setup_env

        setup_env.ensure(retry_optional=True)
        code = "import sys; sys.path.insert(0, sys.argv[1]); from longniang_pcr import ocr; raise SystemExit(0 if ocr.available() else 1)"
        return subprocess.call([sys.executable, "-c", code, str(paths.PROJECT_ROOT)]) == 0
    except Exception:  # noqa: BLE001
        return False


def check_env(say: Any, work: Any) -> dict[str, Any]:
    """① 运行环境：项目放在带中文的文件夹里读写图片行不行、读字的组件在不在。"""
    out: dict[str, Any] = {}
    try:
        f = work / "中文路径测试.png"
        img = np.full((40, 60, 3), 200, np.uint8)
        imgio.imwrite(f, img)
        back = imgio.imread(f)
        out["path"] = back is not None and back.shape == img.shape
    except Exception as e:  # noqa: BLE001
        out["path"], out["path_err"] = False, f"{type(e).__name__}: {e}"
    say("      " + ("✓ 项目文件夹（路径里有中文）读写图片正常。" if out["path"] else
                    f"× 在项目文件夹里读写图片出错（{out.get('path_err', '读回来的不对')}）：把整个文件夹挪到路径短一点、没有特殊符号的地方再试。"))
    out["ocr"] = ocr.available()
    if not out["ocr"]:                               # 第一次装的时候没装上（多半是网络）：这里再试着装一次
        say("      读字的组件（OCR）没装好，再试着装一次（要联网，一两分钟）……")
        out["ocr"] = retry_optional()
    say("      " + ("✓ 读字的组件（OCR）可用。" if out["ocr"] else
                    f"× 读字的组件还是没装上（{ocr.why_missing()}）：认不了角色和敌人的名字。检查网络（需要的话开着代理），"
                    "然后在这个文件夹里打开命令行运行 龙娘pcr.exe setup 再做一遍。"))
    return out


def check_device(say: Any, log: RunLog) -> tuple[dict[str, Any], Any]:
    """② 模拟器：连得上、分辨率对、截得到图、点得了；顺便看一眼“整张图找字”读不读得回字。返回（结果, 截到的图）。"""
    out: dict[str, Any] = {"connected": False}
    try:
        dev = Device.open(log)
    except DeviceError as e:
        say(f"      × 连不上模拟器：{e}")
        say("        先把 MuMu 模拟器和游戏开起来，再点一次「首次设置」。MuMu 的设置里要开着“ADB 调试 / 开发者选项里的 USB 调试”。")
        return out, None
    img = None
    try:
        out["connected"] = True
        info = dev.describe()
        w, h = dev.size
        out.update(size=[w, h], screenshot=info.get("screenshot"), touch=info.get("touch"))
        say(f"      ✓ 连上了：{info.get('serial')}，截图用{info.get('screenshot')}，触摸用{info.get('touch')}。")
        out["size_ok"] = (w, h) == WANT_SIZE
        say("      " + (f"✓ 分辨率 {w}×{h}。" if out["size_ok"] else
                        f"× 分辨率是 {w}×{h}，要 {WANT_SIZE[0]}×{WANT_SIZE[1]}：MuMu 右上角菜单 → 设置中心 → 显示 → 选 1920×1080（平板版 / 自定义都行），重启模拟器。"))
        img = dev.screenshot()
        out["shot_ok"] = img is not None and float(np.asarray(img).std()) > 2.0
        say("      " + ("✓ 截得到画面。" if out["shot_ok"] else "× 截到的画面是一片纯色：模拟器是不是最小化了、或者还在启动？把它打开放着再试。"))
        out["touch_ok"] = bool(getattr(dev, "can_touch", False))
        say("      " + ("✓ 触摸接口可用。" if out["touch_ok"] else "× 没有能用的触摸接口：工具点不了游戏。把 MuMu 更新到最新版再试；还不行把这次的记录给我。"))
        if out["shot_ok"]:
            log.shot(img, "first_run", png=True)
    finally:
        dev.close()
    return out, img


def check_reading(say: Any, img: Any) -> dict[str, Any]:
    """②（续）认不认得出现在的画面、“整张图找字”读不读得回字（挂机时自己走回迷宫、读战利品的名字靠它）。"""
    out: dict[str, Any] = {}
    if img is None:
        return out
    try:
        res = PageBook(paths.PROJECT_ROOT / "assets" / "pages").recognize(img)
        out["page"] = res.page if res.known else None
        say("      " + (f"✓ 现在的画面认得：{res.name}。" if res.known else "· 现在的画面不是黎明界迷宫里的页面（没关系，只是告诉你一声）。"))
    except Exception as e:  # noqa: BLE001
        out["page_err"] = f"{type(e).__name__}: {e}"
    if ocr.available():
        items = ocr.read_items_or_none(to_norm(img))
        note = ocr.items_problem()
        out["items"], out["items_note"] = (len(items) if items is not None else None), note
        if items:
            say(f"      ✓ 整张图找字：读到 {len(items)} 段（比如“{items[0][0][:12]}”）。")
        elif note:
            say(f"      × 整张图找字没读成：{note}。走格子、打战斗、看伤害报告不受影响；挂机时“换日 / 掉线以后自己走回迷宫”和“读战利品清单上的名字”会受影响。把这次的记录给我。")
        else:
            say("      · 整张图找字：这个画面上一段字都没读到（画面上本来没字的话是正常的）。")
    return out


def check_afk(say: Any, cfg: dict[str, Any]) -> dict[str, Any]:
    """③ 挂机要用的：运行期间不让电脑睡眠、右下角的通知。"""
    out: dict[str, Any] = {}
    out["keep_awake"] = AFK.keep_awake(True)
    AFK.keep_awake(False)
    say("      " + ("✓ 运行期间不让电脑自己睡眠：管用（屏幕照样可以关）。" if out["keep_awake"] else
                    "× 不让电脑睡眠在这台电脑上不管用：挂机前自己把 Windows 的“睡眠”改成“从不”。"))
    out["toast"] = NT.toast("龙娘pcr · 首次设置", "这是一条测试通知：看到它，说明跑完 / 停下的时候你能收到。") if bool(cfg.get("notify", True)) else None
    say("      " + ("· 通知在设置里关着（notify: false），没有发。" if out["toast"] is None else
                    "✓ 右下角发了一条测试通知。没看到的话，多半是 Windows 的“请勿打扰”开着——不影响别的，只是跑完没有提醒。" if out["toast"] else
                    "× 通知没发出去。不影响别的，只是跑完没有提醒。"))
    return out


def main() -> int:
    console.setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip", action="store_true", help="不做，只记一笔“已经弄好了”，界面上不再显示这一项")
    ap.add_argument("--no-scan", action="store_true", help="不问要不要扫描角色")
    args = ap.parse_args()
    if args.skip:
        mark_done({}, "skipped")
        print("\n  好，记下了：首次设置不再显示。以后想做一遍：在这个文件夹里打开命令行，运行 龙娘pcr.exe setup。")
        return 0
    cfg = config.load()
    log = RunLog("first_run")
    say = log.say
    checks: dict[str, Any] = {}
    say("")
    say("  首次设置：看一遍运行环境、模拟器、挂机要用的几样行不行，最后扫描一次角色。前三步不点游戏，一分钟左右。")
    say("")
    say("  [1/4] 运行环境")
    checks["env"] = check_env(say, log.dir)
    say("  [2/4] 模拟器（MuMu 要开着，游戏开不开都行）")
    checks["device"], img = check_device(say, log)
    checks["reading"] = check_reading(say, img)
    say("  [3/4] 挂机要用的")
    checks["afk"] = check_afk(say, cfg)
    d = checks["device"]
    good = bool(checks["env"].get("path") and d.get("connected") and d.get("size_ok") and d.get("shot_ok") and d.get("touch_ok"))
    log.event("first_run", ok=good, **checks)
    say("")
    if not good:
        say("  ! 上面带 × 的要先弄好（每一条后面写了怎么改），弄好以后再点一次「首次设置」。这一次先不记“做完了”。")
        say(f"  记录在：{log.dir}")
        log.close()
        return 1
    say("  ✓ 前三步都行，工具可以用了。" + ("" if checks["env"].get("ocr") else "（读字的组件没装好那一条，建议先处理。）"))
    say("  [4/4] 扫描角色：把你有的角色读一遍，再去资料站更新名单和头像（七八分钟）。编队认人靠它；以后抽到新角色，在界面上点「扫描角色」再来一次。")
    scan = None
    if not args.no_scan:
        if console.yes("  现在扫描吗？要先把游戏停在主界面底部的「角色」页（角色一览）。", True):
            log.close()
            mark_done(checks)                        # 前三步已经过了：先记上，扫描中途停了也不用从头来
            import scan_chars

            scan = scan_chars.main()
            print("\n  首次设置做完了。" + ("" if scan == 0 else "扫描角色没做完，之后在界面上点「扫描角色」补上就行。"))
            return 0
        say("  好，这一次不扫。之后把游戏停到「角色」页，在界面上点「扫描角色」。")
    mark_done(checks)
    say("  首次设置做完了，界面上不再显示这一项。")
    say(f"  记录在：{log.dir}")
    log.close()
    return 0


if __name__ == "__main__":
    code = main()
    console.pause()
    sys.exit(code)
