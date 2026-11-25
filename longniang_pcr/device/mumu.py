"""定位 MuMu 模拟器：安装目录、命令行工具、自带 adb、截图接口 DLL、实例信息。

MuMu 6 的目录结构（2026 年的版本）：
    <安装目录>\\nx_main\\mumu-cli.exe        命令行工具（旧名 MuMuManager.exe，功能相同）
    <安装目录>\\nx_main\\adb.exe
    <安装目录>\\nx_device\\15.0\\shell\\sdk\\external_renderer_ipc.dll   安卓 15 内核
    <安装目录>\\nx_device\\12.0\\shell\\sdk\\external_renderer_ipc.dll   安卓 12 内核
    <安装目录>\\vms\\MuMuPlayer-15.0-0\\                                  实例数据
更早的版本是 <安装目录>\\shell\\...。这里不写死路径，全部现找。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CLI_NAMES = ["mumu-cli.exe", "MuMuManager.exe"]
DLL_NAME = "external_renderer_ipc.dll"
_SKIP_DIRS = {"vms", "cache", "logs", "log", "data", "temp", "tmp", "crashdump"}


@dataclass
class MuMuInstall:
    root: Path
    sources: list[str] = field(default_factory=list)
    cli: list[Path] = field(default_factory=list)
    adb: list[Path] = field(default_factory=list)
    dlls: list[Path] = field(default_factory=list)
    version: str | None = None
    vms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "sources": self.sources,
            "cli": [str(p) for p in self.cli],
            "adb": [str(p) for p in self.adb],
            "dlls": [str(p) for p in self.dlls],
            "version": self.version,
            "vms": self.vms,
        }


def _decode(b: bytes) -> str:
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def is_root(d: Path) -> bool:
    try:
        if (d / "nx_main").is_dir():
            return True
        if (d / "shell").is_dir() and any((d / "shell" / n).exists() for n in CLI_NAMES):
            return True
    except OSError:
        pass
    return False


def root_from_path(p: Path) -> Path | None:
    """从某个 MuMu 文件 / 文件夹往上找安装根目录。"""
    try:
        cur = p if p.is_dir() else p.parent
    except OSError:
        cur = p.parent
    for _ in range(7):
        if is_root(cur):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def registry_entries() -> list[dict[str, str]]:
    """系统“卸载程序”列表里和 MuMu 有关的条目。"""
    if sys.platform != "win32":
        return []
    import winreg

    out: list[dict[str, str]] = []
    seen = set()
    for hive, hname in ((winreg.HKEY_LOCAL_MACHINE, "HKLM"), (winreg.HKEY_CURRENT_USER, "HKCU")):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                base = winreg.OpenKey(
                    hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0, winreg.KEY_READ | view
                )
            except OSError:
                continue
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(base, i)
                except OSError:
                    break
                i += 1
                try:
                    k = winreg.OpenKey(base, sub, 0, winreg.KEY_READ | view)
                except OSError:
                    continue
                vals: dict[str, str] = {}
                for name in ("DisplayName", "DisplayVersion", "InstallLocation", "DisplayIcon", "UninstallString"):
                    try:
                        v, _ = winreg.QueryValueEx(k, name)
                        vals[name] = str(v)
                    except OSError:
                        pass
                winreg.CloseKey(k)
                blob = (sub + " " + vals.get("DisplayName", "")).lower()
                if "mumu" not in blob and "nemu" not in blob:
                    continue
                key = (sub, vals.get("InstallLocation"), vals.get("DisplayIcon"))
                if key in seen:
                    continue
                seen.add(key)
                vals["key"] = f"{hname}\\...\\Uninstall\\{sub}"
                out.append(vals)
            winreg.CloseKey(base)
    return out


def _paths_in(value: str) -> list[Path]:
    res = []
    v = value.strip().strip('"')
    for m in re.finditer(r"[A-Za-z]:\\[^\"<>|*?\r\n]+?\.(?:exe|ico|dll)", value, flags=re.I):
        res.append(Path(m.group(0)))
    if v and re.match(r"^[A-Za-z]:\\", v) and not res:
        res.append(Path(v.split(",")[0]))
    return res


def processes() -> list[dict[str, Any]]:
    """正在运行的 MuMu 相关进程。"""
    out = []
    try:
        import psutil
    except Exception:
        return out
    for p in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = (p.info.get("name") or "").lower()
            if "mumu" in name or "nemu" in name:
                out.append({"pid": p.info["pid"], "name": p.info.get("name"), "exe": p.info.get("exe")})
        except Exception:
            continue
    return out


def _common_dirs() -> list[Path]:
    res = []
    if sys.platform != "win32":
        return res
    for c in "CDEFGHIJ":
        drive = Path(f"{c}:\\")
        try:
            if not drive.exists():
                continue
        except OSError:
            continue
        for base in (drive / "Program Files" / "Netease", drive / "Program Files (x86)" / "Netease", drive / "Netease", drive / "Program Files", drive):
            try:
                if not base.is_dir():
                    continue
                for child in base.iterdir():
                    n = child.name.lower()
                    if ("mumu" in n or base.name.lower() == "netease") and child.is_dir():
                        res.append(child)
            except OSError:
                continue
    return res


def scan(root: Path) -> dict[str, list[Path]]:
    wanted = {n.lower() for n in CLI_NAMES} | {"adb.exe", DLL_NAME}
    found: dict[str, list[Path]] = {w: [] for w in wanted}
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        try:
            depth = len(Path(dirpath).relative_to(root).parts)
        except ValueError:
            depth = 0
        if depth >= 6:
            dirnames[:] = []
        else:
            dirnames[:] = [d for d in dirnames if d.lower() not in _SKIP_DIRS]
        for f in filenames:
            fl = f.lower()
            if fl in wanted:
                found[fl].append(Path(dirpath) / f)
    return found


def _rank_cli(p: Path) -> tuple[int, int]:
    return (0 if p.parent.name.lower() == "nx_main" else 1, CLI_NAMES.index(p.name) if p.name in CLI_NAMES else 9)


def _rank_adb(p: Path) -> int:
    n = p.parent.name.lower()
    return 0 if n == "nx_main" else (1 if n == "shell" else 2)


def build_install(root: Path, sources: list[str]) -> MuMuInstall:
    found = scan(root)
    cli = sorted(found["mumu-cli.exe"] + found["mumumanager.exe"], key=_rank_cli)
    adb = sorted(found["adb.exe"], key=_rank_adb)
    dlls = sorted(found[DLL_NAME.lower()], key=lambda p: str(p).lower(), reverse=True)
    vms = []
    try:
        vdir = root / "vms"
        if vdir.is_dir():
            vms = sorted(c.name for c in vdir.iterdir() if c.is_dir())
    except OSError:
        pass
    return MuMuInstall(root=root, sources=sources, cli=cli, adb=adb, dlls=dlls, vms=vms)


def find_installs(extra: list[str | Path] | None = None) -> tuple[list[MuMuInstall], dict[str, Any]]:
    """返回 (找到的安装, 线索明细)。优先级：正在运行的进程 > 注册表 > 常见目录。"""
    clues: dict[str, Any] = {}
    roots: dict[str, list[str]] = {}

    def add(root: Path | None, src: str) -> None:
        if root is None:
            return
        key = os.path.normcase(str(root))
        roots.setdefault(key, [])
        roots[key].append(src)
        real.setdefault(key, root)

    real: dict[str, Path] = {}
    for e in extra or []:
        p = Path(e)
        add(p if is_root(p) else root_from_path(p), "手动指定")
    procs = processes()
    clues["processes"] = procs
    for pr in procs:
        if pr.get("exe"):
            add(root_from_path(Path(pr["exe"])), f"进程 {pr['name']}")
    reg = registry_entries()
    clues["registry"] = reg
    versions: dict[str, str] = {}
    for ent in reg:
        for name in ("InstallLocation", "DisplayIcon", "UninstallString"):
            for p in _paths_in(ent.get(name, "")):
                r = p if is_root(p) else root_from_path(p)
                if r is not None:
                    add(r, f"注册表 {ent.get('DisplayName', ent.get('key', ''))}")
                    if ent.get("DisplayVersion"):
                        versions[os.path.normcase(str(r))] = ent["DisplayVersion"]
    for d in _common_dirs():
        if is_root(d):
            add(d, "常见目录")
    installs = []
    for key, srcs in roots.items():
        ins = build_install(real[key], srcs)
        ins.version = versions.get(key)
        installs.append(ins)
    installs.sort(key=lambda i: 0 if any(s.startswith(("进程", "手动")) for s in i.sources) else 1)
    return installs, clues


# ---------------------------------------------------------------- 命令行工具


def cli_run(cli: Path, args: list[str], timeout: float = 25.0) -> tuple[int, str]:
    try:
        p = subprocess.run(
            [str(cli)] + args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            cwd=str(cli.parent),
        )
        text = _decode(p.stdout).strip()
        if not text:
            text = _decode(p.stderr).strip()
        return p.returncode, text
    except subprocess.TimeoutExpired:
        return -999, f"[超时 {timeout}s]"
    except OSError as e:
        return -998, str(e)


def _loads(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        pass
    a, b = text.find("{"), text.rfind("}")
    if 0 <= a < b:
        try:
            return json.loads(text[a : b + 1])
        except Exception:
            return None
    return None


def cli_json(cli: Path, args: list[str], timeout: float = 25.0) -> tuple[Any, str]:
    rc, text = cli_run(cli, args, timeout)
    return _loads(text), text


def normalize_infos(obj: Any) -> dict[int, dict[str, Any]]:
    """`info -v all` 的返回：单个实例时是一个对象，多个实例时是 {序号: 对象}。"""
    res: dict[int, dict[str, Any]] = {}
    if not isinstance(obj, dict):
        return res
    if "index" in obj and not isinstance(obj.get("index"), dict):
        try:
            res[int(obj["index"])] = obj
        except (TypeError, ValueError):
            res[0] = obj
        return res
    for k, v in obj.items():
        if isinstance(v, dict):
            try:
                idx = int(v.get("index", k))
            except (TypeError, ValueError):
                continue
            res[idx] = v
    return res


def instance_infos(cli: Path) -> tuple[dict[int, dict[str, Any]], str]:
    obj, text = cli_json(cli, ["info", "-v", "all"])
    infos = normalize_infos(obj)
    if not infos:
        obj, text2 = cli_json(cli, ["info", "--vmindex", "all"])
        infos = normalize_infos(obj)
        text = text + "\n---\n" + text2
    return infos, text


def _adb_port_in(obj: Any, depth: int = 0) -> int | None:
    """在一份配置里找“adb”那一项的端口（层数、名字各版本不太一样，所以一层层找）。"""
    if depth > 8:
        return None
    if isinstance(obj, dict):
        adb = obj.get("adb")
        if isinstance(adb, dict):
            for k in ("host_port", "port"):
                try:
                    port = int(str(adb.get(k, "")).strip())
                except ValueError:
                    continue
                if 1024 < port < 65536:
                    return port
        for v in obj.values():
            got = _adb_port_in(v, depth + 1)
            if got:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = _adb_port_in(v, depth + 1)
            if got:
                return got
    return None


def config_ports(root: Path) -> dict[int, int]:
    """每个实例在 MuMu 自己的配置文件里登记的 ADB 端口：{实例序号: 端口}。

    命令行工具问不出端口的时候用（2026-11-25 有用户的电脑上就是这样）：看 `vms/<实例文件夹>/configs/vm_config.json`
    里“adb”那一项的 host_port，实例序号是文件夹名最后的数字。读不到、看不懂就是空的——只读，不改任何东西。"""
    out: dict[int, int] = {}
    try:
        vdir = Path(root) / "vms"
        dirs = sorted(c for c in vdir.iterdir() if c.is_dir()) if vdir.is_dir() else []
    except OSError:
        return out
    for d in dirs:
        m = re.search(r"-(\d+)$", d.name)
        if not m:
            continue
        for name in ("vm_config.json", "customer_config.json"):
            try:
                obj = json.loads((d / "configs" / name).read_text(encoding="utf-8", errors="replace"))
            except (OSError, ValueError):
                continue
            port = _adb_port_in(obj)
            if port:
                out[int(m.group(1))] = port
                break
    return out


def instance_settings(cli: Path, index: int) -> tuple[dict[str, Any] | None, str]:
    obj, text = cli_json(cli, ["setting", "-v", str(index), "-a"])
    return (obj if isinstance(obj, dict) else None), text


def truthy(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes", "on"):
            return True
        if s in ("false", "0", "no", "off", ""):
            return False
    return None
