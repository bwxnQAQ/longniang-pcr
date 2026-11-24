"""紧急停止。

- 运行中随时按停止键（默认 F12，在哪个窗口按都行），工具在下一个动作之前停下；手指按着也会先抬起。
- 在黑窗口里按 Ctrl+C 也一样。
- 所有等待都切成小段，每段都看一眼停止标志，所以最多几十毫秒就能反应过来。
"""
from __future__ import annotations

import os
import sys
import threading
import time

VK = {f"F{i}": 0x6F + i for i in range(1, 13)}
VK.update({"PAUSE": 0x13, "SCROLL": 0x91, "END": 0x23, "HOME": 0x24})


class Stopped(Exception):
    """用户按了停止键，或者触发了某个上限。"""


class StopFlag:
    def __init__(self) -> None:
        self._ev = threading.Event()
        self.reason = ""

    def set(self, reason: str) -> None:
        if not self._ev.is_set():
            self.reason = reason
            self._ev.set()

    def is_set(self) -> bool:
        return self._ev.is_set()

    def check(self) -> None:
        if self._ev.is_set():
            raise Stopped(self.reason or "已停止")

    def sleep(self, seconds: float) -> None:
        """可以被打断的等待。"""
        end = time.perf_counter() + max(0.0, seconds)
        while True:
            self.check()
            left = end - time.perf_counter()
            if left <= 0:
                return
            time.sleep(min(0.03, left))


class HotkeyWatcher:
    """后台线程盯着停止键。只读键盘状态，不拦截按键，不影响你正常用电脑。"""

    def __init__(self, stop: StopFlag, key: str = "F12"):
        self.stop = stop
        self.key = key.upper()
        self.vk = VK.get(self.key)
        self._alive = False
        self._th: threading.Thread | None = None
        self.active = False

    def start(self) -> "HotkeyWatcher":
        stop_file = os.environ.get("LNPCR_STOP_FILE") or ""      # 图形界面的「停止」按钮：它写这个文件，这里看到就停
        user32 = None
        if sys.platform == "win32" and self.vk is not None:
            import ctypes
            user32 = ctypes.windll.user32
            user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            user32.GetAsyncKeyState.restype = ctypes.c_short
            user32.GetAsyncKeyState(self.vk)              # 清掉启动前的按键记录
            self.active = True
        if user32 is None and not stop_file:
            return self
        self._alive = True

        def run() -> None:
            n = 0
            while self._alive and not self.stop.is_set():
                if user32 is not None and user32.GetAsyncKeyState(self.vk) & 0x8000:
                    self.stop.set(f"你按了 {self.key}")
                    return
                n += 1
                if stop_file and n % 5 == 0 and os.path.exists(stop_file):
                    self.stop.set("你在界面上点了停止")
                    return
                time.sleep(0.03)

        self._th = threading.Thread(target=run, name="stop-key", daemon=True)
        self._th.start()
        return self

    def close(self) -> None:
        self._alive = False
