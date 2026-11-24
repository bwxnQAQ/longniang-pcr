"""MuMu 自带的截图 / 触控接口（external_renderer_ipc.dll，MAA 里叫“截图增强”“触控增强”）。

函数签名按 MuMu SDK 的公开用法写（MAA、ALAS 等工具都在用）：
    int  nemu_connect(const wchar_t* path, int index)        返回 >0 的句柄，0 表示失败
    void nemu_disconnect(int handle)
    int  nemu_get_display_id(int handle, const char* pkg, int appIndex)
    int  nemu_capture_display(int handle, unsigned displayid, int buffer_size,
                              int* width, int* height, unsigned char* pixels)   返回 0 表示成功
    int  nemu_input_event_touch_down(int handle, int displayid, int x, int y)
    int  nemu_input_event_touch_up(int handle, int displayid)
    int  nemu_input_event_finger_touch_down(int handle, int displayid, int finger_id, int x, int y)
    int  nemu_input_event_finger_touch_up(int handle, int displayid, int finger_id)

2026-11-16 在 MuMu 6.8.8（安卓 15 内核）上实测：
  - DLL 用 nx_device\\15.0\\shell\\sdk\\ 下的那份，nemu_connect 的路径参数传安装根目录
  - 截图约 10 ms 一张；像素是 RGBA、上下颠倒（capture() 里已经翻正并转成 BGR）
  - 触摸坐标直接用画面坐标（1920x1080），不用旋转
  - touch_down / touch_up 在模拟器里产生的内核触摸事件，和鼠标点击产生的是同一个设备、同样的格式
    （没有压力值）；finger_touch_down 用的是另一个触点槽位（12）
  - 再次调用 touch_down 就是“移动”
"""
from __future__ import annotations

import ctypes
import os
import struct
import sys
import threading
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

KNOWN_FUNCS = [
    "nemu_connect",
    "nemu_disconnect",
    "nemu_get_display_id",
    "nemu_capture_display",
    "nemu_input_text",
    "nemu_input_event_touch_down",
    "nemu_input_event_touch_up",
    "nemu_input_event_key_down",
    "nemu_input_event_key_up",
    "nemu_input_event_finger_touch_down",
    "nemu_input_event_finger_touch_up",
]


class NemuError(RuntimeError):
    pass


def call_with_timeout(fn: Callable[..., Any], timeout: float, *args: Any) -> Any:
    """在后台线程里调用，防止 DLL 卡死把整个测试拖住。"""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn(*args)
        except BaseException as e:  # noqa: BLE001
            box["error"] = e

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise NemuError(f"调用超过 {timeout:.0f} 秒没有返回")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def pe_exports(dll_path: str | Path) -> list[str]:
    """读 DLL 的导出函数名（只读文件，不加载）。"""
    data = Path(dll_path).read_bytes()
    if data[:2] != b"MZ":
        raise ValueError("不是 PE 文件")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe : pe + 4] != b"PE\0\0":
        raise ValueError("PE 头不对")
    n_sections = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    dd = opt + (112 if magic == 0x20B else 96)
    exp_rva, exp_size = struct.unpack_from("<II", data, dd)
    if not exp_rva:
        return []
    sections = []
    sec = opt + opt_size
    for i in range(n_sections):
        vsize, vaddr, rsize, rptr = struct.unpack_from("<IIII", data, sec + i * 40 + 8)
        sections.append((vaddr, max(vsize, rsize), rptr))

    def off(rva: int) -> int:
        for vaddr, size, rptr in sections:
            if vaddr <= rva < vaddr + size:
                return rva - vaddr + rptr
        raise ValueError(f"RVA {rva:#x} 不在任何节里")

    e = off(exp_rva)
    n_names = struct.unpack_from("<I", data, e + 24)[0]
    names_rva = struct.unpack_from("<I", data, e + 32)[0]
    names = []
    base = off(names_rva)
    for i in range(min(n_names, 4096)):
        p = off(struct.unpack_from("<I", data, base + i * 4)[0])
        end = data.index(b"\0", p)
        names.append(data[p:end].decode("ascii", "replace"))
    return names


class NemuIpc:
    def __init__(self, dll_path: str | Path):
        self.dll_path = Path(dll_path)
        self.lib: Any = None
        self.handle = 0
        self.folder: str | None = None
        self.index: int | None = None
        self.display_id = 0
        self.width = 0
        self.height = 0
        self._buf: Any = None
        self._dll_dir: Any = None

    # ---- 加载 ----
    def load(self) -> "NemuIpc":
        if sys.platform != "win32":
            raise NemuError("只能在 Windows 上使用")
        try:
            self._dll_dir = os.add_dll_directory(str(self.dll_path.parent))
        except Exception:
            self._dll_dir = None
        try:
            self.lib = ctypes.CDLL(str(self.dll_path))
        except OSError:
            self.lib = ctypes.CDLL(str(self.dll_path), winmode=0)
        L = self.lib
        c_int, c_uint = ctypes.c_int, ctypes.c_uint
        L.nemu_connect.argtypes = [ctypes.c_wchar_p, c_int]
        L.nemu_connect.restype = c_int
        L.nemu_disconnect.argtypes = [c_int]
        L.nemu_disconnect.restype = None
        L.nemu_capture_display.argtypes = [
            c_int,
            c_uint,
            c_int,
            ctypes.POINTER(c_int),
            ctypes.POINTER(c_int),
            ctypes.c_void_p,
        ]
        L.nemu_capture_display.restype = c_int
        optional = {
            "nemu_get_display_id": [c_int, ctypes.c_char_p, c_int],
            "nemu_input_event_touch_down": [c_int, c_int, c_int, c_int],
            "nemu_input_event_touch_up": [c_int, c_int],
            "nemu_input_event_finger_touch_down": [c_int, c_int, c_int, c_int, c_int],
            "nemu_input_event_finger_touch_up": [c_int, c_int, c_int],
        }
        for name, argtypes in optional.items():
            if hasattr(L, name):
                f = getattr(L, name)
                f.argtypes = argtypes
                f.restype = c_int
        return self

    def has(self, name: str) -> bool:
        return self.lib is not None and hasattr(self.lib, name)

    # ---- 连接 ----
    def connect(self, folder: str | Path, index: int, timeout: float = 10.0) -> bool:
        h = call_with_timeout(self.lib.nemu_connect, timeout, str(folder), int(index))
        if not h or h <= 0:
            return False
        self.handle = int(h)
        self.folder = str(folder)
        self.index = int(index)
        return True

    def disconnect(self) -> None:
        if self.lib is not None and self.handle:
            try:
                self.lib.nemu_disconnect(self.handle)
            except Exception:
                pass
        self.handle = 0

    def get_display_id(self, package: str, app_index: int = 0) -> int | None:
        if not self.has("nemu_get_display_id"):
            return None
        return int(call_with_timeout(self.lib.nemu_get_display_id, 10.0, self.handle, package.encode("utf-8"), app_index))

    # ---- 截图 ----
    def resolution(self) -> tuple[int, int]:
        w, h = ctypes.c_int(0), ctypes.c_int(0)
        ret = self.lib.nemu_capture_display(self.handle, self.display_id, 0, ctypes.byref(w), ctypes.byref(h), None)
        if ret != 0:
            raise NemuError(f"读取分辨率失败（返回 {ret}）")
        if w.value <= 0 or h.value <= 0 or w.value > 10000 or h.value > 10000:
            raise NemuError(f"分辨率不合理：{w.value}x{h.value}")
        if (w.value, h.value) != (self.width, self.height) or self._buf is None:
            self.width, self.height = w.value, h.value
            self._buf = (ctypes.c_ubyte * (self.width * self.height * 4))()
        return self.width, self.height

    def capture_rgba(self) -> np.ndarray:
        """原始画面（RGBA，上下颠倒），是缓冲区的视图：下次截图会被覆盖。"""
        if self._buf is None:
            self.resolution()
        w, h = ctypes.c_int(self.width), ctypes.c_int(self.height)
        ret = self.lib.nemu_capture_display(
            self.handle, self.display_id, self.width * self.height * 4, ctypes.byref(w), ctypes.byref(h), self._buf
        )
        if ret != 0:
            raise NemuError(f"截图失败（返回 {ret}）")
        if (w.value, h.value) != (self.width, self.height):
            self._buf = None  # 分辨率变了，下次重新申请
            raise NemuError(f"分辨率变了：{self.width}x{self.height} -> {w.value}x{h.value}")
        return np.frombuffer(self._buf, dtype=np.uint8).reshape(self.height, self.width, 4)

    def capture(self) -> np.ndarray:
        """BGR 图（已翻正），独立于内部缓冲区。"""
        rgba = self.capture_rgba()
        return cv2.flip(cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR), 0)

    # ---- 触摸（坐标怎么对应屏幕，由触摸测试实测决定）----
    def touch_down(self, x: int, y: int) -> int:
        return int(self.lib.nemu_input_event_touch_down(self.handle, self.display_id, int(x), int(y)))

    def touch_up(self) -> int:
        return int(self.lib.nemu_input_event_touch_up(self.handle, self.display_id))

    def finger_down(self, finger: int, x: int, y: int) -> int:
        return int(self.lib.nemu_input_event_finger_touch_down(self.handle, self.display_id, int(finger), int(x), int(y)))

    def finger_up(self, finger: int) -> int:
        return int(self.lib.nemu_input_event_finger_touch_up(self.handle, self.display_id, int(finger)))
