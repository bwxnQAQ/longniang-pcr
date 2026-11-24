"""设备层：对上只暴露“截图”和“按下 / 移动 / 抬起”。

阶段 0 实测后定的路线：MuMu 自带接口截图（约 10 毫秒）+ MuMu 自带接口触摸（坐标就是屏幕坐标，
事件格式和鼠标点击一致）；ADB 截图只作兜底。没有 MuMu 接口就不发触摸——`adb input` 那种
“按下和抬起同时完成”的点法特征太明显，宁可不点。
"""
from __future__ import annotations

import time
from typing import Any, Protocol

import numpy as np

from . import discover
from .nemu_ipc import call_with_timeout


class DeviceError(RuntimeError):
    pass


class DeviceLike(Protocol):
    size: tuple[int, int]

    def screenshot(self) -> np.ndarray: ...
    def down(self, x: int, y: int) -> None: ...
    def move(self, x: int, y: int) -> None: ...
    def up(self) -> None: ...


class _Quiet:
    """discover 里的函数需要一个“报告”对象；正式运行时不需要那么啰嗦。"""

    def __init__(self, log: Any | None = None):
        self.log = log
        self.data: dict[str, Any] = {}

    def _w(self, text: str) -> None:
        if self.log is not None:
            self.log.say(text)

    def say(self, text: str = "") -> None: self._w(text)
    def head(self, text: str) -> None: pass
    def info(self, text: str) -> None: pass
    def ok(self, text: str) -> None: pass
    def warn(self, text: str) -> None: self._w("  ! " + text)
    def bad(self, text: str) -> None: self._w("  × " + text)
    def put(self, key: str, value: Any) -> None: self.data[key] = value


class Device:
    def __init__(self, target: discover.Target, nemu: Any | None, grabber: discover.Grabber):
        self.target = target
        self.nemu = nemu
        self.grabber = grabber
        self.size: tuple[int, int] = (0, 0)
        self._pressed = False
        self._fail = 0

    # ---- 连接 ----
    @classmethod
    def open(cls, log: Any | None = None) -> "Device":
        rep = _Quiet(log)
        try:
            t = discover.find_target(rep)
        except discover.DiscoverError as e:
            raise DeviceError(str(e)) from e
        nemu = discover.open_nemu(t, rep)
        grab = discover.Grabber(t, nemu)
        if not grab.pick(rep):
            raise DeviceError("截不到模拟器的画面（MuMu 接口和 ADB 都试过了）。先跑一次“连接测试”看看哪里不对。")
        dev = cls(t, nemu, grab)
        img = dev.screenshot()
        dev.size = (img.shape[1], img.shape[0])
        return dev

    @property
    def can_touch(self) -> bool:
        return self.nemu is not None

    def describe(self) -> dict[str, Any]:
        return {"serial": self.target.serial, "index": self.target.index, "android": self.target.android,
                "size": list(self.size), "screenshot": self.grabber.name,
                "touch": "MuMu 接口" if self.can_touch else "无", "game": self.target.game}

    # ---- 截图 ----
    def screenshot(self) -> np.ndarray:
        last: Exception | None = None
        for attempt in range(3):
            try:
                if self.grabber.name == "MuMu 接口":
                    img = call_with_timeout(self.grabber.grab, 5.0)
                else:
                    img = self.grabber.grab()
                if isinstance(img, np.ndarray) and img.ndim == 3 and img.shape[0] > 100:
                    self._fail = 0
                    return img
                last = DeviceError("截图是空的")
            except Exception as e:  # noqa: BLE001
                last = e
            time.sleep(0.2 * (attempt + 1))
        self._fail += 1
        if self.grabber.name == "MuMu 接口" and self._fail >= 2:
            self.grabber.nemu = None                      # MuMu 接口连续失败：退到 ADB 截图
            if self.grabber.pick(None):
                return self.grabber.grab()
        raise DeviceError(f"截图失败：{type(last).__name__}: {last}")

    # ---- 触摸 ----
    def _clamp(self, x: float, y: float) -> tuple[int, int]:
        w, h = self.size
        return int(min(max(round(x), 1), w - 2)), int(min(max(round(y), 1), h - 2))

    def down(self, x: float, y: float) -> None:
        if self.nemu is None:
            raise DeviceError("MuMu 触摸接口没连上，不发触摸。")
        xi, yi = self._clamp(x, y)
        self.nemu.touch_down(xi, yi)
        self._pressed = True

    def move(self, x: float, y: float) -> None:
        if self.nemu is None or not self._pressed:
            return
        xi, yi = self._clamp(x, y)
        self.nemu.touch_down(xi, yi)                      # 按住时再发一次 touch_down 就是移动（阶段 0 实测）

    def up(self) -> None:
        if self.nemu is not None and self._pressed:
            self.nemu.touch_up()
        self._pressed = False

    # ---- 游戏还在不在前台（闪退恢复用，2026-11-24）：只问系统“现在最前面是哪个应用”、启动游戏，不碰游戏本身 ----
    def foreground(self) -> str | None:
        """现在在最前面的应用的包名（用 ADB 问安卓系统）。问不到返回 None。"""
        import re
        try:
            out = self.target.adb.shell("dumpsys activity activities | grep -E 'ResumedActivity'", 8.0)
        except Exception:  # noqa: BLE001
            return None
        m = re.search(r"\s([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)/", out or "")
        return m.group(1) if m else None

    def launch_game(self, restart: bool = False) -> bool:
        """启动游戏（和在桌面上点一下图标一样）。restart = 先把它彻底关掉再开（卡死时用）。发出去了返回 True。"""
        pkg = self.target.game
        if not pkg:
            return False
        try:
            if restart:
                self.target.adb.shell(f"am force-stop {pkg}", 10.0)
                time.sleep(1.0)
            self.target.adb.shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1", 15.0)
            return True
        except Exception:  # noqa: BLE001
            return False

    def close(self) -> None:
        try:
            self.up()
        finally:
            if self.nemu is not None:
                try:
                    self.nemu.disconnect()
                except Exception:  # noqa: BLE001
                    pass
