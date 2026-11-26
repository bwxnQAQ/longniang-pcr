"""检查更新：去 GitHub 看有没有新版本，有的话下载、换上，然后重新打开界面。

- 下载和更换只在你点了「检查更新」（或者界面上那条新版本提醒里的「更新」）的时候做；只连 GitHub（api.github.com 查版本，
  下载会被它带到 codeload.github.com），只认 REPO 这一个仓库。
  另外，打开界面时后台会自动查一次有没有新版本（tools/gui.py 的 check_new_version：只读版本标签，不下载、不换；
  config/settings.json 里写 "update_check": false 可以关）。
- 版本看的是仓库里的标签（v1.0、v1.0.1 ……），取最大的那个和本机的 longniang_pcr.__version__ 比。
- 换的只是程序本身：龙娘pcr.exe、README 这些最外层的文件，longniang_pcr、tools、assets、data 这几个文件夹里随版本发的文件。
  你的东西不动：config/settings.json、data/learned、logs、排查包、tools/dev。
- 换之前先把整包检查一遍（该有的文件在不在、版本号对不对、每个 .py 有没有语法错误），不对就不换；
  换下来的旧文件留在 %LOCALAPPDATA%\\longniang-pcr\\backup 里（留最近 3 次）；换到一半出错会自己恢复原样。
- 这个文件只用 Python 自带的库，不 import 工具本身的代码：就算程序别处坏了，也还能靠它更新回来。

命令行：龙娘pcr.exe update          检查，有新的就问一句再换
        龙娘pcr.exe update --check  只看有没有新的，不换
        龙娘pcr.exe update --yes    有新的就直接换，不问
"""
from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
REPO = "bwxnQAQ/longniang-pcr"             # 只认这一个仓库
API = "https://api.github.com"
UA = "longniang-pcr-updater"
EXE = "龙娘pcr.exe"
NEED = (EXE, "longniang_pcr/__init__.py", "tools/menu.py", "tools/gui.py", "tools/update.py")     # 新版本的包里一定要有的
DIRS = ("longniang_pcr", "tools", "assets", "data")       # 这几个文件夹里随版本发的文件会被换
SKIP = ("tools/dev/", "data/learned/")                    # 这些是你的 / 开发用的，不动
ONLY_IF_MISSING = ("config/settings.json",)               # 你可能改过：只在没有的时候补一份
MAX_ZIP = 300 << 20
MAX_FILES = 5000
MAX_UNPACK = 800 << 20
KEEP_BACKUPS = 3


class UpdateError(Exception):
    """没更新成（原因写给人看）。"""


# ---------- 版本 ----------

def parse_version(text: Any) -> tuple[int, ...] | None:
    """"v1.0" / "V1.0.1" / "1.2" → 能比大小的一组数；不是这种写法（比如带 -beta）返回 None。1.0 和 1.0.0 算同一个。"""
    m = re.fullmatch(r"[vV]?([0-9]{1,6}(?:\.[0-9]{1,6}){0,3})", str(text).strip())
    if not m:
        return None
    v = tuple(int(x) for x in m.group(1).split("."))
    while len(v) > 1 and v[-1] == 0:
        v = v[:-1]
    return v


def show(text: Any) -> str:
    return "V" + str(text).strip().lstrip("vV")


def local_version(root: Path) -> str:
    """文件夹里这一份是哪一版（直接读 longniang_pcr/__init__.py 里那一行，不 import）。读不到返回空串。"""
    try:
        text = (root / "longniang_pcr" / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r"""^__version__\s*=\s*["']([^"']+)["']""", text, re.M)
    return m.group(1) if m else ""


# ---------- 联网（只去 GitHub） ----------

def is_github(url: str) -> bool:
    u = urllib.parse.urlsplit(url)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host == "github.com" or host.endswith(".github.com") or host.endswith(".githubusercontent.com"))


class Net:
    """联网的那一层。allow 决定哪些地址能去——正式用的是 is_github；跳转去了别的地方也不跟。"""

    def __init__(self, api: str = API, allow: Callable[[str], bool] = is_github, timeout: float = 20.0):
        self.api, self.allow, self.timeout = api.rstrip("/"), allow, timeout
        net = self

        class OnlyAllowed(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
                if not net.allow(newurl):
                    raise UpdateError(f"被带去了 GitHub 以外的地址（{urllib.parse.urlsplit(newurl).hostname}），不去")
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        self.opener = urllib.request.build_opener(OnlyAllowed())     # 代理照系统的来（Windows 设置里的代理、HTTPS_PROXY）

    def open(self, url: str) -> Any:
        if not self.allow(url):
            raise UpdateError(f"不是 GitHub 的地址，不去：{url}")
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
        try:
            return self.opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise UpdateError(f"GitHub 上没找到（{REPO}）：仓库还没建好、不是公开的，或者这个版本被撤掉了") from None
            limited = e.code == 429 or (e.code == 403 and (e.headers.get("x-ratelimit-remaining") == "0" or e.headers.get("retry-after")))
            if limited:
                raise UpdateError("GitHub 说查得太频繁了（没登录的每小时只能查 60 次），过一会儿再点") from None
            raise UpdateError(f"GitHub 回的是 {e.code} {e.reason}（要是开着代理或者在公司 / 学校的网络里，可能是被它拦了）") from None
        except UpdateError:
            raise
        except (urllib.error.URLError, OSError) as e:
            why = getattr(e, "reason", e)
            raise UpdateError(f"连不上 GitHub（{why}）。检查网络，需要的话开着代理再点一次") from None

    def json(self, url: str) -> Any:
        with self.open(url) as r:
            try:
                return json.loads(r.read(8 << 20).decode("utf-8"))
            except (ValueError, OSError) as e:
                raise UpdateError(f"GitHub 回的东西看不懂（{e}）") from None

    def download(self, url: str, dst: Path, progress: Callable[[int, int], None] | None = None) -> int:
        part = dst.with_name(dst.name + ".part")
        done = 0
        try:
            with self.open(url) as r, open(part, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                while True:
                    buf = r.read(256 << 10)
                    if not buf:
                        break
                    done += len(buf)
                    if done > MAX_ZIP:
                        raise UpdateError("下载的东西大得不对，不要了")
                    f.write(buf)
                    if progress:
                        progress(done, total)
            if total and done != total:
                raise UpdateError(f"只下到 {done} / {total} 字节，网络断了")
            os.replace(part, dst)
        except (OSError, http.client.HTTPException) as e:
            raise UpdateError(f"下载到一半断了（{e}）") from None
        finally:
            try:
                part.unlink()
            except OSError:
                pass
        return done


def latest(net: Net, repo: str = REPO) -> tuple[tuple[int, ...], str] | None:
    """仓库里最大的那个版本标签：（能比大小的版本, 标签名）。一个都没有返回 None。"""
    tags = net.json(f"{net.api}/repos/{repo}/tags?per_page=100")
    best = None
    for t in tags if isinstance(tags, list) else []:
        name = str(t.get("name", "")) if isinstance(t, dict) else ""
        v = parse_version(name)
        if v is not None and (best is None or v > best[0]):
            best = (v, name)
    return best


def zip_url(net: Net, tag: str, repo: str = REPO) -> str:
    return f"{net.api}/repos/{repo}/zipball/refs/tags/{urllib.parse.quote(tag, safe='')}"


# ---------- 解压、检查 ----------

def entry_name(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if not info.flag_bits & 0x800:                # 没标 UTF-8 的中文名会被读成乱码，转回来
        try:
            name = name.encode("cp437").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name.replace("\\", "/")


def unpack(zip_path: Path, dst: Path) -> Path:
    """解压到 dst，返回里面工具所在的那一层（GitHub 的压缩包外面套着一层文件夹）。"""
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as e:
        raise UpdateError(f"下载下来的不是个好的压缩包（{e}）") from None
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNPACK:
            raise UpdateError("压缩包大得不对，不要了")
        if zf.testzip() is not None:
            raise UpdateError("压缩包是坏的（下载出了错），再点一次试试")
        for info in infos:
            name = entry_name(info)
            if name.endswith("/") or (info.external_attr >> 16) & 0o170000 == 0o120000:      # 文件夹；符号链接不要
                continue
            parts = name.split("/")
            if name.startswith("/") or any(p in ("", ".", "..") or ":" in p for p in parts):
                raise UpdateError(f"压缩包里有不对劲的路径（{name}），不要了")
            target = dst.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    for c in [dst] + sorted(p for p in dst.iterdir() if p.is_dir()):
        if (c / "longniang_pcr" / "__init__.py").is_file() and (c / "tools" / "menu.py").is_file():
            return c
    raise UpdateError("压缩包里没找到工具本身")


def check_package(pkg: Path, want: tuple[int, ...], have: tuple[int, ...] | None) -> str:
    """换之前把新版本的包看一遍，不对就抛 UpdateError。返回包里写的版本号。"""
    for n in NEED:
        if not (pkg / n).is_file():
            raise UpdateError(f"新版本的包里少了 {n}，不换")
    ver = local_version(pkg)
    v = parse_version(ver)
    if v is None or v != want:
        raise UpdateError(f"包里写的版本（{ver or '没写'}）和 GitHub 上的标签对不上，不换")
    if have is not None and v <= have:
        raise UpdateError("包里的版本不比现在的新，不换")
    if (pkg / EXE).read_bytes()[:2] != b"MZ":
        raise UpdateError(f"包里的 {EXE} 不是个程序，不换")
    for py in sorted(list((pkg / "longniang_pcr").rglob("*.py")) + list((pkg / "tools").glob("*.py"))):
        try:
            compile(py.read_bytes(), str(py), "exec")
        except (SyntaxError, ValueError) as e:
            raise UpdateError(f"新版本里的 {py.relative_to(pkg).as_posix()} 有语法错误（{getattr(e, 'msg', e)}），不换") from None
    return ver


# ---------- 换上 ----------

def plan(pkg: Path, root: Path) -> tuple[list[str], list[str]]:
    """（要换上的文件, 新版本里已经没有、要挪走的旧程序文件），都是相对路径。内容一模一样的不算。"""
    put, new = [], set()
    for p in sorted(pkg.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(pkg).as_posix()
        if rel.startswith(SKIP):
            continue
        if "/" not in rel:
            if rel.startswith("."):               # .gitignore 之类
                continue
        elif rel in ONLY_IF_MISSING:
            if (root / rel).exists():
                continue
        elif rel.split("/")[0] not in DIRS:
            continue
        new.add(rel)
        old = root / rel
        try:
            same = old.is_file() and old.stat().st_size == p.stat().st_size and old.read_bytes() == p.read_bytes()
        except OSError:
            same = False
        if not same:
            put.append(rel)
    stale = []
    mine = list((root / "longniang_pcr").rglob("*.py")) + list((root / "tools").glob("*.py"))
    for p in sorted(mine):
        rel = p.relative_to(root).as_posix()
        if rel not in new and "__pycache__" not in rel and not rel.startswith(SKIP):
            stale.append(rel)
    return put, stale


def _replace(tmp: Path, dst: Path) -> None:
    try:
        os.replace(tmp, dst)
    except PermissionError:                       # 正在运行的 exe 不能直接盖，但可以先改名让开（下次打开界面时会把 .old 清掉）
        old = dst.with_name(dst.name + ".old")
        try:
            old.unlink()
        except OSError:
            pass
        os.replace(dst, old)
        os.replace(tmp, dst)


def apply(pkg: Path, root: Path, backup: Path, put: list[str], stale: list[str]) -> None:
    """把 put 换上、stale 挪走；旧的都先存进 backup。中途出错：恢复原样，再把错误抛出去。"""
    done: list[tuple[str, bool]] = []             # （相对路径, 原来有没有这个文件）
    try:
        for rel in stale:
            b = backup / rel
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / rel, b)
            done.append((rel, True))
            (root / rel).unlink()
        for rel in put:
            dst = root / rel
            had = dst.is_file()
            if had:
                b = backup / rel
                b.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, b)
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".new")
            shutil.copyfile(pkg / rel, tmp)
            done.append((rel, had))
            _replace(tmp, dst)
    except Exception:
        for rel, had in reversed(done):
            try:
                tmp = (root / rel).with_name((root / rel).name + ".new")
                if tmp.exists():
                    tmp.unlink()
                if had:
                    shutil.copyfile(backup / rel, tmp)
                    _replace(tmp, root / rel)
                elif (root / rel).exists():
                    (root / rel).unlink()
            except OSError:
                pass
        raise


def prune(backups: Path, keep: int = KEEP_BACKUPS) -> None:
    try:
        old = sorted((p for p in backups.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    for p in old[:-keep] if keep > 0 else old:
        shutil.rmtree(p, ignore_errors=True)


def notes(pkg: Path, have: tuple[int, ...] | None, limit: int = 40) -> list[str]:
    """CHANGELOG.md 里比现在这版新的那几段（“## V1.0.1”这样的小标题分段）。没有这个文件返回空。"""
    try:
        lines = (pkg / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out, on = [], False
    for ln in lines:
        if ln.startswith("## "):                  # 小标题：是“## V1.0.1（日期）”这样的才看版本，别的小标题（和它下面的字）不要
            m = re.match(r"^##\s+[vV]?([0-9]+(?:\.[0-9]+)*)", ln)
            v = parse_version(m.group(1)) if m else None
            on = v is not None and (have is None or v > have)
        if on and ln.strip():
            out.append(ln.rstrip())
    return out[:limit]


# ---------- 入口 ----------

def runtime_dir() -> Path:
    base = os.environ.get("LNPCR_RUNTIME") or os.path.join(os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache")), "longniang-pcr")
    return Path(base)


def ask_yes(prompt: str) -> bool:
    try:
        s = input(prompt + " [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return s in ("", "y", "yes", "是", "好", "1")


def run(args: list[str], net: Net | None = None, root: Path = ROOT, rt: Path | None = None,
        ask: Callable[[str], bool] = ask_yes, say: Callable[[str], None] = print) -> int:
    check_only, auto = "--check" in args, "--yes" in args
    net = net or Net()
    rt = rt or runtime_dir()
    cur = local_version(root)
    have = parse_version(cur)
    say("")
    say(f"  检查更新：去 GitHub 看有没有新版本（github.com/{REPO}）。")
    say(f"  现在这一份是 {show(cur) if cur else '没写版本号的'}。")
    try:
        best = latest(net)
    except UpdateError as e:
        say(f"  × 没查成：{e}。")
        return 1
    if best is None:
        say("  GitHub 上还没有发布过版本。")
        return 0
    want, tag = best
    if have is not None and want <= have:
        say(f"  已经是最新的了（GitHub 上最新的是 {show(tag)}）。")
        return 0
    say(f"  发现新版本：{show(tag)}。")
    if check_only:
        say("  这一次只是看看，没有换。要换的话点「检查更新」，或者运行 龙娘pcr.exe update。")
        return 0
    if not auto and not ask("  现在下载并换上吗？换的只是程序本身，你的设置、运行记录、学到的角色数据都不动"):
        say("  没有更新。")
        return 0
    work = rt / "update"
    shutil.rmtree(work, ignore_errors=True)
    try:
        work.mkdir(parents=True, exist_ok=True)
        say("  下载中……")
        step = [0]

        def progress(done: int, total: int) -> None:
            mark = done * 4 // total if total else done >> 22          # 每 25%（不知道总大小就每 4 MB）说一次
            if mark != step[0]:
                step[0] = mark
                say(f"    已下载 {done / 1e6:.1f} MB" + (f"（{done * 100 // total}%）" if total else ""))

        size = net.download(zip_url(net, tag), work / "new.zip", progress)
        say(f"  下载好了（{size / 1e6:.1f} MB），检查一遍……")
        pkg = unpack(work / "new.zip", work / "new")
        ver = check_package(pkg, want, have)
        put, stale = plan(pkg, root)
        name, n = f"{show(cur) if cur else 'V0'}_{time.strftime('%Y%m%d-%H%M%S')}", 1
        backup = rt / "backup" / name
        while backup.exists():                    # 同一秒里的第二次：另起一个，不和上一次的留底混在一起
            n += 1
            backup = rt / "backup" / f"{name}_{n}"
        backup.mkdir(parents=True)
        apply(pkg, root, backup, put, stale)
        prune(rt / "backup")
        what = notes(pkg, have)
    except UpdateError as e:
        say(f"  × 没有更新：{e}。程序还是原来的样子。")
        return 1
    except OSError as e:
        say(f"  × 换文件的时候出错了（{e}），已经恢复成原来的样子。关掉别的占着这个文件夹的程序再试一次。")
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
    say(f"  换了 {len(put)} 个文件" + (f"，挪走了 {len(stale)} 个新版本里已经没有的旧文件" if stale else "") + f"；旧的留在 {backup}。")
    if what:
        say("")
        say("  这一版改了什么：")
        for ln in what:
            say("    " + ln)
    say("")
    say(f"  更新好了：{show(cur) if cur else '旧版'} → {show(ver)}")
    if os.environ.get("LNPCR_GUI") == "1":
        say("  界面马上自己重新打开。")
    else:
        say(f"  关掉这个窗口，重新双击“{EXE}”就是新版本了。")
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
