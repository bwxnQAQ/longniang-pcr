"""ADB 封装：只用模拟器自带的 adb.exe，所有调用都带超时。"""
from __future__ import annotations

import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class AdbError(RuntimeError):
    pass


def _decode(b: bytes) -> str:
    return b.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")


class Adb:
    def __init__(self, adb_path: str | Path, serial: str | None = None):
        self.path = str(adb_path)
        self.serial = serial

    def _base(self, use_serial: bool = True) -> list[str]:
        cmd = [self.path]
        if use_serial and self.serial:
            cmd += ["-s", self.serial]
        return cmd

    # ---- 基础调用 ----
    def start_server(self, timeout: float = 40.0) -> None:
        """先单独拉起 adb 服务。

        不接管输出：adb 服务是常驻后台进程，如果它继承了我们的管道，
        第一条带输出的命令会一直等不到结束。
        """
        try:
            subprocess.run(
                [self.path, "start-server"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            pass

    def raw(self, args: list[str], timeout: float = 20.0, use_serial: bool = True) -> tuple[int, bytes, bytes]:
        try:
            p = subprocess.run(
                self._base(use_serial) + list(args),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
            return p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:
            return -999, e.stdout or b"", (e.stderr or b"") + f"\n[超时 {timeout}s]".encode()
        except OSError as e:
            return -998, b"", str(e).encode("utf-8", "replace")

    def text(self, args: list[str], timeout: float = 20.0, use_serial: bool = True) -> str:
        rc, out, err = self.raw(args, timeout, use_serial)
        s = _decode(out)
        if rc != 0 or not s.strip():
            e = _decode(err).strip()
            if e:
                s = (s + "\n" + e).strip()
        return s.strip()

    def shell(self, cmd: str, timeout: float = 20.0) -> str:
        return self.text(["shell", cmd], timeout)

    def exec_out(self, cmd: str, timeout: float = 20.0) -> bytes:
        rc, out, err = self.raw(["exec-out", cmd], timeout)
        if rc != 0 and not out:
            raise AdbError(f"exec-out {cmd!r} 失败（{rc}）：{_decode(err).strip()[:300]}")
        return out

    # ---- 连接 ----
    def connect(self, timeout: float = 15.0) -> str:
        if not self.serial:
            return ""
        return self.text(["connect", self.serial], timeout, use_serial=False)

    def devices(self) -> list[tuple[str, str]]:
        out = self.text(["devices"], 15.0, use_serial=False)
        res = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] != "List" and not line.startswith("*"):
                res.append((parts[0], parts[1]))
        return res

    def state(self) -> str:
        return self.text(["get-state"], 10.0)

    def getprop(self, name: str) -> str:
        return self.shell(f"getprop {name}", 10.0).strip()

    # ---- 截图 ----
    def screencap_png(self, display: str | None = None, timeout: float = 25.0) -> np.ndarray:
        cmd = "screencap -p" + (f" -d {display}" if display else "")
        data = self.exec_out(cmd, timeout)
        i = data.find(PNG_MAGIC)
        if i < 0:
            raise AdbError(f"screencap -p 没有返回 PNG（{len(data)} 字节，开头 {data[:60]!r}）")
        img = cv2.imdecode(np.frombuffer(data[i:], np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise AdbError("screencap -p 返回的 PNG 解码失败")
        return img

    def screencap_raw(self, display: str | None = None, timeout: float = 25.0) -> np.ndarray:
        cmd = "screencap" + (f" -d {display}" if display else "")
        data = self.exec_out(cmd, timeout)
        return decode_raw_screencap(data)

    # ---- 长时间运行的命令 ----
    def popen(self, args: list[str]) -> subprocess.Popen:
        return subprocess.Popen(
            self._base(True) + list(args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )


def decode_raw_screencap(data: bytes) -> np.ndarray:
    """解析 `screencap` 的原始输出：头部 12 或 16 字节（宽、高、格式[、色彩空间]）+ RGBA。"""
    n = len(data)
    # 正常情况下头部就在开头；多显示器时前面可能多一行警告文字，所以往后找一小段
    for off in range(0, min(max(n - 16, 0), 2048) + 1):
        if n - off < 12:
            break
        w, h, _fmt = struct.unpack_from("<III", data, off)
        if not (100 <= w <= 10000 and 100 <= h <= 10000):
            continue
        need = w * h * 4
        for hdr in (16, 12):
            if n - off - hdr == need:
                arr = np.frombuffer(data, np.uint8, count=need, offset=off + hdr).reshape(h, w, 4)
                return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
    raise AdbError(f"screencap 原始数据解析失败（{n} 字节，开头 {data[:24].hex()}）")


class LineStream:
    """后台读一条长时间运行的 adb 命令，每来一行就回调 (到达时刻, 原始字节)。"""

    def __init__(self, adb: Adb, args: list[str], on_line: Callable[[float, bytes], None]):
        self.adb = adb
        self.args = args
        self.on_line = on_line
        self.proc: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None
        self.lines = 0
        self.error: str | None = None
        self.ended = False

    def start(self) -> "LineStream":
        self.proc = self.adb.popen(self.args)
        self.thread = threading.Thread(target=self._run, name="adb-stream", daemon=True)
        self.thread.start()
        return self

    def _run(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        try:
            for line in iter(self.proc.stdout.readline, b""):
                t = time.perf_counter()
                self.lines += 1
                try:
                    self.on_line(t, line)
                except Exception as e:  # noqa: BLE001
                    self.error = f"{type(e).__name__}: {e}"
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
        finally:
            self.ended = True

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.proc is not None:
            try:
                self.proc.kill()
            except Exception:
                pass
            try:
                self.proc.wait(timeout=3)
            except Exception:
                pass
        if self.thread is not None:
            self.thread.join(timeout=3)
