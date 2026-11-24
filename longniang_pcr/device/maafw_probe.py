"""试用 MaaFramework 的控制器（开发计划里的“路线 A”）。

只在连接测试里用，用来和自己写的“路线 B”（ADB + MuMu 接口）对比，阶段 0 之后再定用哪条。
MaaFramework 的 Python 包名是 MaaFw，接口随版本会变，所以这里每一步都单独容错，
出错就把错误原样记进报告。
"""
from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path
from typing import Any

SCREENCAP = {
    "EmulatorExtras": 64,
    "RawByNetcat": 8,
    "RawWithGzip": 4,
    "Encode": 2,
    "EncodeToFileAndPull": 1,
}
INPUT = {
    "EmulatorExtras": 8,
    "Maatouch": 4,
    "MinitouchAndAdbKey": 2,
    "AdbShell": 1,
}


def version() -> str | None:
    try:
        from importlib import metadata

        for name in ("MaaFw", "maafw"):
            try:
                return metadata.version(name)
            except metadata.PackageNotFoundError:
                continue
    except Exception:
        pass
    return None


def run_with_timeout(fn: Any, timeout: float) -> Any:
    """MaaFramework 的等待没有超时，这里包一层，免得某种方式卡住拖死整个测试。"""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["v"] = fn()
        except BaseException as e:  # noqa: BLE001
            box["e"] = e

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise TimeoutError(f"超过 {timeout:.0f} 秒没有返回")
    if "e" in box:
        raise box["e"]
    return box.get("v")


def _to_plain(obj: Any) -> Any:
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    if hasattr(obj, "__dict__"):
        return {k: _to_plain(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)


class MaaProbe:
    def __init__(self, adb_path: str | Path, serial: str, user_dir: Path):
        self.adb_path = str(adb_path)
        self.serial = serial
        self.user_dir = Path(user_dir)
        self.ready = False
        self.error: str | None = None

    def init(self) -> bool:
        try:
            from maa.toolkit import Toolkit

            self.user_dir.mkdir(parents=True, exist_ok=True)
            Toolkit.init_option(str(self.user_dir))
            self.ready = True
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        return self.ready

    def find_devices(self, timeout: float = 90.0) -> list[dict[str, Any]]:
        """让 MaaFramework 自己找设备（它会给出它认为合适的截图 / 触摸方式和配置）。"""
        box: dict[str, Any] = {}

        def run() -> None:
            try:
                from maa.toolkit import Toolkit

                try:
                    box["v"] = Toolkit.find_adb_devices(self.adb_path)
                except TypeError:  # 老版本不接受参数
                    box["v"] = Toolkit.find_adb_devices()
            except Exception as e:  # noqa: BLE001
                box["e"] = f"{type(e).__name__}: {e}"

        th = threading.Thread(target=run, daemon=True)
        th.start()
        th.join(timeout)
        if th.is_alive():
            raise TimeoutError(f"find_adb_devices 超过 {timeout:.0f} 秒")
        if "e" in box:
            raise RuntimeError(box["e"])
        return [_to_plain(d) for d in (box.get("v") or [])]

    def controller(self, screencap: int, input_: int, config: dict[str, Any] | None, timeout: float = 60.0) -> tuple[Any, bool, str]:
        """建一个只用指定截图 / 触摸方式的控制器并连接。返回 (控制器, 是否连上, 说明)。"""
        from maa.controller import AdbController

        ctrl = AdbController(
            adb_path=self.adb_path,
            address=self.serial,
            screencap_methods=screencap,
            input_methods=input_,
            config=config or {},
        )
        note = ""
        try:
            ctrl.set_screenshot_use_raw_size(True)
        except Exception as e:  # noqa: BLE001
            note = f"set_screenshot_use_raw_size 不可用：{e}"
        box: dict[str, Any] = {}

        def run() -> None:
            try:
                job = ctrl.post_connection()
                job.wait()
                ok = getattr(job, "succeeded", None)
                if ok is None:
                    ok = getattr(ctrl, "connected", False)
                box["ok"] = bool(ok)
            except Exception as e:  # noqa: BLE001
                box["e"] = f"{type(e).__name__}: {e}"

        th = threading.Thread(target=run, daemon=True)
        th.start()
        th.join(timeout)
        if th.is_alive():
            return ctrl, False, f"连接超过 {timeout:.0f} 秒"
        if "e" in box:
            return ctrl, False, box["e"]
        return ctrl, box.get("ok", False), note

    @staticmethod
    def screencap(ctrl: Any) -> Any:
        job = ctrl.post_screencap()
        job.wait()
        img = None
        if hasattr(job, "get"):
            try:
                img = job.get()
            except Exception:
                img = None
        if img is None:
            img = ctrl.cached_image
        return img

    @staticmethod
    def wait(job: Any) -> bool:
        job.wait()
        ok = getattr(job, "succeeded", None)
        return True if ok is None else bool(ok)

    def bench_screencap(self, ctrl: Any, n: int = 8) -> tuple[list[float], Any]:
        times = []
        img = None
        for i in range(n + 1):
            t0 = time.perf_counter()
            img = self.screencap(ctrl)
            dt = (time.perf_counter() - t0) * 1000
            if i > 0:
                times.append(dt)
        return times, img

    def tail_log(self, max_bytes: int = 200_000) -> str:
        p = self.user_dir / "debug" / "maa.log"
        try:
            data = p.read_bytes()
            return data[-max_bytes:].decode("utf-8", "replace")
        except Exception:
            return ""
