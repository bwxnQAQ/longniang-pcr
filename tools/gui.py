"""图形界面（正式版 V1.0；2026-11-24 重新排过一次版：最上面是「黎明界迷宫」这一块——四个档位、连续打几局、几个开关、一个大的「开始」；
「角色」单独一块；检验用、一次性的工具收进下面折叠的一栏；状态行下面多一排小标签（档位、第几局、区域、输赢、重开、估分））。

双击“龙娘pcr.exe”以后弹出一个窗口，没有黑窗口：最上面一行写着现在在干什么，下面是各项功能的按钮
（带【正式】【测试】【一次性】标签）；想看完整的输出点「详细输出」展开。工具提问时，问题显示在那一行上，旁边有回答用的按钮。

做法：在本机开一个只有自己能连的小网页（127.0.0.1，带一次性的口令），用 Edge 的“应用窗口”方式打开——看起来就是一个普通窗口，
不用装任何额外的东西。每一项功能还是原来那个脚本，这里只是替你启动它（不弹黑窗口）、把它打印的字搬到窗口里、把你点的按钮和输入转给它。
后台没有窗口，所以什么时候退出全看界面：关掉界面窗口 → 正在跑的功能先让它停下 → 后台退出。
很久收不到界面的消息（窗口没了却没打招呼）也一样退出，不会留一个看不见的东西在后面点游戏。
"""
from __future__ import annotations

import codecs
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
MAX_LINES = 6000
QQ_GROUP = "891856490"    # 用户的 QQ 群（2026-11-25 让加在「检查更新」右边）：出了问题把排查包发到这里
OFFICIAL_URL = "https://space.bilibili.com/353840826"      # 国服官号：新角色的消息在这。工具不去读它，只是界面上给个链接，由你自己看
LOGO = ROOT / "assets" / "logo_256.png"
SILENT_S = 180.0          # 这么久收不到界面的消息，就当界面窗口没了（窗口最小化时浏览器最慢一分钟才问一次，所以不能设太短）
RESTART_WAIT_S = 5.0      # 更新好了以后等界面来叫“重新打开”，最多等这么久
STOP_WAIT_S = 15.0        # 退出时让正在跑的功能自己停下，最多等这么久，再不停就强制结束
# 每一项在界面上多出来的小选项： (名字, 种类, 默认值, 说明)
# 2026-11-25 用户定的：所有的勾默认都不勾；公会默认是「刷分」（按饰品刷是「自动」）。
# 种类：number 数字、check 勾选、tier 档位（界面上是四张卡片）、select 下拉、text 一行字、time 钟点
OPTIONS: dict[str, list[tuple[str, str, Any, str]]] = {
    # spend = 使用门票（通行证）：不勾就只打一局、停在最终首领跟前；勾了才打最终首领并结算，成功打完才算一局。每次都要重新勾，不记。
    # settle = 分数线（只在勾了门票时有用）：没到分的局撤退重打，不用门票、不算一局
    # resume = 接着打进行中的一局（2026-11-27）：游戏里有一局打到一半时从地图接手；不勾就照旧停下、不动那一局。每次都要重新勾，不记
    # shop2 = 第二层（区域 2）绕不开商店就重开。原来只有第一档看得到这个勾；2026-11-27 用户要的：哪一档都能勾（别的档位勾了带 --shop-reroll）
    # marks1 = 第一层（区域 1）没有双角色格就重开（2026-11-27 用户要的，放在 shop2 上面）：区域 1 踩不到两个印记格就撤退重开（--marks-reroll）
    # boss3 = 第三层（区域 3）首领一队过不了就重开（2026-11-27 用户定的：以前第一、二档默认就这样，现在不再是默认的；--boss3-single）。
#       不勾：哪一档都是打输了下一次多编一队
    # ex4 = 第四层（区域 4）没有双极难就重开（2026-11-27 用户定的：以前第一、二档默认就这样，现在不再是默认的，勾了才重开；--ex4-reroll）
    "15": [("tier", "tier", 2, "档位"), ("guild", "select", "", "公会"),
           ("spend", "check", False, "使用门票（不勾选则停在最终boss前）"),
           ("laps", "number", 1, "打几局"), ("settle", "number", 0, "到多少分才结算（0 = 不看分数）"),
           ("resume", "check", False, "接着打进行中的一局"),
           ("report", "check", False, "每场打完看伤害报告"), ("equip", "check", False, "编完队自动装备特别装备"),
           ("recover", "check", False, "换日 / 掉线后自己走回迷宫"),
           ("boss_want", "text", "", "第一档·只留这些首领（空着不挑）"), ("boss_avoid", "text", "", "第一档·遇到就重开的首领"),
           ("marks1", "check", False, "第一层（区域 1）没有双角色格就重开"),
           ("shop2", "check", False, "第二层（区域 2）绕不开商店就重开"),
           ("boss3", "check", False, "第三层（区域 3）首领一队过不了就重开"),
           ("ex4", "check", False, "第四层（区域 4）没有双极难就重开"),
           ("start_at", "time", "", "定时：几点开始"), ("stop_at", "time", "", "几点以后不再开新的一局")],
    # 按饰品数量连续刷：text = 一行字。spend（使用门票）每次都要重新勾，不记
    "18": [("targets", "text", "", "目标"), ("max_runs", "number", 10, "最多打通几局"), ("tier", "tier", 2, "档位"), ("guild", "select", "", "公会"),
           ("spend", "check", False, "使用门票（每打通一局用 1 张）"), ("fresh", "check", False, "从头数（不接着上一轮）"),
           ("report", "check", False, "每场打完看伤害报告"), ("equip", "check", False, "编完队自动装备特别装备")],
}
PREFS_V = 2               # 界面记住的选项是哪一套默认值下面记的（2 = 2026-11-25：开关默认都关、公会默认刷分）。对不上的旧记录不用
NEVER_REMEMBER = ("spend", "fresh", "start_at", "stop_at", "resume")      # 这几个每次都要重新填 / 勾：记住了反而会出意外（比如点开始却等到明天）
# 这几个选项的默认值跟着 config/settings.json 走：(选项名, walk 里的键)
FROM_SETTINGS = (("guild", "guild"), ("tier", "tier"), ("laps", "laps"), ("report", "damage_report"), ("equip", "auto_equip"), ("recover", "recover"))
GROUPS = (("黎明界迷宫", ("15",)), ("按饰品数量连续刷", ("18",)), ("其他", ("16", "6", "5", "8")))
EXPORT = "6"              # 「导出排查包」
UPDATE = "5"              # 「检查更新」：更新成功以后界面自己重新打开（Launcher.restart → watch → relaunch）
RESET = "8"               # 「重置到初始状态」：清完以后界面也自己重新打开（首次设置重新出现、选项回到默认）
# 这三个和「扫描角色」一起在「其他」里（2026-11-25 用户定的；「重新安装依赖」删了）
FIRST_RUN = "9"           # 「首次设置」：不在上面的分组里——只在还没做过的时候，在界面最上面单独显示一张卡片


def first_run_needed(root: Path = ROOT) -> bool:
    """还没做过「首次设置」（做过、或者点过“已经弄好了”，会在 data/learned/first_run.json 里记一笔）。"""
    try:
        return not bool(json.loads((root / "data" / "learned" / "first_run.json").read_text(encoding="utf-8")).get("done"))
    except Exception:  # noqa: BLE001
        return True


def build_cmd(key: str, items: dict[str, tuple], opts: dict[str, Any], python: str = sys.executable) -> list[str]:
    """界面上点了某一项 → 要运行的命令。opts 是那一项的小选项。"""
    if key == RESET:
        return [python, str(TOOLS / "reset.py")]
    if key == UPDATE:
        return [python, str(TOOLS / "update.py")]
    if key == EXPORT:
        return [python, str(TOOLS / "export_report.py")]
    cmd = [python, str(TOOLS / items[key][0])]
    if key == FIRST_RUN and opts.get("skip") is True:      # “已经弄好了，不再显示”：只记一笔，什么都不做
        cmd.append("--skip")
    if key == "18":
        text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fffα（）()=＝:：×,，、;；· ]", "", str(opts.get("targets", "")))[:300].strip()
        if text:
            cmd += ["--targets", text]
        try:
            if "max_runs" in opts:
                cmd += ["--max-runs", str(max(1, min(50, int(opts["max_runs"]))))]
        except (TypeError, ValueError):
            pass
        if opts.get("spend") is True:           # 只有明确勾了才带：不带的话那个脚本只说明、不动手
            cmd.append("--spend")
        if opts.get("fresh") is True:
            cmd.append("--fresh")
        if isinstance(opts.get("report"), bool):
            cmd.append("--report" if opts["report"] else "--no-report")
    if key in ("15", "18") and str(opts.get("guild") or "") in guild_choices(key == "18"):      # 只认下拉里有的
        cmd += ["--guild", str(opts["guild"])]
    if key in ("15", "18") and "tier" in opts:
        try:
            cmd += ["--tier", str(max(1, min(4, int(opts["tier"]))))]
        except (TypeError, ValueError):
            pass
    if key == "15":
        if opts.get("resume") is True:          # 只有明确勾了才带：不带的话，游戏里有进行中的一局就停下、不动它
            cmd.append("--resume")
        if opts.get("spend") is True:           # 只有明确勾了「使用门票」才带：不带的话走到最终首领跟前就停，不用门票、只打一局
            cmd.append("--spend")
            if "laps" in opts:
                try:
                    cmd += ["--laps", str(max(1, min(50, int(opts["laps"]))))]
                except (TypeError, ValueError):
                    pass
            try:
                settle = max(0, min(999999, int(opts.get("settle") or 0)))
            except (TypeError, ValueError):
                settle = 0
            if settle > 0:
                cmd += ["--settle", str(settle)]
        for name, flag in (("start_at", "--start-at"), ("stop_at", "--stop-at")):
            if re.fullmatch(r"\d{1,2}:\d{2}", str(opts.get(name) or "")):
                cmd += [flag, str(opts[name])]
        for name, flag in (("boss_want", "--boss-want"), ("boss_avoid", "--boss-avoid")):
            text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff（）()＆&·,，、 ]", "", str(opts.get(name) or ""))[:120].strip()
            if text and str(opts.get("tier")) == "1":
                cmd += [flag, text]
        if str(opts.get("tier")) == "1":            # 第一档本来就带这条规矩：不勾 = 明着关掉
            if opts.get("shop2") is False:
                cmd.append("--no-shop-reroll")
        elif opts.get("shop2") is True:             # 别的档位：勾了才带
            cmd.append("--shop-reroll")
        if opts.get("marks1") is True:
            cmd.append("--marks-reroll")
        if opts.get("boss3") is True:
            cmd.append("--boss3-single")
        if opts.get("ex4") is True:
            cmd.append("--ex4-reroll")
        for name in ("report", "recover"):      # 这几个开关在设置里默认是关的：勾了、没勾都明着告诉脚本，界面上是什么就是什么
            if isinstance(opts.get(name), bool):
                cmd.append(("--" if opts[name] else "--no-") + name)
    if key in ("15", "18") and isinstance(opts.get("equip"), bool):
        cmd.append("--equip" if opts["equip"] else "--no-equip")
    if key in ("15", "18"):                     # 单步模式删了：一律自己走（脚本现在不写也是这样，留着这个词是为了老的命令行还能用）
        cmd.append("--auto")
    return cmd


_STAMP = re.compile(r"^\s*\[\d\d:\d\d:\d\d\]\s*")
# 从功能脚本打印的字里认几样东西，显示成状态行下面那排小标签
_FACTS = (("updated", re.compile(r"^更新好了：.*→\s*V?([\d.]+)")), ("reset", re.compile(r"^(重置好了)")), ("tier", re.compile(r"^档位：(.+?)——")), ("laps", re.compile(r"这次连续打 (\d+) 局")), ("lap", re.compile(r"^—— 第 (\d+) 局")),
          ("restarts", re.compile(r"^—— 重开第 (\d+) 次")), ("area", re.compile(r"区域 (\d) 一共 \d+ 列")),
          ("score", re.compile(r"(最终分数是 [\d,]+|续打估分下限是 [\d,]+|结算实得 [\d,]+ 分|结算分未能核实)")))


def settings_walk(root: Path) -> dict[str, Any]:
    """config/settings.json 里 walk 那一段（读不了就当没有）：界面上档位、局数、两个开关的默认值跟着它。"""
    try:
        d = json.loads((Path(root) / "config" / "settings.json").read_text(encoding="utf-8-sig"))
        return d.get("walk") if isinstance(d.get("walk"), dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def guild_choices(farm: bool = False) -> list[str]:
    """界面上「公会」下拉里的选项：十个公会，前面加一个让工具自己挑的（打通一局是「刷分」，按饰品刷是「自动」）。"""
    try:
        sys.path.insert(0, str(ROOT)) if str(ROOT) not in sys.path else None
        from longniang_pcr import guilds as GD

        return [GD.AUTO if farm else GD.SCORE] + list(GD.NAMES)
    except Exception:  # noqa: BLE001
        return []


def default_guild(root: Path) -> str:
    """没选过的时候下拉里停在哪：设置里写了 walk.guild 就是它；没写返回空串——那就停在第一个（「刷分」/「自动」）。"""
    return str(settings_walk(root).get("guild") or "")


MAX_RUNS_SHOWN = 2000     # 「运行记录」最多列这么多次（新的在前）。记录本身都在 logs/runs 里，不会因为这个数少掉


def run_records(root: Path) -> list[dict[str, str]]:
    """所有运行过的记录，新的在前：logs/runs 里每个有 summary.txt 的文件夹一条。
    when = 什么时候开始的；head = 一句话（怎么结束的）；text = 那次的小结全文。"""
    try:
        dirs = sorted((d for d in (Path(root) / "logs" / "runs").iterdir() if (d / "summary.txt").is_file()), key=lambda d: d.name, reverse=True)
    except OSError:
        return []
    out = []
    for d in dirs[:MAX_RUNS_SHOWN]:
        try:
            text = (d / "summary.txt").read_text(encoding="utf-8")[:3000].strip()
        except OSError:
            continue
        m = re.match(r"(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)", d.name)
        when = f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}" if m else d.name
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        head = next((ln.split("：", 1)[1] for ln in lines if ln.startswith("怎么结束的：")), lines[0] if lines else "")
        out.append({"name": d.name, "when": when, "head": head[:60], "text": text})
    return out


def stats(root: Path) -> dict[str, Any]:
    """统计面板：各公会的成绩、运行记录——只有这两样（2026-11-25 用户定的）。
    饰品和战利品的账、输出角色的比重、真机上打赢过的队，工具自己照样记、照样用，只是不往界面上放。读不了的那一块就空着。"""
    out: dict[str, Any] = {"guilds": [], "runs": run_records(root)}
    try:
        sys.path.insert(0, str(ROOT)) if str(ROOT) not in sys.path else None
        from longniang_pcr import guilds as GD

        out["guilds"] = GD.GuildBook(Path(root) / "data" / "learned" / "guilds.json").table()
    except Exception:  # noqa: BLE001
        pass
    return out


def accessory_catalog() -> dict[str, Any]:
    """界面上「按分类选」和「饰品一览」用的目录（十个公会各出哪个系列）。"""
    try:
        sys.path.insert(0, str(ROOT)) if str(ROOT) not in sys.path else None
        from longniang_pcr import accessories as AC

        return {"elements": list(AC.ELEMENTS), "slots": list(AC.SLOTS), "series": AC.catalog()}
    except Exception:  # noqa: BLE001
        return {"elements": [], "slots": [], "series": []}


def tier_cards() -> list[dict[str, Any]]:
    try:
        sys.path.insert(0, str(ROOT)) if str(ROOT) not in sys.path else None
        from longniang_pcr import tiers as TR

        return [{"n": t.n, "short": t.name.split("·")[-1], "name": t.name, "blurb": t.blurb} for t in TR.TIERS.values()]
    except Exception:  # noqa: BLE001
        return []
_WHY = ("停下了", "已停止", "× ", "×", "！", "! ")


def child_python(python: str = sys.executable) -> str:
    """功能脚本用带控制台的 python.exe 来跑（不显示窗口）：界面自己是 pythonw 时，旁边那个 python.exe 才是对的。"""
    p = Path(python)
    if p.name.lower() == "pythonw.exe" and p.with_name("python.exe").exists():
        return str(p.with_name("python.exe"))
    return python


class Job:
    def __init__(self, name: str, key: str, proc: subprocess.Popen, stop_file: Path):
        self.name, self.key, self.proc, self.stop_file = name, key, proc, stop_file
        self.started = time.time()
        self.ended: float | None = None
        self.stop_asked: float | None = None


class Launcher:
    """启动、盯着、停止各项功能的脚本；把它们打印的字收起来给界面看。一次只跑一项。"""

    def __init__(self, items: dict[str, tuple], extra: dict[str, tuple], release: bool = False, root: Path = ROOT,
                 python: str = ""):
        self.items, self.extra, self.release, self.root, self.python = items, extra, release, Path(root), python or child_python()
        self.lock = threading.Lock()
        self.lines: list[str] = []
        self.base = 0                       # lines[0] 是第几行（旧的行会丢掉）
        self.tail = ""                      # 还没换行的那半行（工具在提问时，问题就停在这里）
        self.tail_t = 0.0                   # 那半行是什么时候开始停在那的（停了一会儿不动 = 在等你回答）
        self.job: Job | None = None
        self.last = ""                      # 上一项是怎么结束的
        self.doing = ""                     # 最近打印的一行（界面最上面那一行显示的就是它）
        self.why = ""                       # 这一项里“停下了 / 已停止 / 出错”的那一行（结束以后显示）
        self.restart = 0.0                  # 「检查更新」换上了新版本的时刻（0 = 没有）：界面该重新打开了
        self.facts: dict[str, Any] = {}     # 这一项跑到哪了：档位、第几局、区域、输赢、重开几次、估分（界面上那排小标签）
        self.prefs_path = lock_path().parent / "gui_prefs.json"     # 上次在界面上选的档位、局数、开关：下次打开还是它

    # ---- 输出 ----
    def _add(self, text: str) -> None:
        with self.lock:
            parts = (self.tail + text).replace("\r\n", "\n").replace("\r", "\n").split("\n")
            tail = parts.pop()
            if tail != self.tail:
                self.tail, self.tail_t = tail, time.time()
            self.lines.extend(parts)
            for ln in parts:
                t = _STAMP.sub("", ln).strip()
                for name, rx in _FACTS:
                    m = rx.search(t)
                    if m:
                        self.facts[name] = m.group(1)
                        if name in ("lap", "restarts"):
                            self.facts.pop("score", None)
                if "…打赢了" in t:
                    self.facts["wins"] = int(self.facts.get("wins", 0)) + 1
                elif "…打输了" in t:
                    self.facts["losses"] = int(self.facts.get("losses", 0)) + 1
                elif "我自己走回迷宫" in t:
                    self.facts["recovers"] = int(self.facts.get("recovers", 0)) + 1
                if "请你在模拟器里手动点过去" in t:          # 有个画面认不出来，在等你动手：界面上亮出来
                    self.facts["hand"] = 1
                elif self.facts.get("hand") and (t.startswith("认出来了") or t.startswith(_WHY)):
                    self.facts.pop("hand", None)
                if "laps" in self.facts and "lap" not in self.facts:
                    self.facts["lap"] = "1"
                if not t or not re.search(r"[0-9A-Za-z\u4e00-\u9fff]", t) or t.startswith(("——", "====")):
                    continue
                self.doing = t
                if t.startswith(_WHY):
                    self.why = t
            if len(self.lines) > MAX_LINES:
                cut = len(self.lines) - MAX_LINES
                del self.lines[:cut]
                self.base += cut

    def note(self, text: str) -> None:
        self._add(("\n" if self.tail else "") + text + "\n")

    def _pump(self, job: Job) -> None:
        dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
        fd = job.proc.stdout.fileno()
        while True:
            try:
                data = os.read(fd, 4096)
            except OSError:
                break
            if not data:
                break
            self._add(dec.decode(data))
        code = job.proc.wait()
        job.ended = time.time()
        try:
            job.stop_file.unlink(missing_ok=True)
        except OSError:
            pass
        mins = (job.ended - job.started) / 60
        self.last = f"「{job.name}」结束了（{'正常' if code == 0 else '代码 ' + str(code)}，用时 {mins:.1f} 分钟）"
        self.note(f"—— {self.last} ——")
        if code == 0 and ((job.key == UPDATE and self.facts.get("updated")) or (job.key == RESET and self.facts.get("reset"))):
            # 换上了新版本 / 重置好了：界面要重新打开才是新的
            self.restart = time.time()

    # ---- 启动 / 输入 / 停止 ----
    def running(self) -> bool:
        return self.job is not None and self.job.proc.poll() is None

    def start_cmd(self, name: str, cmd: list[str], key: str = "") -> tuple[bool, str]:
        if self.running():
            return False, f"「{self.job.name}」还在运行，先等它结束或者点停止"
        rt = Path(os.environ.get("LNPCR_RUNTIME") or self.root)
        stop_file = rt / f"stop_{os.getpid()}_{int(time.time() * 1000)}.flag"
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
                   LNPCR_STOP_FILE=str(stop_file), LNPCR_GUI="1")
        try:
            proc = subprocess.Popen(cmd, cwd=str(self.root), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, bufsize=0,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))      # 不弹黑窗口；它再启动的 adb 之类也跟着不弹
        except OSError as e:
            return False, f"没能启动：{e}"
        self.note(f"\n==================== {name} ====================")
        self.doing, self.why, self.facts = "正在启动……", "", {}
        self.job = Job(name, key, proc, stop_file)
        threading.Thread(target=self._pump, args=(self.job,), name="gui-pump", daemon=True).start()
        return True, ""

    def start(self, key: str, opts: dict[str, Any] | None = None) -> tuple[bool, str]:
        if key not in self.items and key not in self.extra:
            return False, "没有这一项"
        tag = self.items[key][2] if key in self.items else self.extra[key][1]
        if self.release and tag != "正式":
            return False, "正式版里没有这一项"
        name = (self.items[key][1] if key in self.items else self.extra[key][0]).split("：")[0].split("（")[0]
        if opts and key in OPTIONS:
            self.save_prefs(key, opts)
        return self.start_cmd(name, build_cmd(key, self.items, opts or {}, self.python), key)

    # ---- 上次选的 ----
    def load_prefs(self) -> dict[str, dict[str, Any]]:
        try:
            d = json.loads(self.prefs_path.read_text(encoding="utf-8"))
            if not isinstance(d, dict) or d.get("_v") != PREFS_V:      # 默认值改过以前记下的：不算了，一切回到新的默认
                return {}
            return {k: v for k, v in d.items() if isinstance(v, dict)}
        except Exception:  # noqa: BLE001
            return {}

    def save_prefs(self, key: str, opts: dict[str, Any]) -> None:
        known = {n for n, _k, _v, _l in OPTIONS.get(key, [])}
        d = self.load_prefs()
        d[key] = {k: (v[:200] if isinstance(v, str) else v) for k, v in opts.items()
                  if k in known and k not in NEVER_REMEMBER and isinstance(v, (bool, int, float, str))}
        if "tier" in d[key]:                # 档位两项共用：一处改了另一处也跟着
            for other in ("15", "18"):
                d.setdefault(other, {})["tier"] = d[key]["tier"]
        try:
            self.prefs_path.parent.mkdir(parents=True, exist_ok=True)
            self.prefs_path.write_text(json.dumps(dict(d, _v=PREFS_V), ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def option_values(self, key: str) -> list[dict[str, Any]]:
        """这一项的小选项和它们现在的默认值：代码里的默认 ← config/settings.json ← 上次在界面上选的。"""
        walk, prefs = settings_walk(self.root), self.load_prefs().get(key, {})
        out = []
        for n, kd, v, lb in OPTIONS.get(key, []):
            for opt, cfg_key in FROM_SETTINGS:
                if opt == n and key in ("15", "18") and isinstance(walk.get(cfg_key), type(v)):
                    v = walk[cfg_key]
            if isinstance(prefs.get(n), type(v)) and n not in NEVER_REMEMBER:
                v = prefs[n]
            row = {"name": n, "kind": kd, "value": v, "label": lb}
            if kd == "select":
                row["choices"] = guild_choices(key == "18")
                if key == "18" and not isinstance(prefs.get(n), str) and row["choices"]:
                    row["value"] = row["choices"][0]                 # 按饰品刷：没选过就停在「自动」（哪个公会出哪种饰品目录里写着）
                if row["value"] not in row["choices"]:
                    row["value"] = default_guild(self.root) if default_guild(self.root) in row["choices"] else (row["choices"][0] if row["choices"] else "")
            out.append(row)
        return out

    def send(self, text: str) -> tuple[bool, str]:
        if not self.running():
            return False, "现在没有在运行的功能"
        try:
            self.job.proc.stdin.write((text + "\n").encode("utf-8"))
            self.job.proc.stdin.flush()
        except OSError as e:
            return False, f"没送进去：{e}"
        self._add(text + "\n")              # 把你输入的也显示出来（接在问题后面）
        return True, ""

    def stop(self, force: bool = False) -> tuple[bool, str]:
        if not self.running():
            return False, "现在没有在运行的功能"
        job = self.job
        if force:
            job.proc.kill()
            self.note("—— 已强制结束。如果刚才正在点游戏，回游戏里看一眼画面 ——")
            return True, ""
        try:
            job.stop_file.write_text("stop", encoding="utf-8")
        except OSError as e:
            return False, f"停止信号没发出去：{e}"
        job.stop_asked = time.time()
        self.note("—— 已经让它停下（会在下一个动作之前停）。几秒钟还没停的话，可以点「强制结束」 ——")
        return True, ""

    def open_folder(self, what: str) -> tuple[bool, str]:
        if what == "official":                   # 用默认浏览器打开国服官号的页面
            try:
                import webbrowser

                return (True, "") if webbrowser.open(OFFICIAL_URL) else (False, f"浏览器没打开，地址是：{OFFICIAL_URL}")
            except Exception as e:  # noqa: BLE001
                return False, f"浏览器没打开（{e}），地址是：{OFFICIAL_URL}"
        p = {"logs": self.root / "logs", "recordings": self.root / "recordings", "project": self.root}.get(what)
        if p is None:
            return False, "没有这个文件夹"
        p.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(p))            # noqa: S606  只在 Windows 上有
        except AttributeError:
            return False, f"文件夹在：{p}"
        except OSError as e:
            return False, f"打不开文件夹：{e}（路径是 {p}）"
        return True, ""

    def state(self, since: int = 0) -> dict[str, Any]:
        with self.lock:
            start = max(since, self.base)
            lines = self.lines[start - self.base:]
            total, tail = self.base + len(self.lines), self.tail
        job = self.job
        run = self.running()
        asking = bool(run and tail.strip() and time.time() - self.tail_t > 0.5)        # 没换行的半行停住不动了：工具在等你回答
        return {"lines": lines, "from": start, "next": total, "tail": tail, "running": run, "facts": dict(self.facts),
                "doing": (tail.strip() if asking else self.doing) if run else "", "asking": asking, "why": "" if run else self.why,
                "name": job.name if job and run else "", "key": job.key if job and run else "",
                "seconds": round(time.time() - job.started) if job and run else 0,
                "stop_asked": bool(job and run and job.stop_asked), "last": self.last, "restart": bool(self.restart)}

    def menu(self) -> list[dict[str, Any]]:
        out = []
        for title, keys in GROUPS:
            rows = []
            for k in keys:
                text, tag = (self.items[k][1], self.items[k][2]) if k in self.items else self.extra[k]
                if self.release and tag != "正式":
                    continue
                head, _, rest = text.partition("：")
                if not rest and "（" in head:                 # 没有冒号的：括号里的话当说明，按钮上只留名字
                    head, _, rest = head.partition("（")
                    rest = rest[:-1] if rest.endswith("）") else rest
                rows.append({"key": k, "title": head, "desc": rest, "tag": tag,
                             "opts": self.option_values(k)})
            if rows:
                out.append({"title": title, "items": rows})
        return out


PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>龙娘pcr</title>
<style>
:root{--ink:#27365f;--ink2:#5b6a8c;--line:#d6deee;--bg:#eef3fb;--card:#fff;--blue:#3d6fd1;--blue2:#2f58ad;--gold:#d9a441;--gold2:#f6e7c1;--lav:#efeaff;--ok:#2e9e5b;--warn:#d9822b;--bad:#c0392b}
*{box-sizing:border-box}
body{margin:0;font-family:"Microsoft YaHei UI","Microsoft YaHei",system-ui,sans-serif;font-size:14px;color:var(--ink);background:var(--bg);height:100vh;display:flex;flex-direction:column}
header{padding:8px 18px;background:linear-gradient(100deg,#dfe9fb 0%,#ece6fb 55%,#fbf1dc 100%);border-bottom:1px solid var(--line);display:flex;align-items:center;gap:14px}
header img{height:60px;width:60px;flex:none;filter:drop-shadow(0 2px 3px rgba(60,80,140,.25))}
header .ttl{flex:1;min-width:0}
header b{font-size:20px;letter-spacing:1px;color:#2c3f7c}
header .sub{display:block;font-size:12px;color:var(--ink2);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
header button{background:rgba(255,255,255,.7);color:var(--ink);border:1px solid #c5cfe6;border-radius:16px;padding:5px 14px;cursor:pointer;font-size:13px}
header button:hover{background:#fff;border-color:var(--blue)}
#status{margin:12px 14px 0;padding:10px 14px;border-radius:12px;background:var(--card);border:1px solid var(--line);display:flex;align-items:center;gap:10px;min-height:50px;box-shadow:0 1px 2px rgba(40,60,120,.05)}
#status.run{background:#fff8e8;border-color:#edc878}#status.ask{background:#e9f2ff;border-color:#7fb0ee}#status.bad{background:#fdeeee;border-color:#e3a1a1}
#dot{flex:none;width:10px;height:10px;border-radius:50%;background:#a9b5cc}
#status.run #dot{background:#e39a1c;animation:blink 1.1s infinite}#status.ask #dot{background:#2b7de0}#status.bad #dot{background:var(--bad)}
@keyframes blink{50%{opacity:.25}}
#what{flex:none;font-weight:600;white-space:nowrap}
#doing{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:15px}
#status button{flex:none;padding:5px 14px;border-radius:8px;border:1px solid #b8c4dc;background:#fff;cursor:pointer;color:var(--ink)}
#status button.stop{border-color:var(--bad);background:var(--bad);color:#fff}#status button.force{background:#7b241c;border-color:#7b241c;color:#fff}
#chips{margin:8px 14px 0;display:none;gap:6px;flex-wrap:wrap}
#chips.on{display:flex}
.chip{font-size:12px;padding:3px 10px;border-radius:12px;background:#fff;border:1px solid var(--line);color:var(--ink2)}
.chips{display:flex;flex-wrap:wrap;gap:6px}.farmpick{margin-top:8px;padding-top:8px;border-top:1px dashed var(--line)}
.chip b{color:var(--ink);font-weight:600}.chip.gold{background:var(--gold2);border-color:#e6cf93}
#ask{margin:8px 14px 0;display:none;gap:6px;align-items:center}
#ask.on{display:flex}
#ask input{flex:1;padding:7px 10px;border:1px solid #b8c4dc;border-radius:8px;font-size:14px}
#ask button{padding:6px 10px;border-radius:8px;border:1px solid #b8c4dc;background:#fff;cursor:pointer}
main{flex:1;display:flex;min-height:0;padding:12px 14px;gap:12px}
#left{flex:1;min-width:0;overflow:auto;padding-right:2px}
body.detail #left{flex:none;width:440px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:12px;box-shadow:0 1px 2px rgba(40,60,120,.05)}
.card h2{margin:0;font-size:16px;color:#2c3f7c;display:flex;align-items:baseline;gap:10px}
.card h2 small{font-size:12px;font-weight:400;color:var(--ink2)}
.tag{flex:none;font-size:11px;padding:1px 7px;border-radius:10px;color:#fff;font-weight:400}
.t正式{background:var(--ok)}.t测试{background:var(--warn)}.t一次性{background:#7a8794}
#hero{background:linear-gradient(180deg,#fff 0%,#f7f9ff 100%)}
#first{background:linear-gradient(180deg,#fffaf0,#fff);border-color:#e6cf93}
#newver{background:#eef6ff;border-color:#7fb0ee;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
#newver span{flex:1;min-width:150px;font-size:13px}
#tiers{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px}
body.detail #tiers{grid-template-columns:repeat(2,1fr)}
.tier{border:1.5px solid var(--line);border-radius:10px;padding:8px 10px;cursor:pointer;background:#fff;transition:border-color .12s,box-shadow .12s;position:relative}
.tier:hover{border-color:#9db4e6}
.tier.on{border-color:var(--gold);box-shadow:0 0 0 3px rgba(217,164,65,.18);background:linear-gradient(180deg,#fffdf6,#fff)}
.tier .n{font-size:11px;color:var(--ink2)}.tier .nm{font-weight:600;font-size:14px;margin:1px 0 4px}
.tier .bl{font-size:12px;color:var(--ink2);line-height:1.45}
.tier.on .n::after{content:"  ✓ 现在用这一档";color:#b07d14}
.optrow{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin-top:12px;font-size:13px}
.optrow input[type=number]{width:56px;padding:3px 5px;border:1px solid #b8c4dc;border-radius:6px}
.optrow label{display:inline-flex;align-items:center;gap:5px;cursor:pointer}
.gorow{display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap}
button.primary{padding:9px 26px;border-radius:10px;border:none;background:linear-gradient(180deg,var(--blue),var(--blue2));color:#fff;font-size:16px;font-weight:600;cursor:pointer;box-shadow:0 2px 6px rgba(61,111,209,.35)}
button.primary:hover{filter:brightness(1.06)}
button.ghost{padding:8px 16px;border-radius:10px;border:1px solid #9db4e6;background:#fff;color:var(--blue2);font-size:14px;cursor:pointer}
button.primary:disabled,button.ghost:disabled,.item button:disabled{background:#c3cce0;border-color:#c3cce0;color:#fff;cursor:not-allowed;box-shadow:none}
.note{font-size:12px;color:var(--ink2);line-height:1.6;margin-top:8px}
#grid,.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:8px 10px;align-items:start;margin-top:10px}
.grid.one{grid-template-columns:1fr}.grid.one .item{border:none;background:none;padding:0}.grid.one .opts{font-size:13px;gap:14px;margin-top:10px}
h3{margin:12px 0 2px;font-size:12px;color:var(--ink2);font-weight:600;grid-column:1/-1}
.item{background:#fbfcff;border:1px solid var(--line);border-radius:10px;padding:8px 10px}
.row{display:flex;align-items:center;gap:8px}
.item button{flex:none;min-width:112px;padding:6px 10px;border-radius:8px;border:1px solid var(--blue2);background:var(--blue2);color:#fff;cursor:pointer;font-size:13px}
.desc{font-size:12px;color:var(--ink2);margin-top:5px;line-height:1.5}
.opts{font-size:12px;margin-top:6px;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.opts input[type=number]{width:56px;padding:2px 4px}
details.card>summary{cursor:pointer;font-size:14px;font-weight:600;color:#2c3f7c;list-style:none}
details.card>summary::before{content:"▸ ";color:var(--ink2)}details.card[open]>summary::before{content:"▾ "}
details.card>summary small{font-weight:400;color:var(--ink2);font-size:12px;margin-left:6px}
#right{flex:1;min-width:0;display:none;flex-direction:column}
body.detail #right{display:flex}
#log{flex:1;min-height:0;overflow:auto;background:#141b2b;color:#d7e0f0;border-radius:12px;padding:12px 14px;font-family:Consolas,"Microsoft YaHei UI",monospace;font-size:13px;line-height:1.55;white-space:pre-wrap;word-break:break-all}
#log .tail{color:#ffd479}
table.st{border-collapse:collapse;margin:4px 0 10px;font-size:12px}table.st th,table.st td{border-bottom:1px solid var(--line);padding:3px 12px 3px 0;text-align:left}
table.st th{color:var(--ink2);font-weight:600}h4{margin:10px 0 2px;font-size:13px;color:var(--ink)}
.hint{font-size:12px;color:var(--ink2);padding:0 16px 8px}
/* 2026-11-24 晚：整体缩小一号（用户要的）。下面这些盖掉上面的尺寸 */
body{font-size:13px}
header{padding:5px 12px;gap:10px}header img{height:36px;width:36px}header b{font-size:16px}
header .sub{font-size:11px;margin-top:1px}header button{padding:3px 10px;font-size:12px;border-radius:12px}
#status{margin:8px 10px 0;padding:5px 10px;min-height:34px;border-radius:9px;gap:8px}
#doing{font-size:13px}#status button{padding:3px 10px;font-size:12px;border-radius:7px}
#chips{margin:6px 10px 0}.chip{font-size:11px;padding:2px 8px}
main{padding:8px 10px;gap:8px}body.detail #left{width:400px}
.card{padding:9px 12px;margin-bottom:8px;border-radius:10px}.card h2{font-size:14px}.card h2 small{font-size:11px}
#tiers{gap:6px;margin-top:8px}.tier{padding:5px 8px;border-radius:8px}
.tier .n{font-size:10px}.tier .nm{font-size:13px;margin:0 0 2px}.tier .bl{font-size:11px;line-height:1.4}
.optrow{gap:8px 14px;margin-top:8px;font-size:12px}.optrow input[type=number]{width:50px;padding:2px 4px}
.optrow input.wide{width:76px}
.gorow{margin-top:10px;gap:8px}
button.primary{padding:6px 22px;font-size:14px;border-radius:8px}button.ghost{padding:5px 12px;font-size:12px;border-radius:8px}
.note{font-size:11px;line-height:1.55;margin-top:6px}
#grid,.grid{grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:6px 8px;margin-top:8px}
.grid.one .opts{font-size:12px;gap:10px;margin-top:8px}
.item{padding:6px 8px;border-radius:8px}.item button{min-width:92px;padding:4px 8px;font-size:12px;border-radius:7px}
.desc{font-size:11px;margin-top:4px;line-height:1.45}.opts{font-size:11px;gap:10px}
details.card>summary{font-size:13px}details.card>summary small{font-size:11px}
#log{font-size:12px;line-height:1.5;padding:8px 10px;border-radius:9px}
.hint{font-size:11px;padding:0 12px 6px}table.st{font-size:11px}h4{font-size:12px}
details.adv{margin-top:6px;font-size:12px}details.adv>summary{cursor:pointer;color:var(--ink2);list-style:none}
details.adv>summary::before{content:"▸ "}details.adv[open]>summary::before{content:"▾ "}
details.adv .optrow{margin-top:6px}
.spend{font-weight:700}
.opts label{display:inline-flex;align-items:center;gap:5px;cursor:pointer}
/* 2026-11-24 深夜：改成“小工具”那种小窗口（用户要的）：一栏、窄、常用的摆外面，别的收起来；看输出时整块换成输出 */
body{font-size:12px}
header{padding:4px 8px;gap:8px}header img{height:26px;width:26px}header b{font-size:14px;letter-spacing:0}
header .sub{display:none}header button{padding:2px 8px;font-size:11px;border-radius:10px}
#status{margin:6px 8px 0;padding:4px 8px;min-height:30px;gap:6px}#what{font-size:12px}#doing{font-size:12px}
#status button{padding:2px 8px;font-size:11px}
#chips{margin:4px 8px 0;gap:4px}.chip{font-size:10px;padding:1px 6px}
main{padding:6px 8px;gap:6px}
body.detail #left{display:none}#right{flex:1}
.card{padding:8px 10px;margin-bottom:6px;border-radius:9px}.card h2{font-size:13px;gap:6px}
#tiers,body.detail #tiers{display:flex;gap:4px;margin-top:6px}
.tier{flex:1;padding:4px 2px;text-align:center;border-radius:7px;border-width:1px}
.tier .n,.tier .bl{display:none}.tier .nm{font-size:12px;margin:0;font-weight:500}.tier.on .nm{font-weight:700}
.tier.on{box-shadow:0 0 0 2px rgba(217,164,65,.22)}
#tierbl{font-size:11px;color:var(--ink2);margin-top:5px;line-height:1.45;min-height:32px}
.optrow{gap:6px 12px;margin-top:6px;font-size:12px}.optrow input[type=number]{width:44px}.optrow input.wide{width:70px}
.optrow select{max-width:130px}
.gorow{margin-top:8px;gap:6px}
button.primary{padding:5px 18px;font-size:13px;border-radius:7px}button.ghost{padding:4px 10px;font-size:12px;border-radius:7px}
.note{font-size:11px;line-height:1.5;margin-top:5px}
#grid,.grid{grid-template-columns:1fr;gap:6px;margin-top:6px}
.grid.one .opts{font-size:12px;gap:6px 10px;margin-top:6px}
.item button{min-width:0;padding:4px 12px}
.desc{font-size:11px;margin-top:3px}
.hint{display:none}
details.card>summary{font-size:13px}details.card>summary small{font-size:10px}
details.adv{margin-top:5px;font-size:11px}
#log{font-size:11px;line-height:1.5;padding:6px 8px;border-radius:8px}
#ask{margin:4px 8px 0;padding:6px 10px}#askq{font-size:12px}
.rolerow{display:flex;align-items:center;gap:8px}.rolerow .desc{margin:0;flex:1}.rolerow button{flex:none;width:104px;padding:4px 0 !important;font-size:12px}
/* 2026-11-25：窗口再小一号（380×430）。一打开看到的就是状态 + 黎明界迷宫那一栏，其余的往下滚 */
header{padding:3px 6px;gap:6px}header img{height:22px;width:22px}header b{font-size:13px}header button{padding:1px 7px}
#status{margin:4px 6px 0;padding:3px 7px;min-height:26px}
#chips{margin:3px 6px 0}#ask{margin:3px 6px 0}
main{padding:4px 6px}
.card{padding:6px 8px;margin-bottom:5px}.card h2{font-size:12px}
#tiers,body.detail #tiers{margin-top:4px;gap:3px}.tier{padding:3px 1px}.tier .nm{font-size:11px}
#tierbl{margin-top:3px;min-height:2.8em;font-size:10.5px;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.optrow{gap:4px 10px;margin-top:5px;font-size:11.5px}.optrow select{max-width:118px;font-size:11.5px !important;padding:2px 4px !important}
.optrow input[type=number]{width:40px;padding:1px 3px}.optrow input.wide{width:64px}
.gorow{margin-top:6px}button.primary{padding:4px 16px;font-size:12.5px}button.ghost{padding:3px 9px;font-size:11.5px}
details.adv{margin-top:3px;font-size:10.5px}
details.runs{margin:2px 0 8px}details.runs>summary{cursor:pointer;font-size:12px}
.runlist{max-height:240px;overflow:auto;margin-top:4px;border:1px solid var(--line);border-radius:6px;padding:2px 6px;background:#fafcff}
.runlist details{border-bottom:1px dashed var(--line);padding:2px 0}.runlist details:last-child{border-bottom:0}
.runlist summary{cursor:pointer;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.runlist pre{margin:2px 0 4px;font-family:inherit;font-size:11px;white-space:pre-wrap;line-height:1.5}
.gofold{display:flex;flex-wrap:wrap;align-items:center;gap:3px 14px}.gofold details.adv{margin-top:0}
.gofold details.adv[open]{flex:1 0 100%;order:2}
#foot{flex:none;text-align:center;padding:1px 8px 4px;line-height:1.3}
#qq{font-size:11px;color:var(--ink2);user-select:text;cursor:text;white-space:nowrap}
/* 2026-11-25 用户截图：点开「按饰品数量连续刷」往下滚以后，上面那一栏的旧画面还留在原地、盖在新内容上（Edge 滚动后没重画干净，
   是浏览器画面的毛病，不是排版）。常用的治法：让会滚的这一块有自己不透明的底色、单独成一层——滚动时整层挪，不用一块一块重画 */
#left{background:var(--bg);will-change:scroll-position;isolation:isolate;scrollbar-gutter:stable;margin-right:-6px;padding-right:0}
/* 滚动条：细细的一条（6 像素），位置一直留着——正好是右边那 6 像素的边，所以出不出滚动条，各栏都不变宽窄、右边和上面的状态栏对齐 */
#left::-webkit-scrollbar{width:6px}#left::-webkit-scrollbar-track{background:transparent}
#left::-webkit-scrollbar-thumb{background:#b9c5dd;border-radius:3px}#left::-webkit-scrollbar-thumb:hover{background:#8fa0c4}
#more{margin-bottom:2px}
/* 页面里自己的提示框（2026-11-25 用户截图：浏览器自带的那种比小窗口还宽，字和「取消」被切掉，标题还写着“127.0.0.1:端口 显示”）：
   盖在窗口正中、比窗口窄一圈，内容多了在框里滚，两个按钮一直看得全 */
#dlg{position:fixed;inset:0;z-index:50;display:flex;align-items:center;justify-content:center;padding:10px;background:rgba(30,42,78,.42)}
#dlg[hidden]{display:none}
#dlgbox{box-sizing:border-box;width:100%;max-width:360px;max-height:100%;display:flex;flex-direction:column;background:#fff;border-radius:12px;padding:11px 14px 12px;box-shadow:0 10px 34px rgba(20,30,60,.34)}
#dlgttl{flex:none;font-size:13px;font-weight:700;color:var(--ink)}
#dlgmsg{flex:1 1 auto;min-height:0;overflow:auto;margin:6px 0 10px;font-size:12.5px;line-height:1.6;color:var(--ink);white-space:pre-wrap;overflow-wrap:anywhere}
#dlgbtn{flex:none;display:flex;justify-content:flex-end;gap:8px}
#dlgbtn button{min-width:64px;padding:4px 14px !important;font-size:12.5px !important;border-radius:7px}
/* 「按饰品数量连续刷」点开以后也照小窗口的大小来：字和框小一号，「部位 / 系列」那个下拉框别撑满一整行 */
.grid.one .opts select,.farmpick select{font-size:11.5px !important;padding:2px 4px !important;max-width:150px}
.grid.one .opts input[type=number],.farmpick input[type=number]{width:40px !important;padding:1px 3px;font-size:11.5px}
.farmpick{margin-top:6px;padding-top:6px}.farmpick .opts{margin-top:4px}
.farmpick button{padding:2px 9px !important;font-size:11.5px !important}
/* 工具问你问题的时候才出来的那一条：上面是问的话，下面是能选的答案（一个按钮一个答案），需要填字的才有输入框 */
#ask{margin:6px 10px 0;display:none;flex-direction:column;gap:6px;align-items:stretch;padding:8px 12px;border-radius:9px;background:#e9f2ff;border:1px solid #7fb0ee}
#ask.on{display:flex}
#askq{font-size:13px;font-weight:600;color:#1f3f7a;line-height:1.5;white-space:pre-wrap;word-break:break-all}
#askrow{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
#ask button{padding:4px 14px;border-radius:7px;border:1px solid #9db4e6;background:#fff;cursor:pointer;font-size:12px;color:var(--ink)}
#ask button.pri{background:var(--blue2);border-color:var(--blue2);color:#fff}
#ask input{flex:1;min-width:120px;padding:4px 8px;border:1px solid #b8c4dc;border-radius:7px;font-size:13px}
</style></head><body>
<header><img id="logo" alt="" onerror="this.style.display='none'"><div class="ttl"><b>龙娘pcr</b> <small style="color:var(--ink2);font-size:10px">V__VERSION__</small></div></header>
<div id="status"><span id="dot"></span><span id="what">空闲</span><span id="doing">选好档位，点「开始」</span>
 <button id="bstop" class="stop" style="display:none" onclick="stop(false)">停止</button>
 <button id="bforce" class="force" style="display:none" onclick="stop(true)">强制结束</button>
 <button id="bdetail" onclick="detail()" title="看这一项一步一步干了什么；再点一下回来">输出 ▸</button></div>
<div id="chips"></div>
<div id="ask"><div id="askq"></div><div id="askrow"><span id="askbtns"></span>
 <input id="inp" placeholder="在这里填你的回答，按回车" onkeydown="if(event.key==='Enter')send()"><button id="asksend" onclick="send()">确定</button></div></div>
<main><div id="left"><div id="newver" class="card" style="display:none"></div><div id="first" class="card" style="display:none"></div><div id="hero" class="card" style="display:none"></div><div id="cards"></div><details id="stats" class="card"><summary>统计<small id="statsn"></small></summary><div id="statsbody" class="note"></div></details><details id="more" class="card"><summary>其他</summary><div id="grid"></div></details></div><div id="right"><div id="log"></div></div></main>
<footer id="foot"><span id="qq" title="出了问题：在「其他」里点「导出排查包」，把生成的 zip 发到这个 QQ 群里，再说一下当时在做什么、哪里不对">QQ群 __QQ__</span></footer>
<div id="dlg" hidden><div id="dlgbox" role="dialog" aria-modal="true" aria-labelledby="dlgttl"><div id="dlgttl">龙娘pcr</div><div id="dlgmsg"></div>
 <div id="dlgbtn"><button id="dlgno" class="ghost" onclick="dlgClose(false)">取消</button><button id="dlgok" class="primary" onclick="dlgClose(true)">确定</button></div></div></div>
<div class="hint">关掉这个窗口工具就退出（正在跑的功能会先停下）。下次直接双击文件夹里的“龙娘pcr.exe”，没有黑窗口。运行记录和截图在 logs 文件夹里。</div>
<script>
const T = new URLSearchParams(location.search).get('t') || '';
// 打开的时候就是小窗口：Edge / Chrome 的应用窗口会照上次关掉时的大小打开，这里自己改回来（普通浏览器标签页改不了，那种不管）
const FIT_W = 426;
let FIT_H = 420, fitted = false;     // 高度先用估计的；页面排好以后 fitToContent() 量出准的
function fitWindow(){ try { if (Math.abs(window.outerWidth - FIT_W) > 24 || Math.abs(window.outerHeight - FIT_H) > (fitted ? 2 : 24)) window.resizeTo(FIT_W, FIT_H); } catch (e) {} }
// 窗口的高度（2026-11-25 定的）：下面几栏（下拉栏）都收着的时候，窗口正好装下所有内容——「其他」那一栏下面紧跟着最底下的 QQ 群号，
// 不用滚。上面多出东西（状态下面的小标签、工具问你问题的那一条、「首次设置」那一栏）窗口就跟着变高，没了再变回来。
// 有哪一栏点开着的时候不动（那时候内容多，可以滚）；都收起来以后再量。
// 各台电脑上字体、缩放不一样，所以不写死：页面自己量，量出来的告诉后台（它让 Windows 照着改），自己也改一次。
function fitToContent(){
  try {
    if (document.body.classList.contains('detail')) return;
    const left = $('left'), last = $('more');
    if (!left || !last || !last.offsetHeight) return;
    const shown = d => { for (let p = d.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS' && !p.open) return false; return true; };
    if ([...left.querySelectorAll('details[open]')].some(shown)) return;
    const css = (el, k) => parseFloat(getComputedStyle(el)[k] || 0) || 0;
    // 窗口里 #left（会滚的那一块）以外的东西一共多高（上面几行、四周的留白、最底下的 QQ 群号） + #left 里的内容一共多高
    const content = last.getBoundingClientRect().bottom - left.getBoundingClientRect().top + left.scrollTop + css(last, 'marginBottom');
    const inner = (window.innerHeight - left.clientHeight) + content;
    let h = Math.round(inner + Math.max(0, window.outerHeight - window.innerHeight));
    try { if (screen.availHeight > 400) h = Math.min(h, screen.availHeight); } catch (e) {}
    if (!(h >= 320 && h <= 900)) return;
    if (fitted && Math.abs(h - FIT_H) <= 1) return;
    FIT_H = h; fitted = true;
    document.documentElement.dataset.fitH = h + '=' + Math.round(inner) + '+' + (h - Math.round(inner));      // 留个记号（总高 = 页面 + 标题栏）：排查的时候看得到量出来是多少
    fitWindow();
    api('/api/fit', {h: h}).catch(() => {});
  } catch (e) {}
}
let fitSig = '';
function fitIfChanged(){             // 上面那几样（小标签、问你的那一条、首次设置）出现 / 消失 / 变高了：重新量一次
  const hh = id => { const e = $(id); return e ? e.offsetHeight : 0; };
  const sig = [hh('chips'), hh('ask'), hh('newver'), hh('first'), hh('hero'), hh('status')].join(',');
  if (sig !== fitSig){ fitSig = sig; setTimeout(fitToContent, 30); }
}
fitWindow(); window.addEventListener('load', () => setTimeout(fitWindow, 300));
const HERO = ['15'], MAIN_GROUPS = ['按饰品数量连续刷'];
let next = 0, running = false, menu = [], tiers = [], catalog = {}, gone = false, miss = 0, tier = 2, firstRun = false;
const $ = id => document.getElementById(id);
async function api(path, body){
  const r = await fetch(path + (path.includes('?') ? '&' : '?') + 't=' + encodeURIComponent(T), body === undefined ? {} :
    {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  return r.json();
}
function esc(s){return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
(() => { const u = '/logo.png?t=' + encodeURIComponent(T); $('logo').src = u; const l = document.createElement('link'); l.rel = 'icon'; l.type = 'image/png'; l.href = u; document.head.appendChild(l); })();
function find(key){ for (const g of menu) for (const it of g.items) if (it.key === key) return it; return null; }
function optHtml(it, o){
  const id = 'o_' + it.key + '_' + o.name;
  if (o.kind === 'tier') return '';
  if (o.name === 'targets') return '<input type="hidden" id="' + id + '" value="' + esc(o.value) + '">';      // 目标不直接写：在下面按分类加（farmHtml），这里只是存着
  if (o.kind === 'select') return '<label>' + esc(o.label) + ' <select id="' + id + '" style="padding:3px 6px;border:1px solid #b8c4dc;border-radius:6px;font-size:13px">' +
    (o.choices || []).map(c => '<option' + (c === o.value ? ' selected' : '') + '>' + esc(c) + '</option>').join('') + '</select></label>';
  if (o.kind === 'time') return '<label>' + esc(o.label) + ' <input type="time" id="' + id + '" value="' + esc(o.value) + '" style="padding:2px 5px;border:1px solid #b8c4dc;border-radius:6px"></label>';
  if (o.kind === 'text' && o.name.indexOf('boss_') === 0) return '<label class="t1only" style="flex:1 1 45%;display:none">' + esc(o.label) + ' <input type="text" id="' + id + '" value="' + esc(o.value) + '" placeholder="比如 巨型魔像、奇美拉" style="flex:1;min-width:150px;padding:3px 6px;border:1px solid #b8c4dc;border-radius:6px"></label>';
  if (o.kind === 'text') return '<label style="flex:1 1 100%">' + esc(o.label) + ' <input type="text" id="' + id + '" value="' + esc(o.value) + '"' + ' style="flex:1;min-width:180px;padding:3px 6px;border:1px solid #b8c4dc;border-radius:6px"></label>';
  // shop2（第二层绕不开商店就重开）原来只在第一档显示；2026-11-27 起哪一档都显示，和别的勾一样画
  return o.kind === 'check' ? '<label' + (o.name === 'spend' ? ' class="spend"' : '') + '><input type="checkbox" id="' + id + '"' + (o.value ? ' checked' : '') + '> ' + esc(o.label) + '</label>'
                            : '<label>' + esc(o.label) + ' <input type="number" id="' + id + '" value="' + esc(o.value) + '" min="0"' + (o.name === 'settle' ? ' class="wide" max="999999" step="100"' : ' max="' + (o.name === 'laps' || o.name === 'max_runs' ? 50 : 40) + '"') + '></label>';
}
const BRIEF = {       // 「其他」里的每一项：按钮右边一句话（细的写在鼠标停上去的提示里）
  '16': '抽到新角色后按一下（游戏先停在「角色」页）',
  '6': '出了问题点这个，把生成的 zip 发到 QQ 群',
  '5': '去 GitHub 看有没有新版本，有就换上',
  '8': '变回刚下载时的样子，首次设置重来',
};
function itemHtml(it){
  if (BRIEF[it.key]) return '<div class="item"><div class="rolerow"><button data-key="' + it.key + '" onclick="run(\'' + it.key + '\')" title="' + esc(it.desc) + '">' + esc(it.title) + '</button><span class="desc">' + esc(BRIEF[it.key]) + '</span></div></div>';
  let h = '<div class="item"><div class="row"><button data-key="' + it.key + '" onclick="run(\'' + it.key + '\')">' + esc(it.key === '18' ? '开始连续刷' : it.title) + '</button></div>';
  if (it.desc && it.key !== '18') h += '<div class="desc">' + esc(it.desc) + '</div>';
  const os = it.opts.map(o => optHtml(it, o)).join('');
  if (os) h += '<div class="opts">' + os + '</div>';
  if (it.key === '18') h += farmHtml();
  return h + '</div>';
}
// —— 按饰品连续刷：按分类加目标 ——
function farmHtml(){
  const c = catalog; if (!c.series || !c.series.length) return '';
  const sel = 'padding:3px 6px;border:1px solid #b8c4dc;border-radius:6px;font-size:13px';
  const btn = 'background:#fff;color:#2b4a9b;border:1px solid #b8c4dc;padding:4px 12px;font-size:13px;min-width:0;box-shadow:none';
  let sr = '<option value="">任意部位</option>';
  for (const sl of c.slots){
    const two = c.series.filter(s => s.slot === sl);
    sr += '<option value="' + sl + '">' + sl + '（像' + esc(two[0].alias) + '；' + two.map(s => esc(s.suffix)).join('、') + ' 两个系列都算）</option>';
    for (const s of two) sr += '<option value="' + sl + s.suffix + '">　' + sl + '·' + esc(s.suffix) + '（' + esc(s.guild) + '）</option>';
  }
  let h = '<div class="farmpick"><div class="opts" style="align-items:center"><b style="font-size:12px">目标：</b><div id="fb_chips" class="chips"></div></div>' +
    '<div class="opts" style="align-items:center"><b style="font-size:12px">按分类加：</b>' +
    '<label>属性 <select id="fb_el" style="' + sel + '"><option value="">任意</option>' + c.elements.map(e => '<option>' + e + '</option>').join('') + '</select></label>' +
    '<label>部位 / 系列 <select id="fb_sr" style="' + sel + '">' + sr + '</select></label>' +
    '<label>要 <input type="number" id="fb_n" value="1" min="1" max="20" style="width:48px"> 件</label>' +
    '<button onclick="farmAdd()" style="' + btn + '">加进目标</button><button onclick="farmSet(\'\')" style="' + btn + '">清空</button></div>' +
    '<details style="margin-top:6px"><summary style="font-size:13px;cursor:pointer">饰品一览（十个公会的宝箱各出什么，○ = 火 / 水 / 风 / 光 / 暗）</summary>' +
    '<table class="st" style="margin-top:6px"><tr><th>公会</th><th>游戏里的名字</th><th>部位</th><th>系列</th></tr>' +
    c.series.map(s => '<tr><td>' + esc(s.guild) + '</td><td>黎明○' + esc(s.slot) + (s.greek === 'α' ? ' α ' : esc(s.greek)) + esc(s.suffix) + '</td><td>' + esc(s.slot) + '（像' + esc(s.alias) + '）</td><td>' + esc(s.suffix) + '</td></tr>').join('') +
    '</table><div class="desc">每个公会的宝箱只出它自己那个系列，所以挑好目标以后公会留在「自动」就行。几个目标各数各的：一件“火轮赞颂”既算进“火轮赞颂”，也算进“轮”和“火”。</div></details></div>';
  return h;
}
function farmParse(text){
  const out = [];
  for (const part of String(text || '').split(/[,，、;；\s]+/)){
    const m = part.match(/^(.+?)[=＝:：×xX*](\d+)$/);
    if (m && Number(m[2]) > 0) out.push([m[1], Number(m[2])]);
  }
  return out;
}
function farmSet(text){ const el = $('o_18_targets'); if (el){ el.value = text; farmChips(); } }
function farmChips(){
  const el = $('o_18_targets'), box = $('fb_chips'); if (!el || !box) return;
  const ts = farmParse(el.value);
  box.innerHTML = ts.length ? ts.map(([k, n], i) => '<span class="chip">' + esc(k) + ' × ' + n + ' <a href="#" onclick="farmDrop(' + i + ');return false" title="去掉这个目标" style="text-decoration:none;color:#8a4a4a">✕</a></span>').join('')
                            : '<span class="desc" style="margin:0">还没有，在下面按分类加。</span>';
}
function farmDrop(i){ const ts = farmParse($('o_18_targets').value); ts.splice(i, 1); farmSet(ts.map(([k, n]) => k + '=' + n).join(', ')); }
function farmAdd(){
  const el = $('fb_el').value, sr = $('fb_sr').value, n = Math.max(1, Math.min(20, Number($('fb_n').value) || 1));
  const key = (el + sr) || '饰品';
  const ts = farmParse($('o_18_targets').value);
  const hit = ts.find(t => t[0] === key);
  if (hit) hit[1] = Math.min(99, hit[1] + n); else ts.push([key, n]);
  farmSet(ts.map(([k, m]) => k + '=' + m).join(', '));
}
function pickTier(n){ tier = n; for (const el of document.querySelectorAll('.tier')) el.classList.toggle('on', Number(el.dataset.n) === n);
  const tb = $('tierbl'), cur = tiers.find(t => t.n === n); if (tb) tb.textContent = cur ? cur.blurb : '';
  for (const el of document.querySelectorAll('.t1only')) el.style.display = n === 1 ? 'inline-flex' : 'none'; }
// 打开界面时后台自动查了一次有没有新版本：有就在最上面亮一条。换不换还是你点——点「更新」走的就是「检查更新」那一项
async function checkNew(n){
  let u; try { u = await api('/api/update_info'); } catch (e) { return; }
  if (u.state === 'pending'){ if ((n || 0) < 20) setTimeout(() => checkNew((n || 0) + 1), 1500); return; }
  if (u.state === 'new') drawNew(u);
}
function drawNew(u){
  const el = $('newver');
  el.innerHTML = '<span>有新版本 <b>' + esc(u.show) + '</b>（现在是 ' + esc(u.have) + '）</span>' +
    '<button class="primary" data-key="5" onclick="hideNew(); run(\'5\')">更新</button><button class="ghost" onclick="hideNew()">这次不用</button>';
  el.style.display = '';
  setButtons(); fitIfChanged();
}
function hideNew(){ $('newver').style.display = 'none'; fitIfChanged(); }
function drawFirst(){
  const el = $('first');
  if (!firstRun){ el.style.display = 'none'; return; }
  el.innerHTML = '<h2>首次设置 <small>只在第一次用的时候做一遍</small></h2>' +
    '<div class="note">看运行环境、模拟器、挂机要用的几样行不行（不点游戏，约一分钟），不行的直接告诉你怎么改；最后问要不要扫描角色。先把 MuMu 开起来。<br>另外请在游戏里把迷宫的「角色加入动画」设成「不播放」：迷宫地图右上角「菜单」→「设定」。</div>' +
    '<div class="gorow"><button class="primary" data-key="9" onclick="run(\'9\')">开始首次设置</button>' +
    '<button class="ghost" data-key="9" onclick="skipFirst()">不用了</button></div>';
  el.style.display = '';
}
// —— 页面里自己的提示框：askBox 问“确定 / 取消”（回 true / false），tellBox 只说一声。不用浏览器自带的 confirm / alert ——
// 光标默认停在「取消」上（只说一声的停在「确定」上）：手一滑按了回车，不会把要确认的事（比如用门票）就这么确认了。Esc = 取消。
const DLG = {done: null};
function dlgClose(v){ const d = DLG.done; DLG.done = null; $('dlg').hidden = true; if (d) d.call(null, !!v); }
function dlgOpen(text, both){
  return new Promise(res => {
    if (DLG.done) dlgClose(false);                          // 上一个还开着：当成取消
    $('dlgmsg').textContent = String(text == null ? '' : text);
    $('dlgno').style.display = both ? '' : 'none';
    DLG.done = res;
    $('dlg').hidden = false;
    $('dlgmsg').scrollTop = 0;
    setTimeout(() => { try { $(both ? 'dlgno' : 'dlgok').focus(); } catch (e) {} }, 0);
  });
}
const askBox = text => dlgOpen(text, true);
const tellBox = text => dlgOpen(text, false);
document.addEventListener('keydown', e => {
  if ($('dlg').hidden) return;
  if (e.key === 'Escape'){ e.preventDefault(); dlgClose(false); }
  else if (e.key === 'Tab'){ e.preventDefault(); const a = $('dlgno'), b = $('dlgok'); (document.activeElement === b && a.style.display !== 'none' ? a : b).focus(); }   // 光标只在这两个按钮之间走
}, true);
async function skipFirst(){
  if (!await askBox('不做首次设置，以后也不再显示这一栏。确定吗？\n（以后想做：命令行里运行 龙娘pcr.exe setup）')) return;
  const r = await api('/api/run', {key: '9', opts: {skip: true}});
  if (!r.ok && r.msg) await tellBox(r.msg);
  poll();
}
function drawHero(){
  const full = find('15');
  if (!full){ $('hero').style.display = 'none'; return; }
  const t0 = (full.opts.find(o => o.kind === 'tier') || {}).value || 2;
  let h = '<h2>黎明界迷宫</h2>';
  if (tiers.length){
    h += '<div id="tiers">';
    for (const t of tiers) h += '<div class="tier" data-n="' + t.n + '" onclick="pickTier(' + t.n + ')" title="' + esc(t.blurb) + '"><div class="nm">' + t.n + ' ' + esc(t.short) + '</div></div>';
    h += '</div><div id="tierbl"></div>';
  }
  const MAIN = ['guild', 'spend', 'laps', 'settle', 'resume'];          // 常用的摆外面，别的收进「更多选项」
  h += '<div class="optrow">' + full.opts.filter(o => MAIN.includes(o.name)).map(o => optHtml(full, o)).join('') + '</div>';
  h += '<div class="gorow gofold"><button class="primary" data-key="15" onclick="run(\'15\')">开始</button>';
  h += '<details class="adv"><summary>更多选项</summary><div class="optrow">' + full.opts.filter(o => !MAIN.includes(o.name)).map(o => optHtml(full, o)).join('') + '</div></details>';
  h += '<details class="adv"><summary>说明</summary><div class="note">' +
       '· 不勾「使用门票」：只打一局。五个区域走到最终首领跟前就停下，任务结束——不撤退、不打最终首领、不用门票。这一局交给你：自己打掉它就结算，不想要就手动撤退。<br>' +
       '· 勾了「使用门票」：打掉最终首领、结算，每成功打完一局用 1 张门票，打满「打几局」那么多局（成功打完才算一局）。「到多少分才结算」填了数的话，没到分的局撤退重打——不用门票、不算一局。这个勾每次都要重新勾。<br>' +
       '· 「接着打进行中的一局」：游戏里有一局打到一半时（在迷宫首页点「出发」会直接回到地图），不勾的话工具停下、不动它；勾了就从那一局的地图接手往下打，后面和工具自己开的局一样走——档位规定要撤退重开的时候照样会撤退，那一局就没了。开始前把游戏停在迷宫首页或者那一局的地图上。没有进行中的一局时照常开新的。这个勾每次都要重新勾。<br>' +
       '· 「更多选项」里的勾默认都不勾，要哪个勾哪个（勾过的下次还记着）。公会默认是「刷分」：工具自己挑估分最高的公会。<br>' +
       '· 看伤害报告：勾了的话每场打完点开看每个人打了多少（首领战也看；时间到了没打完输的那一场也看），记下来调输出角色的比重、下一次换人。<br>' +
       '· 自动装备：勾了的话编完队点「特别装备」→「自动装备」。你自己配好了装备、不想被换，就别勾。<br>' +
       '· 挂机过夜：游戏每天 5 点换日、偶尔掉线，勾上“自己走回迷宫”它会从标题画面走回来接着打（不勾就停下）；运行期间电脑不会自己睡眠。自动跑的时候你自己伸手点模拟器，它会先停手等你。<br>' +
       '· 四个“不合意就重开”的勾（哪一档都能勾；重开不用门票，勾了任何一个，重开次数的上限放宽到 20 次）：<br>' +
       '　「第一层没有双角色格就重开」：区域 1 的第 2、4 列各有一个印记格（给角色的格子），两个都踩不到就撤退重开。<br>' +
       '　「第二层绕不开商店就重开」：区域 2 不走商店——有不过商店、又不耽误这一档该打的极难的路就走那条；绕不开就撤退重开。<br>' +
       '　「第三层首领一队过不了就重开」：区域 3 首领只用一队打，重打也不加队，打不过就撤退重开。不勾的话打输了下一次多编一队（以前第一、二档默认只用一队，现在要勾了才这样）。<br>' +
       '　「第四层没有双极难就重开」：区域 4 的两个极难没法都走到就撤退重开。不勾的话只打走得到的那个、不重开（以前第一、二档默认会重开，现在要勾了才重开）。<br>' +
       '· 第一档的“只留 / 重开的首领”写名字，用顿号隔开（区域 3 首领和最终首领都写进去）。</div></details></div>';
  $('hero').innerHTML = h; $('hero').style.display = '';
  pickTier(Number(t0));
  const sp = $('o_15_spend'); if (sp){ sp.addEventListener('change', spendGate); spendGate(); }
}
function spendGate(){               // 没勾「使用门票」：只打一局、不看分数——这两格变灰
  const on = !!($('o_15_spend') && $('o_15_spend').checked);
  for (const n of ['laps', 'settle']){ const el = $('o_15_' + n); if (el){ el.disabled = !on; el.title = on ? '' : '勾了「使用门票」才用得上'; el.parentElement.style.opacity = on ? '' : '.45'; } }
}
function drawMenu(){
  drawFirst();
  drawHero();
  let cards = '', grid = '', n = 0;
  for (const g of menu){
    const items = g.items.filter(it => !HERO.includes(it.key));
    if (!items.length) continue;
    if (MAIN_GROUPS.includes(g.title)){
      cards += '<details class="card" id="fold_' + items[0].key + '"><summary>' + esc(g.title) + '</summary><div class="grid one">' + items.map(itemHtml).join('') + '</div></details>';
    } else {
      grid += (g.title === '其他' ? '' : '<h3>' + esc(g.title) + '</h3>') + items.map(itemHtml).join(''); n += items.length;      // 「其他」这一栏本身就叫其他，里面不再写一遍
    }
  }
  $('cards').innerHTML = cards; $('grid').innerHTML = grid;
  farmChips(); const ft = $('o_18_targets'); if (ft) ft.addEventListener('input', farmChips);
  for (const d of document.querySelectorAll('details.card[id^=fold_]')){         // 收起来的卡片：上次开着的还开着
    try { if (localStorage.getItem('lnpcr_' + d.id) === '1') d.open = true; } catch (e) {}
    d.addEventListener('toggle', () => { try { localStorage.setItem('lnpcr_' + d.id, d.open ? '1' : '0'); } catch (e) {} });
  }
  $('more').style.display = n ? '' : 'none';
  try { if (localStorage.getItem('lnpcr_more') === '1') $('more').open = true; } catch (e) {}
  $('more').addEventListener('toggle', () => { try { localStorage.setItem('lnpcr_more', $('more').open ? '1' : '0'); } catch (e) {} });
}
function setButtons(){
  for (const b of document.querySelectorAll('button[data-key]')){
    const k = b.dataset.key;
    b.disabled = running;
  }
}
function detail(set){
  const on = set === undefined ? !document.body.classList.contains('detail') : set;
  document.body.classList.toggle('detail', on);
  $('bdetail').textContent = on ? '◂ 返回' : '输出 ▸';
  try { localStorage.setItem('lnpcr_detail', on ? '1' : '0'); } catch (e) {}
  if (on) { const log = $('log'); log.scrollTop = log.scrollHeight; }
}
async function run(key){
  const opts = {}, it = find(key);
  if (it) for (const o of it.opts){
    if (o.kind === 'tier'){ opts[o.name] = tier; continue; }
    const el = $('o_' + key + '_' + o.name) || (HERO.includes(key) ? $('o_15_' + o.name) : null);
    if (!el) continue;
    opts[o.name] = o.kind === 'check' ? el.checked : (o.kind === 'text' || o.kind === 'select' || o.kind === 'time' ? el.value : Number(el.value));
  }
  if (key === '15' && opts.spend && !await askBox('注意：这一次会真实使用门票。\n\n勾了「使用门票」：每成功打完一局（打掉最终首领、结算）用 1 张门票，一共打 ' + opts.laps + ' 局，最多用 ' + opts.laps + ' 张。' +
      (opts.settle > 0 ? '\n估分没到 ' + opts.settle + ' 的局会撤退重打，不用门票、不算一局。' : '') + '\n确定开始吗？')) return;
  if (key === '15' && opts.resume && !await askBox('勾了「接着打进行中的一局」。\n\n游戏里如果有一局打到一半，工具会从那一局的地图接手往下打，后面和它自己开的局一样走：' +
      '档位规定要撤退重开的时候（极难走不到、一场打了几次都没过……）会把那一局撤退掉。' + (opts.spend ? '' : '\n没勾「使用门票」：走到最终首领跟前就停下，不打它。') + '\n确定开始吗？')) return;
  if (key === '18' && !String(opts.targets || '').trim()){ await tellBox('还没有目标：先在下面「按分类加」里选好属性、部位 / 系列和件数，点「加进目标」。'); return; }
  if (key === '18' && opts.spend && !await askBox('注意：这一次会真实使用门票。\n\n勾了「使用门票」：每打通一局（打掉最终首领、结算）用掉 1 张门票，最多打 ' + opts.max_runs + ' 局。确定开始吗？')) return;
  const r = await api('/api/run', {key, opts});
  if (!r.ok && r.msg) await tellBox(r.msg);
  poll();
}
async function send(){ const v = $('inp').value; $('inp').value = ''; lastQ = ''; const r = await api('/api/input', {text: v}); if (!r.ok && r.msg) await tellBox(r.msg); }
function quick(c){ $('inp').value = c; send(); }
// 工具问问题的时候：把问的那一行拆成“问的话”和“能选的答案”，一个答案一个按钮；要填字的才留输入框
let lastQ = '';
function askParts(q){
  let text = String(q || '').trim().replace(/[>＞:：]\s*$/, '').trim();
  const out = {text: text, choices: [], free: true};
  const parts = text.split(/[；;]/).map(x => x.trim()).filter(x => x);
  const kv = parts.map(p => p.match(/^(直接回车|回车|[A-Za-z0-9]{1,3})\s*=\s*(.+)$/));
  if (kv.length >= 2 && kv.every(m => m)){            // “回车 = 执行；m = 这一步我自己点；a = 后面都自动；q = 退出”
    out.text = '这一步怎么办？'; out.free = false;
    for (const m of kv) out.choices.push([m[1].indexOf('回车') >= 0 ? '' : m[1], m[2]]);
    return out;
  }
  const yn = text.match(/\s*\[(Y\/n|y\/N)\]$/);
  if (yn){                                            // “……吗？ [Y/n]”
    out.text = text.slice(0, yn.index).trim(); out.free = false;
    const yes = ['y', '是'], no = ['n', '否'];
    out.choices = yn[1] === 'Y/n' ? [yes, no] : [no, yes];
    return out;
  }
  if (/然后回车/.test(text)){ out.choices.push(['', '我弄好了']); out.free = false; out.text = text.replace(/[，,]?\s*然后回车/, ''); }
  const def = text.match(/直接回车\s*=\s*([^；;）)]+)/);
  if (def) out.choices.push(['', '用默认的：' + def[1].trim()]);
  const quit = out.text.match(/[；;]?\s*q\s*=\s*退出/);
  if (quit){ out.choices.push(['q', '退出']); out.text = out.text.replace(quit[0], '').trim(); }
  return out;
}
function drawAsk(s){
  const on = !!(s.running && s.asking);
  $('ask').className = on ? 'on' : '';
  if (!on){ lastQ = ''; return; }
  const q = (s.tail || '').trim();
  if (q === lastQ) return;
  lastQ = q;
  const a = askParts(q);
  $('askq').textContent = a.text;
  $('askbtns').innerHTML = a.choices.map(([v, lb], i) => '<button' + (i === 0 ? ' class="pri"' : '') + ' onclick="quick(\'' + v + '\')">' + esc(lb) + '</button>').join(' ');
  $('inp').style.display = $('asksend').style.display = a.free ? '' : 'none';
  if (a.free) $('inp').focus();
}
async function stop(force){ if (force && !await askBox('强制结束会立刻掐掉这一项。如果它正在点游戏，手指可能还按着，回游戏里看一眼。确定吗？')) return; await api('/api/stop', {force: !!force}); }
async function restartNow(){         // 「检查更新」换上了新版本 / 「重置到初始状态」清好了：这个窗口关掉，后台会重新打开一个新的
  if (gone) return;
  gone = true;
  try { await api('/api/restart', {}); } catch (e) {}
  document.body.innerHTML = '<div style="padding:40px;font-size:16px">好了，新的界面窗口马上打开；这个窗口可以关了。</div>';
  window.close();
}
function fmt(s){ const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return (h ? h + ' 小时 ' : '') + (m ? m + ' 分 ' : '') + (s % 60) + ' 秒'; }
function drawChips(f){
  const c = [];
  if (f.tier) c.push('<span class="chip gold"><b>' + esc(f.tier) + '</b></span>');
  if (f.lap) c.push('<span class="chip">第 <b>' + f.lap + '</b>' + (f.laps ? ' / ' + f.laps : '') + ' 局</span>');
  if (f.area) c.push('<span class="chip">区域 <b>' + f.area + '</b></span>');
  if (f.wins || f.losses) c.push('<span class="chip">战斗 赢 <b>' + (f.wins || 0) + '</b> · 输 <b>' + (f.losses || 0) + '</b></span>');
  if (f.restarts) c.push('<span class="chip">重开 <b>' + f.restarts + '</b> 次</span>');
  if (f.recovers) c.push('<span class="chip">走回迷宫 <b>' + f.recovers + '</b> 次</span>');
  if (f.hand) c.push('<span class="chip gold"><b>有个画面认不出来：请到模拟器里手动点过去</b></span>');
  if (f.score) c.push('<span class="chip gold">' + esc(f.score) + '</span>');
  $('chips').innerHTML = c.join(''); $('chips').className = c.length ? 'on' : '';
}
function tbl(head, rows){
  return '<table class="st"><tr>' + head.map(h => '<th>' + esc(h) + '</th>').join('') + '</tr>' +
    rows.map(r => '<tr>' + r.map(c => '<td>' + esc(c === null || c === undefined ? '—' : c) + '</td>').join('') + '</tr>').join('') + '</table>';
}
async function loadStats(){          // 统计：各公会的成绩（在上）、运行记录。别的账（饰品、输出角色、打赢过的队）工具自己记着用，不往这里放
  let s; try { s = await api('/api/stats'); } catch (e) { return; }
  let h = '';
  const g = (s.guilds || []).filter(r => r.scored);
  if (g.length) h += '<h4>各公会的成绩</h4>' +
    tbl(['公会', '走完几局', '平均估分', '最高', '一局约几分钟'], g.map(r => [r.guild, r.scored, r.avg === null ? null : r.avg.toLocaleString(), r.best === null ? null : r.best.toLocaleString(), r.minutes]));
  const runs = s.runs || [];
  if (runs.length){                  // 运行记录：每一次一条（新的在前），整块能收起，每一条也能点开 / 收起
    let open = true; try { open = localStorage.getItem('lnpcr_runs') !== '0'; } catch (e) {}
    h += '<details class="runs"' + (open ? ' open' : '') + ' ontoggle="try { localStorage.setItem(\'lnpcr_runs\', this.open ? \'1\' : \'0\'); } catch (e) {}">' +
      '<summary><b>运行记录</b>（' + runs.length + ' 次）</summary><div class="runlist">' +
      runs.map((r, i) => '<details' + (i === 0 ? ' open' : '') + '><summary>' + esc(r.when) + '　' + esc(r.head) + '</summary><pre>' + esc(r.text) + '</pre></details>').join('') +
      '</div></details>';
  }
  $('statsbody').innerHTML = h || '还没有数据：跑完一局这里就有运行记录；走到最终首领跟前算过分，这里就有各公会的成绩。';
  $('statsn').textContent = '';
}
let wasRunning = false;
async function poll(){
  if (gone) return;
  let s;
  try { s = await api('/api/state?since=' + next); miss = 0; }
  catch (e) { if (++miss >= 4){ $('status').className = 'bad'; $('what').textContent = '后台不在了'; $('doing').textContent = '关掉这个窗口，重新双击启动。'; } return; }
  const log = $('log'), stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
  const old = log.querySelector('.tail'); if (old) old.remove();
  if (s.lines.length){ log.insertAdjacentText('beforeend', s.lines.join('\n') + '\n'); }
  if (s.tail){ const sp = document.createElement('span'); sp.className = 'tail'; sp.textContent = s.tail; log.appendChild(sp); }
  next = s.next;
  if (stick) log.scrollTop = log.scrollHeight;
  running = s.running;
  if (s.restart && !running){ restartNow(); return; }
  const bad = !running && s.last && (s.why || s.last.indexOf('正常') < 0);
  const hand = running && !!(s.facts || {}).hand;          // 有个画面认不出来，在等你去模拟器里点
  $('status').className = running ? ((s.asking || hand) ? 'ask' : 'run') : (bad ? 'bad' : '');
  $('what').textContent = running ? (s.asking ? '在问你' : hand ? '等你动手' : '正在运行') + '：' + s.name + '（' + fmt(s.seconds) + '）' : (s.last ? '上一项' : '空闲');
  $('doing').textContent = running ? (s.asking ? '等你回答——在下面选一个' : hand ? '有个画面认不出来——请到模拟器里手动点过去，我会接着跑' : (s.doing || '……')) : (s.last ? (s.why ? s.why + '　' : '') + s.last : '选好档位，点「开始」');
  $('doing').title = $('doing').textContent;
  $('bstop').style.display = running ? '' : 'none';
  $('bforce').style.display = running && s.stop_asked ? '' : 'none';
  drawAsk(s);
  drawChips(s.facts || {});
  fitIfChanged();
  if (wasRunning && !running){ loadStats(); reloadMenu(); }
  wasRunning = running;
  setButtons();
}
async function reloadMenu(){       // 一项跑完以后：首次设置做没做完变了的话，把那一栏收起来
  try {
    const m = await api('/api/menu');
    if (!!m.first_run !== firstRun){ firstRun = !!m.first_run; drawFirst(); }
    const keys = g => g.map(x => x.items.map(i => i.key).join(',')).join(';');
    if (keys(m.groups) !== keys(menu)){ menu = m.groups; drawMenu(); }
    setButtons();
    setTimeout(fitToContent, 150);
  } catch (e) {}
}
window.addEventListener('pagehide', () => { if (!gone) navigator.sendBeacon('/api/bye?t=' + encodeURIComponent(T), '{}'); });
(async () => {
  try { if (localStorage.getItem('lnpcr_detail') === '1' || new URLSearchParams(location.search).get('detail') === '1') detail(true); } catch (e) {}
  const m = await api('/api/menu'); menu = m.groups; tiers = m.tiers || []; catalog = m.catalog || {}; firstRun = !!m.first_run; drawMenu(); loadStats(); poll(); setInterval(poll, 450);
  setTimeout(fitToContent, 150); setTimeout(fitToContent, 1200);
  $('left').addEventListener('toggle', () => setTimeout(fitToContent, 30), true);
  setTimeout(checkNew, 800);
})();
</script></body></html>
"""


def update_check_on(root: Path) -> bool:
    """打开界面时要不要自动查一次新版本：config/settings.json 里写 "update_check": false 就不查（默认查）。"""
    if os.environ.get("LNPCR_NO_UPDATE_CHECK"):
        return False
    try:
        d = json.loads((Path(root) / "config" / "settings.json").read_text(encoding="utf-8-sig"))
        return d.get("update_check") is not False
    except Exception:  # noqa: BLE001
        return True


def check_new_version(root: Path, net: Any = None) -> dict[str, Any]:
    """去 GitHub 看一眼这个仓库最新的版本标签，和本机的比（只读标签列表；不下载、不换——换要你点「更新」）。
    state：new = 有新版本（show = 新的，have = 现在的）；latest = 已经是最新；failed = 没查成（没网之类，界面上不提）。"""
    try:
        sys.path.insert(0, str(TOOLS)) if str(TOOLS) not in sys.path else None
        import update as UP

        cur = UP.local_version(Path(root))
        have = UP.parse_version(cur)
        best = UP.latest(net or UP.Net(timeout=8.0))
    except Exception as e:  # noqa: BLE001 —— 没网、被限流、GitHub 回的东西不对：都只是“这次没查成”
        return {"state": "failed", "why": str(e)[:200]}
    if best is None or have is None or best[0] <= have:
        return {"state": "latest", "have": UP.show(cur) if cur else ""}
    return {"state": "new", "tag": best[1], "show": UP.show(best[1]), "have": UP.show(cur)}


def page_html() -> str:
    """界面那一页（把版本号填进去）。"""
    try:
        sys.path.insert(0, str(ROOT)) if str(ROOT) not in sys.path else None
        from longniang_pcr import __version__ as ver
    except Exception:  # noqa: BLE001
        ver = ""
    return PAGE.replace("__VERSION__", ver).replace("__QQ__", QQ_GROUP)


class Server:
    def __init__(self, launcher: Launcher, port: int = 0):
        self.launcher = launcher
        self.token = secrets.token_urlsafe(12)
        self.last_poll = time.time()
        self.seen_page = False
        self.bye = 0.0                      # 界面窗口说“我要关了”的时刻（刷新页面也会说一声，所以还要看之后有没有再来问）
        self.quit = threading.Event()
        self.fit: tuple[int, int] | None = None      # 页面量出来的窗口大小（没量之前是 None，用 WINDOW_SIZE）
        self.update_info: dict[str, Any] = {"state": "off"}      # 打开界面时自动查新版本的结果（见 start_update_check）
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:      # 不往黑窗口里刷访问记录
                pass

            def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, obj: Any, code: int = 200) -> None:
                self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

            def _ok(self) -> tuple[str, dict[str, list[str]]] | None:
                u = urllib.parse.urlsplit(self.path)
                q = urllib.parse.parse_qs(u.query)
                origin = self.headers.get("Origin", "")
                if q.get("t", [""])[0] != outer.token or (origin and urllib.parse.urlsplit(origin).hostname not in ("127.0.0.1", "localhost")):
                    self._send(403, "口令不对".encode("utf-8"), "text/plain; charset=utf-8")
                    return None
                return u.path, q

            def do_GET(self) -> None:                    # noqa: N802
                got = self._ok()
                if got is None:
                    return
                path, q = got
                if path == "/":
                    outer.seen_page = True
                    self._send(200, page_html().encode("utf-8"), "text/html; charset=utf-8")
                elif path == "/api/menu":
                    self._json({"groups": outer.launcher.menu(), "tiers": tier_cards(), "catalog": accessory_catalog(),
                                "first_run": first_run_needed(outer.launcher.root)})
                elif path == "/api/stats":
                    self._json(stats(outer.launcher.root))
                elif path == "/api/ping":
                    self._json({"ok": True, "app": "longniang-pcr"})
                elif path == "/api/update_info":
                    self._json(dict(outer.update_info))
                elif path == "/logo.png":
                    try:
                        self._send(200, LOGO.read_bytes(), "image/png")
                    except OSError:
                        self._send(404, b"no logo", "text/plain")
                elif path == "/api/state":
                    outer.last_poll = time.time()
                    try:
                        since = int(q.get("since", ["0"])[0])
                    except ValueError:
                        since = 0
                    self._json(outer.launcher.state(since))
                else:
                    self._send(404, b"not found", "text/plain")

            def do_POST(self) -> None:                   # noqa: N802
                got = self._ok()
                if got is None:
                    return
                path, _q = got
                try:
                    n = int(self.headers.get("Content-Length", "0") or 0)
                    body = json.loads(self.rfile.read(min(n, 65536)).decode("utf-8") or "{}") if n else {}
                except Exception:  # noqa: BLE001
                    body = {}
                la = outer.launcher
                if path == "/api/run":
                    ok, msg = la.start(str(body.get("key", "")), body.get("opts") if isinstance(body.get("opts"), dict) else {})
                elif path == "/api/input":
                    ok, msg = la.send(str(body.get("text", ""))[:200])
                elif path == "/api/stop":
                    ok, msg = la.stop(bool(body.get("force")))
                elif path == "/api/open":
                    ok, msg = la.open_folder(str(body.get("what", "")))
                elif path == "/api/quit":
                    ok, msg = True, ""
                    la.restart = 0.0                     # 人自己点了退出：就是退出，不再重新打开
                    outer.quit.set()
                elif path == "/api/restart":                 # 界面看到“更新好了”以后叫的：这个后台退出，main() 接着重新打开
                    ok, msg = bool(la.restart), "" if la.restart else "没有更新过，不用重新打开"
                    if la.restart:
                        outer.quit.set()
                elif path == "/api/bye":
                    ok, msg = True, ""
                    outer.bye = time.time()
                elif path == "/api/fit":                     # 页面量好了窗口该多高（整个窗口，含标题栏）：记下来，并让 Windows 照着改
                    ok, msg = outer.set_fit(body.get("h")), ""
                else:
                    self._send(404, b"not found", "text/plain")
                    return
                self._json({"ok": ok, "msg": msg})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/?t={self.token}"

    def start_update_check(self, check: Any = None) -> bool:
        """打开界面时自动查一次有没有新版本（2026-11-26 用户要的）：在后台查，不耽误界面打开；查到新的页面上会亮一条提醒。
        设置里关了就不查、不联网。返回这次查没查。"""
        if not update_check_on(self.launcher.root):
            return False
        self.update_info = {"state": "pending"}

        def work() -> None:
            try:
                self.update_info = (check or check_new_version)(self.launcher.root)
            except Exception as e:  # noqa: BLE001
                self.update_info = {"state": "failed", "why": str(e)[:200]}

        threading.Thread(target=work, name="gui-update-check", daemon=True).start()
        return True

    def size_now(self) -> tuple[int, int]:
        """界面窗口现在该多大：页面报过高度就用它报的，没报过用估计的。"""
        return self.fit or WINDOW_SIZE

    def set_fit(self, h: Any, resize: Any = None) -> bool:
        try:
            h = int(round(float(h)))
        except (TypeError, ValueError):
            return False
        if isinstance(h, bool) or not FIT_H_RANGE[0] <= h <= FIT_H_RANGE[1]:
            return False
        self.fit = (WINDOW_SIZE[0], h)
        kw = {"wait": 3.0, "size": self.size_now, "hint": f"127.0.0.1:{self.port}", "say": print, "settle": 0.8}
        threading.Thread(target=resize or shrink_window, kwargs=kw, name="gui-fit", daemon=True).start()
        return True

    def serve(self) -> None:
        threading.Thread(target=self.httpd.serve_forever, name="gui-http", daemon=True).start()

    def window_closed(self) -> bool:
        """界面窗口是不是真的关了：它说过要关，之后 4 秒多都没再来问过。"""
        return bool(self.bye) and time.time() - self.bye > 4.0 and self.last_poll < self.bye

    def close(self, wait: float = STOP_WAIT_S) -> None:
        """退出：正在跑的功能先让它自己停下（和点「停止」一样），等一会儿还不停才强制结束。"""
        la = self.launcher
        if la.running():
            la.stop()
            t0 = time.time()
            while la.running() and time.time() - t0 < wait:
                time.sleep(0.1)
            if la.running():
                la.job.proc.kill()
        self.httpd.shutdown()
        self.httpd.server_close()


WINDOW_SIZE = (426, 420)      # 界面窗口刚出来时的大小（“小工具”那种，逻辑像素）。页面里 FIT_W / FIT_H 是同一组数。
#                               宽度就是它；高度页面量好以后会报上来（/api/fit）：首次设置那一栏没有了、下面三栏都收着的时候，
#                               最底下的「其他」那一栏正好贴着窗口的底（2026-11-25 用户定的）。420 是没量之前先用的估计值
FIT_H_RANGE = (320, 900)      # 页面报上来的高度只认这个范围里的
WINDOW_TITLE = "龙娘pcr"      # 界面窗口标题的开头（页面的 <title>）


def shrink_window(wait: float = 10.0, size: Any = WINDOW_SIZE, title: str = WINDOW_TITLE, api: Any = None,
                  hint: str = "", say: Any = None, settle: float = 2.5, tick: float = 0.06) -> int:
    """界面窗口一出来就把它改成小窗口的大小。返回改了几次。

    为什么要这一步（2026-11-25 用户：“怎么还是一打开就是半个屏幕”）：Edge / Chrome 的“应用窗口”会记住上一次关掉时的大小和位置，
    下次打开照着摆，启动时给的 --window-size 管不住它。所以盯着窗口出来（标题还是网址的那一瞬间就认：hint = “127.0.0.1:端口”），
    直接让 Windows 把它改成想要的大小（最大化的先还原，位置不动）；之后再盯 settle 秒，被改回去就再改。改之前、改之后多大都写进日志。
    只在 Windows 上做；只碰标题以“龙娘pcr”开头（或者是我们这个网址）的浏览器窗口。
    size 可以是一对数，也可以是一个随时问得到“现在想要多大”的函数（页面量好高度以后会变）。"""
    say = say or (lambda text: None)
    if api is None:
        if sys.platform != "win32":
            return 0
        import ctypes
        from ctypes import wintypes

        api = ctypes.windll.user32
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        text = lambda fn, hwnd, n: (lambda b: (fn(hwnd, b, n), b.value)[1])(ctypes.create_unicode_buffer(n))      # noqa: E731

        def size_of(hwnd: Any) -> tuple[int, int]:
            r = wintypes.RECT()
            api.GetWindowRect(hwnd, ctypes.byref(r))
            return int(r.right - r.left), int(r.bottom - r.top)
    else:                                            # 自测用的假接口
        proto, text, size_of = (lambda f: f), (lambda fn, hwnd, n: fn(hwnd)), api.GetWindowRect
    done, t0 = 0, time.time()
    first_seen: float | None = None
    told: set[Any] = set()
    while True:
        found: list[Any] = []

        def each(hwnd: Any, _l: Any) -> bool:
            if not api.IsWindowVisible(hwnd) or not text(api.GetClassNameW, hwnd, 80).startswith("Chrome_WidgetWin"):
                return True
            name = text(api.GetWindowTextW, hwnd, 300)
            if name.startswith(title) or (hint and hint in name):
                found.append(hwnd)
            return True

        api.EnumWindows(proto(each), 0)
        for hwnd in found:
            try:
                scale = (api.GetDpiForWindow(hwnd) or 96) / 96.0      # 我们这个进程不认高分屏时这里永远是 96，正好不用换算
            except Exception:  # noqa: BLE001
                scale = 1.0
            goal = size() if callable(size) else size
            want = (int(round(goal[0] * scale)), int(round(goal[1] * scale)))
            was = size_of(hwnd)
            if api.IsZoomed(hwnd):
                api.ShowWindow(hwnd, 9)              # SW_RESTORE：最大化的先还原
            elif abs(was[0] - want[0]) <= 2 and abs(was[1] - want[1]) <= 2:
                if hwnd not in told:
                    told.add(hwnd)
                    say(f"  界面窗口打开时就是 {was[0]}×{was[1]}，不用改。")
                continue
            api.SetWindowPos(hwnd, 0, 0, 0, want[0], want[1], 0x0002 | 0x0004 | 0x0010)   # 不挪位置、不改前后、不抢焦点
            done += 1
            now = size_of(hwnd)
            if hwnd not in told or done <= 3:
                told.add(hwnd)
                try:
                    screen = f"{api.GetSystemMetrics(0)}×{api.GetSystemMetrics(1)}"
                except Exception:  # noqa: BLE001
                    screen = "？"
                say(f"  界面窗口：屏幕 {screen}，缩放 {scale:g}；打开时 {was[0]}×{was[1]} → 改成 {now[0]}×{now[1]}（想要 {want[0]}×{want[1]}）。")
        if found and first_seen is None:
            first_seen = time.time()
        if first_seen is not None and time.time() - first_seen >= settle:
            return done
        if first_seen is None and time.time() - t0 >= wait:
            say("  界面窗口：等了一会儿没找到它（可能是在普通浏览器标签页里打开的，那种改不了大小）。")
            return 0
        time.sleep(tick)


def open_window(url: str) -> str:
    """用 Edge / Chrome 的“应用窗口”打开（没有地址栏，看着就是个普通窗口）；都没有就用默认浏览器。返回用的是什么。"""
    if sys.platform == "win32":
        cands = []
        for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                cands += [Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                          Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"]
        for exe in cands:
            if exe.exists():
                try:
                    subprocess.Popen([str(exe), f"--app={url}", f"--window-size={WINDOW_SIZE[0]},{WINDOW_SIZE[1]}"])   # noqa: S603
                    return exe.stem
                except OSError:
                    continue
    try:
        import webbrowser

        if webbrowser.open(url):
            return "默认浏览器"
    except Exception:  # noqa: BLE001
        pass
    return ""


# ---- 只开一个：再双击一次时，把已经开着的那个界面再打开一个窗口，而不是再起一个后台（两个后台会抢着点游戏）----
def lock_path() -> Path:
    base = os.environ.get("LNPCR_RUNTIME") or os.path.join(os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache")), "longniang-pcr")
    return Path(base) / "gui.json"


def running_instance(path: Path | None = None) -> str:
    """已经有一个界面后台在跑的话，返回它的地址；没有返回空串。"""
    path = path or lock_path()
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        url = f"http://127.0.0.1:{int(d['port'])}/api/ping?t={urllib.parse.quote(str(d['token']))}"
        with urllib.request.urlopen(url, timeout=1.0) as r:          # noqa: S310  只连本机
            if json.loads(r.read()).get("app") == "longniang-pcr":
                return f"http://127.0.0.1:{int(d['port'])}/?t={d['token']}"
    except Exception:  # noqa: BLE001  文件没有、读不了、连不上，都是“没有在跑的”
        pass
    return ""


def write_lock(srv: "Server", path: Path | None = None) -> None:
    path = path or lock_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"port": srv.port, "token": srv.token, "pid": os.getpid()}), encoding="utf-8")
    except OSError:
        pass


def clear_lock(srv: "Server", path: Path | None = None) -> None:
    path = path or lock_path()
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("token") == srv.token:
            path.unlink()
    except Exception:  # noqa: BLE001
        pass


def watch(srv: "Server", say: Any = print, tick: float = 1.0, silent_s: float = SILENT_S) -> str:
    """守着，直到该退出了。返回原因：quit（点了退出）/ closed（窗口关了）/ silent（很久没有界面的消息）/ interrupt。"""
    last_tick = time.time()
    try:
        while not srv.quit.wait(tick):
            now = time.time()
            if now - last_tick > 20:                 # 电脑睡了一觉刚醒：界面还没来得及问，别当成窗口没了
                srv.last_poll = now
            last_tick = now
            if srv.launcher.restart and now - srv.launcher.restart > RESTART_WAIT_S:      # 更新好了，界面一直没来叫：不等了，自己重新打开
                say("  更新好了，重新打开界面。")
                return "restart"
            if srv.window_closed():
                say("  界面窗口关了，退出。")
                return "closed"
            # 很久没有界面的消息：窗口多半是没了。有功能在跑时不因为这个掐它（窗口被游戏挡住、最小化时浏览器会放慢询问；
            # 要停随时按 F12，再双击一次启动也能把界面找回来），等它跑完再退出
            if now - srv.last_poll > silent_s and not srv.launcher.running():
                say("  很久没有收到界面的消息了，退出。")
                return "silent"
    except KeyboardInterrupt:
        return "interrupt"
    return "quit"


def relaunch(windowless: bool = True, popen: Any = subprocess.Popen, root: Path = ROOT) -> bool:
    """更新以后重新打开界面：叫“龙娘pcr.exe”再启动一次（这时候磁盘上已经是新版本的代码了）。exe 不在就直接用 Python 起。"""
    exe = Path(os.environ.get("LNPCR_EXE") or root / "龙娘pcr.exe")
    cmd = [str(exe)] if exe.exists() else [sys.executable, str(root / "tools" / "menu.py"), "window" if windowless else "gui"]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        popen(cmd, cwd=str(root), close_fds=True, creationflags=flags)      # noqa: S603
        return True
    except OSError as e:
        print(f"  没能重新打开界面（{e}），请自己再双击一次“龙娘pcr.exe”。")
        return False


def main(items: dict[str, tuple], extra: dict[str, tuple], release: bool = False, windowless: bool = False) -> int:
    url = running_instance()
    if url:                                          # 已经开着：再给它开一个窗口就行
        if open_window(url) not in ("", "默认浏览器"):
            shrink_window(4.0, hint=urllib.parse.urlsplit(url).netloc, say=print, settle=1.5)
        return 0
    srv = Server(Launcher(items, extra, release))
    srv.serve()
    write_lock(srv)
    srv.start_update_check()                         # 后台查一眼有没有新版本（只读 GitHub 上的版本标签；设置里能关）
    how = open_window(srv.url)
    if how not in ("", "默认浏览器"):                 # 应用窗口会照上次的大小打开：等它出来以后改成小窗口（不挡着后面的事）
        threading.Thread(target=shrink_window, kwargs={"hint": f"127.0.0.1:{srv.port}", "say": print, "size": srv.size_now},
                         name="gui-shrink", daemon=True).start()
    print("")
    print("  图形界面已经打开" + (f"（{how}）" if how else "失败了，请自己用浏览器打开下面的地址") + "。")
    print(f"  地址：{srv.url}")
    if not windowless:
        print("  这个黑窗口是它的后台，留着别关；关掉界面窗口工具就退出了。")
    if not how and windowless:                       # 没有黑窗口、界面又没打开：留着后台也没人看得见，直接退出并报错
        srv.close(0)
        clear_lock(srv)
        raise RuntimeError("没能打开界面窗口（没找到 Edge / Chrome，默认浏览器也没打开）")
    srv.last_poll = time.time()
    try:
        watch(srv)
    finally:
        srv.close()
        clear_lock(srv)
    if srv.launcher.restart:                         # 「检查更新」换上了新版本：这个（旧代码的）后台退出，重新打开一个
        relaunch(windowless)
    return 0
