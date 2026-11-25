"""把“找到模拟器并连上”这件事串起来：连接测试和录制工具共用。"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from . import mumu, win32
from .adb import Adb
from .nemu_ipc import NemuIpc, call_with_timeout

GAME_HINT = re.compile(r"priconne|princessconnect", re.I)
DEFAULT_GAME = "com.bilibili.priconne"  # 公主连结国服（B 服）


@dataclass
class Target:
    install: mumu.MuMuInstall
    cli: Path | None
    adb: Adb
    index: int
    serial: str
    info: dict[str, Any] = field(default_factory=dict)
    all_infos: dict[int, dict[str, Any]] = field(default_factory=dict)
    android: str = ""
    sdk: int = 0
    size: tuple[int, int] = (0, 0)
    density: int = 0
    games: list[str] = field(default_factory=list)
    foreground: str = ""

    @property
    def game(self) -> str | None:
        for g in self.games:
            if g == DEFAULT_GAME:
                return g
        return self.games[0] if self.games else None

    @property
    def main_wnd(self) -> int | None:
        return win32.parse_hwnd(self.info.get("main_wnd"))

    @property
    def render_wnd(self) -> int | None:
        return win32.parse_hwnd(self.info.get("render_wnd"))


class DiscoverError(RuntimeError):
    pass


def _env_root() -> list[str]:
    v = os.environ.get("LNPCR_MUMU_ROOT")
    return [v] if v else []


# 命令行工具和配置文件都问不出端口时试的：MuMu 12 第一个实例是 16384，每多开一个加 32；7555 是老版本；5555 是安卓里面默认的
DEFAULT_PORTS = [16384 + 32 * i for i in range(8)] + [7555, 5555]
_REFUSED = re.compile(r"cannot connect|failed to connect|unable to connect|refused|10061|拒绝", re.I)


def _probe(ins: mumu.MuMuInstall) -> dict[str, Any]:
    """问一个 MuMu 安装的命令行工具：有哪些实例、哪些在运行。问不出来 infos 就是空的。"""
    infos: dict[int, dict[str, Any]] = {}
    cli = None
    raw = []
    for c in ins.cli:
        infos, text = mumu.instance_infos(c)
        raw.append({"cli": str(c), "output": text[:4000]})
        if infos:
            cli = c
            break
    running = {i: v for i, v in infos.items() if mumu.truthy(v.get("is_android_started")) or mumu.truthy(v.get("is_process_started"))}
    return {"ins": ins, "cli": cli, "infos": infos, "running": running, "raw": raw}


def _port_index(port: int) -> int:
    """按端口猜是第几个实例（16384 起每个加 32）；别的端口当成第一个。"""
    return (port - 16384) // 32 if port >= 16384 and (port - 16384) % 32 == 0 and port < 16384 + 32 * 64 else 0


def find_target(rep: Any, extra_roots: list[str] | None = None) -> Target:
    """定位 MuMu → 选实例 → 连 ADB → 读安卓信息。rep 是 Report（负责往屏幕和文件里写）。

    2026-11-25 有用户连不上（电脑上找到两个 MuMu 安装，用了第一个，它的命令行工具问不出端口，默认的 16384 / 5555 又都被拒绝）。改成：
    · 不止一个安装：每个都问一遍，用报得出“有实例在运行”的那个，而不是排在第一个的；
    · 命令行工具问不出端口：先看 MuMu 自己配置文件里登记的端口，再试常用的那一串（多开的实例也在里面）；
    · 还是连不上：把试过哪些、各是什么结果说清楚。"""
    installs, clues = mumu.find_installs((extra_roots or []) + _env_root())
    rep.put("mumu_clues", clues)
    rep.put("mumu_installs", [i.to_dict() for i in installs])
    if not installs:
        names = ", ".join(sorted({p["name"] for p in clues.get("processes", []) if p.get("name")})) or "无"
        raise DiscoverError(f"没找到 MuMu 的安装目录（正在运行的相关进程：{names}）")
    usable = [i for i in installs if i.adb]
    if not usable:
        raise DiscoverError(f"在 {installs[0].root} 里没找到 adb.exe")
    if len(installs) > 1:
        rep.warn("找到不止一个 MuMu 安装：" + "；".join(str(i.root) for i in installs) + "。挨个问一遍，用正在运行的那个")
    probes: list[dict[str, Any]] = []
    for i in usable:                                          # 排在前面的是有进程在运行的那个安装：它答得出“在运行”就不用再问别的了
        probes.append(_probe(i))
        if probes[-1]["running"]:
            break
    rep.put("mumu_info_raw", [x for p in probes for x in p["raw"]])
    pick = probes[-1] if probes[-1]["running"] else None
    if pick is None and all(p["infos"] for p in probes):      # 每个安装的命令行工具都答得上话，都说没有实例在运行
        for p in probes:
            for i, v in sorted(p["infos"].items()):
                rep.info(f"实例 {i}：{v.get('name', '')}　未启动　ADB {v.get('adb_host_ip', '-')}:{v.get('adb_port', '-')}")
        raise DiscoverError("模拟器没有在运行。请先打开 MuMu、启动公主连结，再来跑一次")
    if pick is None:                                          # 没有哪个说得出“在运行”：用问不出东西的那个，按端口去试
        pick = next((p for p in probes if not p["infos"]), probes[0])
    ins, cli, infos, running = pick["ins"], pick["cli"], pick["infos"], pick["running"]
    rep.ok(f"MuMu 安装目录：{ins.root}（线索：{'、'.join(dict.fromkeys(ins.sources))}）")
    if ins.version:
        rep.info(f"注册表里登记的版本：{ins.version}")
    if ins.vms:
        rep.info("实例数据文件夹：" + "、".join(ins.vms))
    rep.info(f"adb：{ins.adb[0]}")
    if not ins.cli:
        rep.warn("没找到命令行工具（mumu-cli.exe / MuMuManager.exe），实例信息只能靠猜")
    elif cli is not None:
        rep.info(f"命令行工具：{cli}")
    rep.info("截图接口 DLL：" + ("、".join(str(d.relative_to(ins.root)) for d in ins.dlls) if ins.dlls else "没找到"))
    rep.put("mumu_infos", infos)
    for i, v in sorted(infos.items()):
        state = "运行中" if i in running else "未启动"
        rep.info(f"实例 {i}：{v.get('name', '')}　{state}　ADB {v.get('adb_host_ip', '-')}:{v.get('adb_port', '-')}")

    # ---- 该连哪个端口 ----
    candidates: list[tuple[int, str]] = []
    for i, v in sorted(running.items()):
        if v.get("adb_port"):
            candidates.append((i, f"{v.get('adb_host_ip') or '127.0.0.1'}:{v['adb_port']}"))
    guessed = not candidates
    if guessed:
        ports: dict[int, int] = {}
        for p in [pick] + [q for q in probes if q is not pick]:
            for i, port in mumu.config_ports(p["ins"].root).items():
                ports.setdefault(i, port)
        rep.put("mumu_config_ports", ports)
        candidates = [(i, f"127.0.0.1:{port}") for i, port in sorted(ports.items())]
        have = {sr for _i, sr in candidates}
        candidates += [(_port_index(port), f"127.0.0.1:{port}") for port in DEFAULT_PORTS if f"127.0.0.1:{port}" not in have]
        rep.warn("没从命令行工具拿到 ADB 端口，" + (f"先按 MuMu 配置文件里登记的端口试（{'、'.join(str(v) for _k, v in sorted(ports.items()))}），再" if ports else "改")
                 + "试 MuMu 常用的端口（16384 起、每多开一个加 32，还有 7555 / 5555）")

    # ---- ADB ----
    adb = Adb(ins.adb[0])
    adb.start_server()
    chosen: Target | None = None
    tried = []
    for idx, serial in candidates:
        adb_i = Adb(ins.adb[0], serial)
        msg = adb_i.connect()
        refused = bool(_REFUSED.search(msg or ""))
        st = ""
        if not refused:
            for n in range(4):  # 刚连上时偶尔会先显示 offline，等一下再看
                st = adb_i.state()
                if st.strip() == "device":
                    break
                if n == 1 and "offline" in st:           # 一直是 offline：断开重连一次（只动这一个地址，不碰别的设备）
                    adb_i.text(["disconnect", serial], 10.0, use_serial=False)
                    msg = adb_i.connect()
                time.sleep(1.0)
        tried.append({"index": idx, "serial": serial, "connect": msg, "state": st, "refused": refused})
        if st.strip() != "device":
            if not (guessed and refused):                # 挨个试端口时，“没人在听”的那些最后合起来说一句，不一条条刷屏
                rep.warn(f"ADB 连接 {serial}：{msg or '无输出'}（状态 {st or '未知'}）")
            continue
        rep.ok(f"ADB 已连上 {serial}")
        t = Target(install=ins, cli=cli, adb=adb_i, index=idx, serial=serial, info=infos.get(idx, {}), all_infos=infos)
        _read_android(t)
        if chosen is None or (t.games and not chosen.games):
            chosen = t
        if chosen.games:
            break
    rep.put("adb_tried", tried)
    rep.put("adb_devices", adb.devices())
    if chosen is None:
        dead = [x["serial"].rsplit(":", 1)[-1] for x in tried if x["refused"]]
        odd = [f"{x['serial'].rsplit(':', 1)[-1]}（{(x['state'] or x['connect'] or '没有回应').strip().splitlines()[0][:40]}）" for x in tried if not x["refused"]]
        what = "；".join(x for x in (("端口 " + "、".join(dead) + " 没有东西在听" if dead else ""), ("、".join(odd) if odd else "")) if x)
        no_proc = not clues.get("processes")
        raise DiscoverError(
            f"ADB 连不上模拟器（{what}）。"
            + ("没看到 MuMu 的进程——模拟器是不是没开？" if no_proc else "")
            + "常见原因：① MuMu 没开着，或者刚打开、安卓还没启动完；② 在 MuMu 设置里改了“ADB 调试”以后没有重启模拟器；"
              "③ 别的模拟器、手机助手自带的 adb 在抢，把它们关掉再试"
            + ("；④ 电脑上有不止一个 MuMu（" + "；".join(str(i.root) for i in installs) + "），这次用的是 " + str(ins.root) if len(installs) > 1 else ""))
    return chosen


def _read_android(t: Target) -> None:
    a = t.adb
    t.android = a.getprop("ro.build.version.release")
    try:
        t.sdk = int(a.getprop("ro.build.version.sdk") or 0)
    except ValueError:
        t.sdk = 0
    m = re.findall(r"(\d+)x(\d+)", a.shell("wm size"))
    if m:
        w, h = map(int, m[-1])
        t.size = (w, h)
    m2 = re.findall(r"(\d+)", a.shell("wm density"))
    if m2:
        t.density = int(m2[-1])
    pk = a.shell("pm list packages", 30.0)
    t.games = sorted({ln.split(":", 1)[1].strip() for ln in pk.splitlines() if ln.startswith("package:") and GAME_HINT.search(ln)})
    t.foreground = foreground_app(a)


def foreground_app(adb: Adb) -> str:
    """当前在最前面的应用（包名/Activity）。"""
    out = adb.shell("dumpsys activity activities | grep -E 'ResumedActivity'", 20.0)
    m = re.search(r"u\d+\s+([\w.]+/[\w.$]+)", out)
    if m:
        return m.group(1)
    out = adb.shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'", 20.0)
    m = re.search(r"\s([\w.]+/[\w.$]+)[\s}]", out)
    return m.group(1) if m else ""


# ---------------------------------------------------------------- MuMu 截图接口


def nemu_candidates(t: Target) -> list[tuple[Path, Path]]:
    """(DLL, 传给 nemu_connect 的目录) 的尝试顺序：安卓版本对得上的 DLL 优先。"""
    major = (t.android or "").split(".")[0]

    def rank(p: Path) -> int:
        s = str(p).lower().replace("/", "\\")
        return 0 if major and f"\\{major}.0\\" in s else 1

    res = []
    for dll in sorted(t.install.dlls, key=rank):
        folders = [t.install.root]
        try:
            folders.append(dll.parents[2])
        except IndexError:
            pass
        seen = set()
        for f in folders:
            k = os.path.normcase(str(f))
            if k not in seen:
                seen.add(k)
                res.append((dll, f))
    return res


def open_nemu(t: Target, rep: Any) -> NemuIpc | None:
    """连上 MuMu 的截图接口。失败返回 None（原因写进报告）。"""
    attempts = []
    for dll, folder in nemu_candidates(t):
        rec: dict[str, Any] = {"dll": str(dll), "folder": str(folder), "index": t.index}
        attempts.append(rec)
        try:
            n = NemuIpc(dll).load()
            if not n.connect(folder, t.index):
                rec["result"] = "nemu_connect 返回 0（连接失败）"
                continue
            rec["handle"] = n.handle
            if t.game:
                try:
                    did = n.get_display_id(t.game)
                    rec["display_id_for_game"] = did
                    if did is not None and did >= 0:
                        n.display_id = did
                except Exception as e:  # noqa: BLE001
                    rec["display_id_error"] = f"{type(e).__name__}: {e}"
            try:
                call_with_timeout(n.resolution, 10.0)
            except Exception as e:  # noqa: BLE001
                rec["resolution_error"] = f"{type(e).__name__}: {e}"
                if n.display_id != 0:
                    n.display_id = 0
                    call_with_timeout(n.resolution, 10.0)
            rec["resolution"] = [n.width, n.height]
            rec["display_id_used"] = n.display_id
            call_with_timeout(n.capture, 10.0)  # 真截一张，确认这条路是通的（卡住也只等 10 秒）
            rec["result"] = "成功"
            rep.put("nemu_attempts", attempts)
            return n
        except Exception as e:  # noqa: BLE001
            rec["result"] = f"{type(e).__name__}: {e}"
    rep.put("nemu_attempts", attempts)
    return None


# ---------------------------------------------------------------- 统一的截图入口


class Grabber:
    """按“MuMu 接口 → ADB 原始 → ADB PNG”的顺序挑一个能用的截图方式。"""

    def __init__(self, t: Target, nemu: NemuIpc | None):
        self.t = t
        self.nemu = nemu
        self.name = ""
        self._fn: Any = None

    def pick(self, rep: Any | None = None) -> bool:
        options = []
        if self.nemu is not None:
            options.append(("MuMu 接口", self.nemu.capture))
        options.append(("ADB 原始", self.t.adb.screencap_raw))
        options.append(("ADB PNG", self.t.adb.screencap_png))
        for name, fn in options:
            try:
                img = fn()
                if isinstance(img, np.ndarray) and img.ndim == 3 and img.shape[0] > 100:
                    self.name, self._fn = name, fn
                    return True
            except Exception as e:  # noqa: BLE001
                if rep is not None:
                    rep.warn(f"截图方式「{name}」不可用：{type(e).__name__}: {e}")
        return False

    def grab(self) -> np.ndarray:
        return self._fn()


def bench(fn: Any, n: int, warmup: int = 1) -> tuple[list[float], Any]:
    """连续调用 n 次，返回每次耗时（毫秒）和最后一次的结果。"""
    out = None
    for _ in range(warmup):
        out = fn()
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        out = fn()
        times.append((time.perf_counter() - t0) * 1000)
    return times, out


def stats(times: list[float]) -> dict[str, float]:
    if not times:
        return {}
    s = sorted(times)
    return {
        "n": len(s),
        "median": round(s[len(s) // 2], 2),
        "min": round(s[0], 2),
        "max": round(s[-1], 2),
        "p90": round(s[min(len(s) - 1, int(len(s) * 0.9))], 2),
    }
