"""重置到初始状态：把龙娘pcr变回刚下载时的样子。

清掉的（都是用的过程中产生的东西）：
  logs/                 运行记录和截图
  data/learned/         学到的东西：你有哪些角色和头像、打赢过的队、伤害记录、战利品账本、各公会的成绩、首次设置做没做过
  排查包/               导出过的排查包
  config/settings.json  改回默认设置
  界面记住的选项、检查更新时留的旧版本文件、“哪些可选组件装过没装上”的记号（都在 %LOCALAPPDATA%\\longniang-pcr 里）
不动的：程序本身（exe、longniang_pcr、tools、assets、data 里随版本发的资料表）；Python 运行环境（不用重新下载那 500 MB）。

清之前把要清的东西列出来、再问一遍（默认是“不”）；清掉以后找不回来。清完「首次设置」会重新出现。
只删上面写的这几处，别的一概不碰。只用 Python 自带的库。

命令行：龙娘pcr.exe reset          列出来、问一遍再清
        龙娘pcr.exe reset --yes    不问直接清
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Callable

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
# 项目文件夹里要清的：（相对路径, 说明）
IN_ROOT = (("logs", "运行记录和截图"), ("data/learned", "学到的东西（你有哪些角色、打赢过的队、伤害记录、战利品账本、公会成绩、首次设置做没做过）"),
           ("排查包", "导出过的排查包"))
# 运行环境那个文件夹里要清的（Python 环境本身不动）
IN_RT = (("gui_prefs.json", "界面记住的选项"), ("backup", "检查更新时留的旧版本文件"), ("update", "检查更新下载到一半的东西"),
         ("optional_tried.json", "“哪些可选组件没装上”的记号（清掉以后下次会再试着装）"))
SETTINGS = "config/settings.json"


def runtime_dir() -> Path:
    base = os.environ.get("LNPCR_RUNTIME") or os.path.join(os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache")), "longniang-pcr")
    return Path(base)


def default_settings(root: Path) -> str | None:
    """刚下载时 config/settings.json 里写的是什么（longniang_pcr/config.py 里存着一份）。拿不到返回 None。"""
    try:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from longniang_pcr import config

        return str(config.DEFAULT_FILE)
    except Exception:  # noqa: BLE001
        return None


def measure(path: Path) -> tuple[int, int]:
    """（几个文件, 一共多少字节）。"""
    if path.is_file():
        return 1, path.stat().st_size
    n = size = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                n, size = n + 1, size + p.stat().st_size
        except OSError:
            pass
    return n, size


def plan(root: Path, rt: Path) -> list[tuple[Path, str, int, int]]:
    """现在有哪些要清：（路径, 说明, 几个文件, 多少字节）。只列上面写的那几处里真的存在的。"""
    out = []
    for base, items in ((root, IN_ROOT), (rt, IN_RT)):
        for rel, what in items:
            p = base.joinpath(*rel.split("/"))
            if p.is_symlink() or not p.exists():       # 链接不跟着走、也不删
                continue
            n, size = measure(p)
            if p.is_file() or n or any(p.iterdir()):
                out.append((p, what, n, size))
    return out


def settings_changed(root: Path) -> bool:
    want = default_settings(root)
    f = root.joinpath(*SETTINGS.split("/"))
    if want is None:
        return False
    try:
        return f.read_text(encoding="utf-8-sig").replace("\r\n", "\n").strip() != want.strip()
    except OSError:
        return True                                    # 文件没了：补一份默认的


def wipe(path: Path) -> list[Path]:
    """删掉一个文件 / 整个文件夹。正被别的程序开着、删不掉的文件：把里面清空，留个空文件。返回没删掉的。"""
    left: list[Path] = []

    def empty(p: Path) -> None:
        try:
            with open(p, "w", encoding="utf-8"):
                pass
        except OSError:
            pass
        left.append(p)

    if path.is_file():
        try:
            path.unlink()
        except OSError:
            empty(path)
        return left
    for p in sorted(path.rglob("*"), key=lambda x: len(x.parts), reverse=True):      # 先里后外
        try:
            if p.is_dir() and not p.is_symlink():
                p.rmdir()
            else:
                p.unlink()
        except OSError:
            if p.is_file():
                empty(p)
    try:
        path.rmdir()
    except OSError:
        pass
    return left


def human(size: int) -> str:
    return f"{size / 1e9:.1f} GB" if size >= 1e9 else f"{size / 1e6:.1f} MB" if size >= 1e5 else f"{size / 1e3:.0f} KB"


def ask_no(prompt: str) -> bool:
    try:
        s = input(prompt + " [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return s in ("y", "yes", "是", "好", "1")


def run(args: list[str], root: Path = ROOT, rt: Path | None = None, ask: Callable[[str], bool] = ask_no,
        say: Callable[[str], None] = print) -> int:
    rt = rt or runtime_dir()
    say("")
    say("  重置到初始状态：把龙娘pcr变回刚下载时的样子。")
    if not (root / "tools" / "menu.py").is_file() or not (root / "longniang_pcr" / "__init__.py").is_file():
        say(f"  × {root} 看着不像龙娘pcr的文件夹（里面没有 tools/menu.py），什么都没动。")
        return 1
    todo = plan(root, rt)
    reset_settings = settings_changed(root)
    if not todo and not reset_settings:
        say("  已经是刚下载时的样子了，没有要清的。")
        return 0
    say("  会清掉这些（清掉以后找不回来）：")
    for p, what, n, size in todo:
        say(f"    · {what}：{p}" + (f"（{n} 个文件，{human(size)}）" if p.is_dir() else ""))
    if reset_settings:
        say(f"    · 设置改回默认：{root.joinpath(*SETTINGS.split('/'))}")
    say("  不动的：程序本身、Python 运行环境。")
    if "--yes" not in args and not ask("  确定要重置吗？"):
        say("  没有重置，什么都没动。")
        return 0
    left: list[Path] = []
    for p, _what, _n, _size in todo:
        left += wipe(p)
    if reset_settings:
        text = default_settings(root)
        f = root.joinpath(*SETTINGS.split("/"))
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text or "", encoding="utf-8", newline="\n")
        except OSError as e:
            say(f"  ! 设置没改回去（{e}）。")
    if left:
        say(f"  有 {len(left)} 个文件正被开着、删不掉，已经把里面清空了（比如界面自己的日志）。")
    say("")
    say("  重置好了：运行记录、学到的东西、设置都回到刚下载时的样子。")
    if os.environ.get("LNPCR_GUI") == "1":
        say("  界面马上自己重新打开，「首次设置」会重新出现。")
    else:
        say("  下次打开界面，「首次设置」会重新出现。")
    return 0


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    code = run(sys.argv[1:])
    if os.environ.get("LNPCR_GUI") != "1":
        try:
            input("  按回车继续……")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


if __name__ == "__main__":
    sys.exit(main())
