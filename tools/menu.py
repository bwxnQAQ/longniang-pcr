"""菜单 / 入口。

平时：双击“龙娘pcr.exe”→ 弹出图形界面（tools/gui.py），没有黑窗口。
“龙娘pcr.exe”是个编译好的小程序（源代码在 tools/dev/launcher）：运行环境没准备好就先开个窗口准备（要显示进度），然后调用这个文件。
    龙娘pcr.exe            打开界面
    龙娘pcr.exe console    黑窗口里输数字的菜单（图形界面打不开时的退路）
    龙娘pcr.exe clear | farm | scan | setup | export | update | reset   直接跑某一项
内部用的两个参数：prepare（只检查 / 安装依赖，exe 在打开界面之前调）、window（用 pythonw 运行：没有黑窗口的图形界面）。
2026-11-25（V1.0）：原来的“启动.bat”和每台电脑现做 exe 的 make_exe.py 都没有了，它们干的事在 exe 里。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT))

import setup_env  # noqa: E402

# 正式版 V1.0（2026-11-25）。每一项：（脚本, 说明, 标签）。标签以前分【正式】【测试】【一次性】，界面上会显示；
# 正式版里全是正式的功能，标签不再显示了（这一格留着只是因为界面的代码还按三格读）。
RELEASE = True
ITEMS = {
    "9": ("first_run.py", "首次设置：第一次用的时候做一遍——看运行环境、模拟器、挂机要用的几样行不行，最后扫描一次角色（前三步不点游戏，一分钟左右）。做完就不再显示", "正式"),
    "15": ("clear.py", "黎明界迷宫：五个区域走到最终首领跟前。不勾「使用门票」只打一局，到了就停下、任务结束；勾了就打最终首领并结算，"
                       "每成功打完一局用 1 张门票，可以定打几局、到多少分才结算", "正式"),
    "18": ("farm.py", "按饰品数量连续刷：先挑要哪几件（可以挑到具体一件、一个系列、一个部位、一种属性），它自己选出得了的公会，一局一局打通（打掉最终首领、结算、开宝箱），"
                      "按名字和图标把战利品里的饰品认出来记账，没刷够就接着打。每打通一局用掉 1 张门票；不勾「使用门票」就只说明、不动手", "正式"),
    "16": ("scan_chars.py", "扫描角色：抽到新角色、游戏出了新角色以后按一下——先在游戏的「角色」页把你有的角色读一遍，再去资料站（pcr.satroki.tech）更新名单、属性和头像。"
                            "要先把游戏停在主界面底部的「角色」页", "正式"),
}
EXTRA = {"6": ("导出排查包：出了问题点这个——把最近几次运行的记录、关键截图、设置和环境信息打成一个 zip（在项目文件夹的「排查包」里），发到 QQ 群", "正式"),
         "5": ("检查更新：去 GitHub 看有没有新版本，有的话下载、换上，然后重新打开界面（下载和更换只在你点的时候做；你的设置和记录不动）", "正式"),
         "8": ("重置到初始状态：把龙娘pcr变回刚下载时的样子——运行记录、学到的角色数据、设置、排查包都清掉，「首次设置」重新来（清之前会再问一遍）", "正式")}
ALIASES = {"setup": "9", "clear": "15", "farm": "18", "scan": "16"}
TOOL_ALIASES = {"export": "export_report.py", "update": "update.py", "reset": "reset.py"}       # 不在 ITEMS 里的小工具：龙娘pcr.exe export


def shown(key: str) -> bool:
    tag = ITEMS[key][2] if key in ITEMS else EXTRA[key][1]
    return tag == "正式" or not RELEASE


def line(key: str) -> str:
    text = ITEMS[key][1] if key in ITEMS else EXTRA[key][0]
    return f"  {key:>2}  {text}"


def run_tool(script: str, extra: list[str] | None = None) -> int:
    print("")
    try:
        code = subprocess.call([sys.executable, str(TOOLS / script)] + (extra or []), cwd=str(ROOT))
    except KeyboardInterrupt:
        code = 130
    if code not in (0, 1):
        print(f"\n  （这一项异常退出了，代码 {code}。已经写出来的报告还在，把情况告诉我就行）")
    return code


def open_folder(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.startfile(str(p))  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        print(f"  打不开文件夹：{e}\n  路径是：{p}")


def message_box(text: str) -> None:
    """没有黑窗口时出了错，弹个框说一声（不然什么都看不到）。"""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "龙娘pcr", 0x30)      # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


def launcher_exe() -> Path:
    """“龙娘pcr.exe”在哪（它启动我们的时候会用 LNPCR_EXE 告诉我们；没说就当它在项目文件夹最外层）。"""
    return Path(os.environ.get("LNPCR_EXE") or ROOT / "龙娘pcr.exe")


def run_window() -> int:
    """用 pythonw 运行的那条路：没有黑窗口，打印的东西写进 logs/gui.log，出错弹框。"""
    log = None
    try:
        (ROOT / "logs").mkdir(parents=True, exist_ok=True)
        log = open(ROOT / "logs" / "gui.log", "a", encoding="utf-8", buffering=1)      # noqa: SIM115
        log.write(f"\n==== {__import__('time').strftime('%Y-%m-%d %H:%M:%S')} 启动界面 ====\n")
        sys.stdout = sys.stderr = log
    except OSError:
        pass
    try:
        (launcher_exe().with_name(launcher_exe().name + ".old")).unlink()      # 上次更新时让开的旧 exe（见 tools/update.py）
    except OSError:
        pass
    try:
        if not setup_env.ready():                 # 依赖不全：要装东西，交给“龙娘pcr.exe --setup”（它会开一个窗口，看得到进度）
            exe = launcher_exe()
            if exe.exists():
                subprocess.Popen([str(exe), "--setup"], cwd=str(ROOT), close_fds=True)      # noqa: S603
                return 0
            message_box("运行环境里缺东西，而且找不到“龙娘pcr.exe”。把它放回项目文件夹里再双击一次。")
            return 1
        import gui

        return gui.main(ITEMS, EXTRA, RELEASE, windowless=True)
    except Exception as e:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        message_box(f"界面没能打开：{type(e).__name__}: {e}\n\n可以改用黑窗口菜单：在这个文件夹里打开命令行，运行 龙娘pcr.exe console。详细的出错信息在 logs\\gui.log 里。")
        return 1
    finally:
        if log is not None:
            log.close()


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "window":
        return run_window()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if not setup_env.ensure():
        input("\n  按回车退出……")
        return 1
    if args and args[0] == "prepare":             # “龙娘pcr.exe”打开界面之前调：依赖齐了就行，接下来它会用 pythonw 打开界面
        return 0
    if args and args[0] in ALIASES:
        return run_tool(ITEMS[ALIASES[args[0]]][0], args[1:])
    if args and args[0] in TOOL_ALIASES:
        return run_tool(TOOL_ALIASES[args[0]], args[1:])
    if not (args and args[0] == "console"):
        try:
            import gui

            return gui.main(ITEMS, EXTRA, RELEASE)
        except Exception as e:  # noqa: BLE001  图形界面起不来：退回黑窗口菜单，别让人什么都用不了
            print(f"\n  图形界面没起来（{type(e).__name__}: {e}），先用黑窗口菜单。")
    while True:
        print("")
        print("  ================================")
        print("   龙娘pcr")
        print("  ================================")
        groups = (("黎明界迷宫", ("15",)), ("按饰品数量连续刷", ("18",)), ("其他", ("16", "9", "6", "5", "8")))
        for title, keys in groups:
            keys = [k for k in keys if shown(k)]
            if keys:
                print(f"   —— {title} ——")
                for k in keys:
                    print(line(k))
        print("   0  退出")
        print("")
        try:
            c = input("  输入数字后回车：").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if c == "0":
            return 0
        if c in ITEMS and shown(c):
            run_tool(ITEMS[c][0])
        elif c in EXTRA and not shown(c):
            print("  没有这一项")
        elif c == "6":
            run_tool("export_report.py")
        elif c == "5":
            run_tool("update.py")
        elif c == "8":
            run_tool("reset.py")
        else:
            print("  没有这一项")


if __name__ == "__main__":
    sys.exit(main())
