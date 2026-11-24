"""你自己动手操作模拟器的时候，工具先让一让。【正式】

怎么知道你在操作：每隔几十毫秒问 Windows 三件事——
  1. 现在最前面的窗口是不是模拟器的窗口（看这个窗口属于哪个程序、标题是什么）；
  2. 鼠标是不是在这个窗口里面；
  3. 鼠标键是不是按着（或者刚按过）。
三件都是，才算“你在操作模拟器”。光是把鼠标挪过去看、在别的窗口里打字、滚轮，都不算。

工具自己的点击是从模拟器的接口进去的，不经过 Windows 的鼠标，按理不会把自己当成你；
保险起见，工具自己按下去的那一小段时间（和抬起后的 0.4 秒）里看到的鼠标键一律不算（own()）。
不装钩子、不读键盘、不记你点了哪里；只留一个时间：你上一次在模拟器窗口里按鼠标是什么时候。

为什么只看鼠标键：鼠标传感器有抖动的时候，“有输入”这件事整晚都会发生，拿它当依据会让工具在你睡着以后一直傻等。
按键是确凿的。漏掉一两下很快的点击也没关系——点之前工具本来就会再看一眼画面，变了就不点。

不是 Windows（或者问不到）的时候，这个模块什么都不做。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

MATCH = ("mumu", "nemu")                 # 模拟器窗口的程序名 / 标题里会有的字（不分大小写）；MuMu 12 是 MuMuPlayer / MuMuNxDevice，老版本是 NemuPlayer
QUIET = 12.0                             # 你停手这么多秒以后，工具才重新看画面接着来
POLL = 0.05                              # 多久问一次 Windows
OWN_GRACE = 0.4                          # 工具自己点完以后，这么多秒里看到的鼠标键不算你的

_EXE: dict[int, str] = {}                # 进程号 → 程序名（问一次记住）
_API: Any = None                         # (user32, kernel32)；False = 这台机器问不到


def _api() -> Any:
    """Windows 的两个系统库，各自单开一份（不去动别处正在用的那一份的函数原型），原型只设一次。"""
    global _API
    if _API is None:
        try:
            import ctypes
            from ctypes import wintypes
            u32 = ctypes.WinDLL("user32")                                  # type: ignore[attr-defined]
            k32 = ctypes.WinDLL("kernel32")                                # type: ignore[attr-defined]
            u32.GetForegroundWindow.restype = wintypes.HWND
            u32.GetForegroundWindow.argtypes = []
            u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            u32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            u32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            u32.GetAsyncKeyState.restype = ctypes.c_short
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            _API = (u32, k32)
        except Exception:
            _API = False
    return _API or None


def _exe_of(pid: int) -> str:
    """这个进程是哪个程序（只要文件名，小写）。问不到返回空。"""
    if pid in _EXE:
        return _EXE[pid]
    name = ""
    api = _api()
    if api is not None:
        try:
            import ctypes
            from ctypes import wintypes
            k32 = api[1]
            h = k32.OpenProcess(0x1000, False, pid)                        # PROCESS_QUERY_LIMITED_INFORMATION：只能问名字，别的什么都做不了
            if h:
                try:
                    buf = ctypes.create_unicode_buffer(520)
                    size = wintypes.DWORD(520)
                    if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                        name = buf.value.replace("/", "\\").rsplit("\\", 1)[-1].lower()
                finally:
                    k32.CloseHandle(h)
        except Exception:
            name = ""
    if len(_EXE) > 200:
        _EXE.clear()
    _EXE[pid] = name
    return name


def win_probe() -> dict[str, Any] | None:
    """问 Windows 一次。返回 {"exe", "title", "inside", "down"}；不是 Windows 或者问不到返回 None。"""
    api = _api()
    if api is None:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        u32 = api[0]
        hwnd = u32.GetForegroundWindow()
        if not hwnd:
            return None
        buf = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(hwnd, buf, 256)
        pid = wintypes.DWORD(0)
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = wintypes.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(rect))
        pt = wintypes.POINT()
        u32.GetCursorPos(ctypes.byref(pt))
        inside = rect.left <= pt.x < rect.right and rect.top <= pt.y < rect.bottom
        down = any(u32.GetAsyncKeyState(vk) & 0x8001 for vk in (1, 2, 4))          # 左、右、中键：现在按着，或者上次问过以后按过
        return {"exe": _exe_of(int(pid.value)), "title": buf.value, "inside": bool(inside), "down": bool(down)}
    except Exception:
        return None


class Hands:
    """盯着“你是不是在操作模拟器”。start() 起一个后台小线程不停地问；busy() = 你最近 quiet 秒里在模拟器窗口里按过鼠标。"""

    def __init__(self, match: Any = None, quiet: float = QUIET, poll: float = POLL,
                 probe: Callable[[], dict[str, Any] | None] | None = None, clock: Callable[[], float] = time.time):
        words = [str(x).strip().lower() for x in (match if isinstance(match, (list, tuple)) else MATCH) if str(x).strip()]
        self.match = tuple(words) or MATCH
        self.quiet = max(2.0, float(quiet))
        self.poll = max(0.02, float(poll))
        self.probe = probe or win_probe
        self.clock = clock
        self.last: float | None = None               # 你上一次在模拟器窗口里按鼠标的时间
        self.hits = 0                                # 一共看到几次（小结里用）
        self.waits: list[float] = []                 # 每次让了多少秒
        self.seen_emulator = False                   # 这次运行里见没见过模拟器窗口在最前面（没见过 = 窗口名字对不上，开工时提醒一句）
        self._own = False                            # 工具自己正按着
        self._own_until = 0.0
        self.own_seen = 0                            # 工具自己点的时候看到了几次鼠标键（不是 0 = 模拟器的触摸接口会带动 Windows 的鼠标键，记下来备查）
        self._thread: threading.Thread | None = None
        self._halt = threading.Event()

    def own(self, on: bool) -> None:
        """工具自己要点了（True）/ 点完了（False）：这段时间和之后的一小会儿里看到的鼠标键不算你的。"""
        if on:
            self._own = True
        else:
            self._own_until = self.clock() + OWN_GRACE
            self._own = False

    def ours(self, p: dict[str, Any]) -> bool:
        text = f"{p.get('exe') or ''} {p.get('title') or ''}".lower()
        return any(w in text for w in self.match)

    def sample(self) -> bool:
        """问一次。这一下算不算“你在操作模拟器”。"""
        try:
            p = self.probe()
        except Exception:
            p = None
        if not p or not self.ours(p):
            return False
        self.seen_emulator = True
        if not (p.get("inside") and p.get("down")):
            return False
        if self._own or self.clock() < self._own_until:
            self.own_seen += 1
            return False
        self.last = self.clock()
        self.hits += 1
        return True

    def since(self) -> float:
        return float("inf") if self.last is None else max(0.0, self.clock() - self.last)

    def busy(self) -> bool:
        return self.since() < self.quiet

    def left(self) -> float:
        """还要再等多少秒（你现在就停手的话）。"""
        return max(0.0, self.quiet - self.since())

    # ---- 后台线程 ----
    def start(self) -> bool:
        """开始盯。问不到 Windows（不是 Windows）就不起线程，返回 False。"""
        if self._thread is not None:
            return True
        if self.probe is win_probe and _api() is None:       # 不是 Windows：没什么可盯的
            return False
        self._halt.clear()
        self._thread = threading.Thread(target=self._run, name="hands", daemon=True)
        self._thread.start()
        return True

    def _run(self) -> None:
        while not self._halt.is_set():
            self.sample()
            self._halt.wait(self.poll)

    def stop(self) -> None:
        self._halt.set()
        t, self._thread = self._thread, None
        if t is not None:
            t.join(timeout=1.0)
