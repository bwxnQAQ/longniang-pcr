"""tools 里几个脚本共用的东西。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from longniang_pcr import paths  # noqa: E402
from longniang_pcr.device import maafw_probe  # noqa: E402

EXPECT_SIZE = (1920, 1080)
EXPECT_DPI = 280


def prepare_maafw(rep: Any, t: Any) -> dict[str, Any] | None:
    """初始化 MaaFramework，并让它自己找一遍设备。没装或出错返回 None。"""
    ver = maafw_probe.version()
    if ver is None:
        rep.warn("没装上 MaaFramework 的 Python 包（MaaFw）。它是可选项，不影响其他测试")
        return None
    rep.info(f"MaaFw 版本：{ver}")
    probe = maafw_probe.MaaProbe(t.adb.path, t.serial, paths.runtime_dir() / "maafw")
    if not probe.init():
        rep.bad("MaaFramework 初始化失败：" + (probe.error or "").splitlines()[0])
        rep.put("maafw_init_error", probe.error)
        return None
    toolkit_cfg = None
    found: list[dict[str, Any]] = []
    try:
        found = probe.find_devices()
        port = t.serial.rsplit(":", 1)[-1]
        for d in found:
            addr = str(d.get("address", ""))
            if addr == t.serial or addr.endswith(":" + port):
                toolkit_cfg = d.get("config") if isinstance(d.get("config"), dict) else None
                rep.ok(f"MaaFramework 自己也找到了这台模拟器（{d.get('name', '')} {addr}）")
                break
        else:
            rep.warn(f"MaaFramework 没自动认出这台模拟器（它找到 {len(found)} 台设备）。改用手写配置继续测")
    except Exception as e:  # noqa: BLE001
        rep.warn(f"MaaFramework 找设备出错：{e}")
    manual_cfg = {"extras": {"mumu": {"enable": True, "path": str(t.install.root), "index": int(t.index)}}}
    ctx = {"version": ver, "probe": probe, "found": found, "toolkit_cfg": toolkit_cfg, "manual_cfg": manual_cfg, "screencap_ok": {}}
    rep.put("maafw", {"version": ver, "found": found, "toolkit_cfg": toolkit_cfg, "manual_cfg": manual_cfg})
    return ctx


def maafw_cfgs(ctx: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    res = []
    if ctx.get("toolkit_cfg"):
        res.append(("自动配置", ctx["toolkit_cfg"]))
    res.append(("手写配置", ctx["manual_cfg"]))
    return res
