"""通知（2026-11-24，计划里阶段 4 的一项）：跑完了、停下了，在 Windows 右下角弹一条通知、响一声——挂机时不用一直盯着窗口。

做法：让系统自带的 PowerShell 弹一个托盘气泡（不用装任何东西）；文字通过环境变量传过去，不拼进命令里。
不是 Windows、PowerShell 起不来、被系统设置挡掉，都只是没有通知，不影响别的。设置里 notify: false 可以关。
"""
from __future__ import annotations

import os
import subprocess
import sys

_PS = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
       "$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
       "$n.ShowBalloonTip(15000, $env:LNPCR_TITLE, $env:LNPCR_BODY, [System.Windows.Forms.ToolTipIcon]::Info); "
       "Start-Sleep -Seconds 9; $n.Dispose()")


def command() -> list[str]:
    return ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", _PS]


def toast(title: str, body: str, sound: bool = True) -> bool:
    """弹一条通知（不等它）。发出去了返回 True。"""
    if sys.platform != "win32":
        return False
    ok = False
    try:
        env = dict(os.environ, LNPCR_TITLE=str(title)[:60], LNPCR_BODY=str(body).replace("\n", " ")[:220])
        subprocess.Popen(command(), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))      # noqa: S603
        ok = True
    except Exception:  # noqa: BLE001
        pass
    if sound:
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:  # noqa: BLE001
            pass
    return ok
