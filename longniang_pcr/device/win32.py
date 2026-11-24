"""Windows 窗口相关：找模拟器画面在屏幕上的位置、最小化 / 恢复、记录鼠标点击。

鼠标记录只在录制期间开启，而且只保留落在模拟器画面里的左键操作；
落在别处的点击在回调里当场丢弃，不写进任何文件。
"""
from __future__ import annotations

import queue
import sys
import threading
import time
from typing import Any, Callable

IS_WIN = sys.platform == "win32"

if IS_WIN:
    import ctypes
    from ctypes import wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    LRESULT = ctypes.c_ssize_t
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", wt.POINT),
            ("mouseData", wt.DWORD),
            ("flags", wt.DWORD),
            ("time", wt.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    def _sig(func: Any, argtypes: list[Any], restype: Any) -> None:
        func.argtypes = argtypes
        func.restype = restype

    _sig(user32.IsWindow, [wt.HWND], wt.BOOL)
    _sig(user32.IsWindowVisible, [wt.HWND], wt.BOOL)
    _sig(user32.IsIconic, [wt.HWND], wt.BOOL)
    _sig(user32.GetWindowTextLengthW, [wt.HWND], ctypes.c_int)
    _sig(user32.GetWindowTextW, [wt.HWND, wt.LPWSTR, ctypes.c_int], ctypes.c_int)
    _sig(user32.GetClassNameW, [wt.HWND, wt.LPWSTR, ctypes.c_int], ctypes.c_int)
    _sig(user32.GetWindowRect, [wt.HWND, ctypes.POINTER(wt.RECT)], wt.BOOL)
    _sig(user32.GetClientRect, [wt.HWND, ctypes.POINTER(wt.RECT)], wt.BOOL)
    _sig(user32.ClientToScreen, [wt.HWND, ctypes.POINTER(wt.POINT)], wt.BOOL)
    _sig(user32.GetWindowThreadProcessId, [wt.HWND, ctypes.POINTER(wt.DWORD)], wt.DWORD)
    _sig(user32.GetForegroundWindow, [], wt.HWND)
    _sig(user32.GetAncestor, [wt.HWND, wt.UINT], wt.HWND)
    _sig(user32.WindowFromPoint, [wt.POINT], wt.HWND)
    _sig(user32.EnumWindows, [WNDENUMPROC, wt.LPARAM], wt.BOOL)
    _sig(user32.EnumChildWindows, [wt.HWND, WNDENUMPROC, wt.LPARAM], wt.BOOL)
    _sig(user32.ShowWindow, [wt.HWND, ctypes.c_int], wt.BOOL)
    _sig(user32.SetWindowsHookExW, [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD], wt.HHOOK)
    _sig(user32.CallNextHookEx, [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM], LRESULT)
    _sig(user32.UnhookWindowsHookEx, [wt.HHOOK], wt.BOOL)
    _sig(user32.GetMessageW, [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT], ctypes.c_int)
    _sig(user32.TranslateMessage, [ctypes.POINTER(wt.MSG)], wt.BOOL)
    _sig(user32.DispatchMessageW, [ctypes.POINTER(wt.MSG)], LRESULT)
    _sig(user32.PostThreadMessageW, [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM], wt.BOOL)
    _sig(kernel32.GetModuleHandleW, [wt.LPCWSTR], wt.HMODULE)
    _sig(kernel32.GetCurrentThreadId, [], wt.DWORD)
    _sig(kernel32.GetStdHandle, [wt.DWORD], wt.HANDLE)
    _sig(kernel32.GetConsoleMode, [wt.HANDLE, ctypes.POINTER(wt.DWORD)], wt.BOOL)
    _sig(kernel32.SetConsoleMode, [wt.HANDLE, wt.DWORD], wt.BOOL)

WH_MOUSE_LL = 14
WM_QUIT = 0x0012
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEWHEEL = 0x020A
GA_ROOT = 2
SW_SHOWNOACTIVATE = 4
SW_SHOWMINNOACTIVE = 7


# ---------------------------------------------------------------- 基础


def set_dpi_aware() -> str:
    """让坐标按真实像素算（系统缩放不是 100% 时尤其重要）。要在用任何窗口接口之前调用。"""
    if not IS_WIN:
        return "非 Windows"
    try:
        f = user32.SetProcessDpiAwarenessContext
        f.argtypes = [ctypes.c_void_p]
        f.restype = wt.BOOL
        if f(ctypes.c_void_p(-4)):
            return "per-monitor-v2"
    except Exception:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        return "per-monitor"
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
        return "system"
    except Exception:
        return "失败"


def disable_quick_edit() -> None:
    """关掉控制台的“快速编辑”：否则鼠标在黑窗口里点一下，程序就会被暂停。"""
    if not IS_WIN:
        return
    try:
        h = kernel32.GetStdHandle(wt.DWORD(-10 & 0xFFFFFFFF))
        mode = wt.DWORD()
        if kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            kernel32.SetConsoleMode(h, (mode.value & ~0x0040) | 0x0080)
    except Exception:
        pass


def code_pages() -> dict[str, Any]:
    if not IS_WIN:
        return {}
    try:
        return {
            "ansi": kernel32.GetACP(),
            "oem": kernel32.GetOEMCP(),
            "console_out": kernel32.GetConsoleOutputCP(),
            "console_in": kernel32.GetConsoleCP(),
        }
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def parse_hwnd(value: Any) -> int | None:
    """MuMu 命令行返回的窗口句柄是十六进制字符串（如 "000A0B5C"）。"""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value or None
    s = str(value).strip()
    try:
        v = int(s, 16)
    except ValueError:
        try:
            v = int(s)
        except ValueError:
            return None
    return v or None


def is_window(hwnd: int | None) -> bool:
    return bool(IS_WIN and hwnd and user32.IsWindow(hwnd))


def window_text(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 2)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(260)
    user32.GetClassNameW(hwnd, buf, 259)
    return buf.value


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    r = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return r.left, r.top, r.right, r.bottom


def client_area(hwnd: int) -> tuple[int, int, int, int] | None:
    """客户区在屏幕上的位置：(左, 上, 宽, 高)，单位是真实像素。"""
    r = wt.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    pt = wt.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None
    return pt.x, pt.y, r.right - r.left, r.bottom - r.top


def window_pid(hwnd: int) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_iconic(hwnd: int) -> bool:
    return bool(user32.IsIconic(hwnd))


def foreground() -> int | None:
    return user32.GetForegroundWindow() if IS_WIN else None


def root_window(hwnd: int | None) -> int | None:
    if not hwnd:
        return None
    return user32.GetAncestor(hwnd, GA_ROOT) or hwnd


def window_from_point(x: int, y: int) -> int | None:
    return user32.WindowFromPoint(wt.POINT(x, y))


def describe(hwnd: int | None) -> dict[str, Any]:
    if not is_window(hwnd):
        return {"hwnd": hwnd, "valid": False}
    assert hwnd is not None
    return {
        "hwnd": f"{hwnd:08X}",
        "valid": True,
        "title": window_text(hwnd),
        "class": class_name(hwnd),
        "rect": window_rect(hwnd),
        "client_area": client_area(hwnd),
        "visible": bool(user32.IsWindowVisible(hwnd)),
        "minimized": is_iconic(hwnd),
        "pid": window_pid(hwnd),
    }


def child_windows(hwnd: int) -> list[int]:
    res: list[int] = []

    def cb(h: int, _l: int) -> bool:
        res.append(h)
        return True

    user32.EnumChildWindows(hwnd, WNDENUMPROC(cb), 0)
    return res


def top_windows_of_pids(pids: set[int]) -> list[int]:
    res: list[int] = []

    def cb(h: int, _l: int) -> bool:
        if window_pid(h) in pids and user32.IsWindowVisible(h):
            res.append(h)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return res


def minimize(hwnd: int) -> None:
    user32.ShowWindow(hwnd, SW_SHOWMINNOACTIVE)


def restore(hwnd: int) -> None:
    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)


def guess_render_window(pids: set[int], aspect: float = 16 / 9) -> int | None:
    """命令行工具没给出画面窗口句柄时的兜底：在 MuMu 的窗口里找最大、比例接近 16:9 的那个。"""
    best, best_area = None, 0
    for top in top_windows_of_pids(pids):
        for h in [top] + child_windows(top):
            if not user32.IsWindowVisible(h):
                continue
            a = client_area(h)
            if not a or a[2] < 320 or a[3] < 180:
                continue
            if abs(a[2] / a[3] - aspect) > 0.03:
                continue
            if a[2] * a[3] > best_area:
                best, best_area = h, a[2] * a[3]
    return best


def make_hit_test(render_hwnd: int, main_hwnd: int | None) -> Callable[[int, int], tuple[int, int, int, int] | None]:
    """返回一个函数：屏幕坐标落在模拟器画面里（且没被别的窗口挡住）就给出画面区域，否则给 None。"""
    roots = {root_window(render_hwnd), root_window(main_hwnd) if main_hwnd else None}
    roots.discard(None)

    def hit(x: int, y: int) -> tuple[int, int, int, int] | None:
        area = client_area(render_hwnd)
        if not area or area[2] <= 0 or area[3] <= 0:
            return None
        left, top, w, h = area
        if not (left <= x < left + w and top <= y < top + h):
            return None
        under = window_from_point(x, y)
        if under and root_window(under) not in roots:
            return None
        return area

    return hit


# ---------------------------------------------------------------- 鼠标记录


class MouseHook:
    """记录模拟器画面里的鼠标左键按下 / 拖动 / 抬起，以及滚轮。

    回调里只做最少的事（取时间、判断是否在画面里、放进队列），拼成一次次点击的
    工作在别的线程做，避免拖慢系统鼠标。
    """

    def __init__(self, hit_test: Callable[[int, int], tuple[int, int, int, int] | None]):
        self.hit_test = hit_test
        self.events: "queue.SimpleQueue[tuple]" = queue.SimpleQueue()
        self.error: str | None = None
        self.count = 0
        self._down = False
        self._hook: Any = None
        self._cb: Any = None
        self._tid = 0
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, timeout: float = 5.0) -> bool:
        if not IS_WIN:
            self.error = "只能在 Windows 上使用"
            return False
        self._thread = threading.Thread(target=self._run, name="mouse-hook", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self._hook is not None and self.error is None

    def _proc(self, n_code: int, w_param: int, l_param: int) -> int:
        try:
            if n_code == 0 and (
                w_param == WM_LBUTTONDOWN
                or w_param == WM_LBUTTONUP
                or w_param == WM_MOUSEWHEEL
                or (w_param == WM_MOUSEMOVE and self._down)
            ):
                t = time.perf_counter()
                info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                x, y = info.pt.x, info.pt.y
                injected = bool(info.flags & 1)
                if w_param == WM_LBUTTONDOWN:
                    area = self.hit_test(x, y)
                    if area is not None:
                        self._down = True
                        self.count += 1
                        self.events.put(("down", t, x, y, area, injected))
                elif w_param == WM_LBUTTONUP:
                    if self._down:
                        self._down = False
                        self.events.put(("up", t, x, y, None, injected))
                elif w_param == WM_MOUSEMOVE:
                    self.events.put(("move", t, x, y, None, injected))
                else:  # 滚轮
                    area = self.hit_test(x, y)
                    if area is not None:
                        delta = ctypes.c_short((info.mouseData >> 16) & 0xFFFF).value
                        self.events.put(("wheel", t, x, y, area, delta))
        except Exception:
            pass
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _run(self) -> None:
        try:
            self._tid = kernel32.GetCurrentThreadId()
            self._cb = HOOKPROC(self._proc)
            self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._cb, kernel32.GetModuleHandleW(None), 0)
            if not self._hook:
                self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._cb, None, 0)
            if not self._hook:
                self.error = f"SetWindowsHookEx 失败（错误码 {ctypes.get_last_error()}）"
                self._hook = None
                return
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
            self._hook = None
            return
        finally:
            self._ready.set()
        msg = wt.MSG()
        while True:
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r in (0, -1):
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        try:
            user32.UnhookWindowsHookEx(self._hook)
        except Exception:
            pass

    def stop(self) -> None:
        if IS_WIN and self._tid and self._thread is not None and self._thread.is_alive():
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(timeout=2)


class ClickBuilder:
    """把鼠标事件拼成一次次点击 / 拖动，并换算成模拟器里的坐标。"""

    def __init__(self, width: int, height: int):
        self.width, self.height = width, height
        self.cur: dict[str, Any] | None = None
        self.count = 0

    def _map(self, x: int, y: int, area: tuple[int, int, int, int]) -> tuple[float, float]:
        left, top, w, h = area
        return round((x - left) * self.width / w, 2), round((y - top) * self.height / h, 2)

    def feed(self, ev: tuple) -> dict[str, Any] | None:
        kind, t, x, y, extra, flag = ev
        if kind == "wheel":
            ex, ey = self._map(x, y, extra)
            return {"type": "wheel", "t": round(t, 6), "x": ex, "y": ey, "delta": flag}
        if kind == "down":
            ex, ey = self._map(x, y, extra)
            self.cur = {
                "type": "click",
                "t_down": t,
                "area": list(extra),
                "screen0": [x, y],
                "x0": ex,
                "y0": ey,
                "path": [[0.0, ex, ey]],
                "injected": bool(flag),
            }
            return None
        if self.cur is None:
            return None
        g = self.cur
        ex, ey = self._map(x, y, tuple(g["area"]))
        g["path"].append([round(t - g["t_down"], 6), ex, ey])
        if kind != "up":
            return None
        self.cur = None
        self.count += 1
        g["id"] = self.count
        g["t_up"] = round(t, 6)
        g["press_ms"] = round((t - g["t_down"]) * 1000, 2)
        g["t_down"] = round(g["t_down"], 6)
        g["x1"], g["y1"] = ex, ey
        xs = [p[1] for p in g["path"]]
        ys = [p[2] for p in g["path"]]
        g["span"] = [round(max(xs) - min(xs), 2), round(max(ys) - min(ys), 2)]
        g["n_points"] = len(g["path"])
        return g
