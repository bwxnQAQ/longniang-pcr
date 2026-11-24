"""控制台小工具：中文输出、防误暂停、提问。"""
from __future__ import annotations

import faulthandler
import sys


def setup() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    try:
        faulthandler.enable()
    except Exception:
        pass
    try:
        from .device import win32

        win32.set_dpi_aware()
        win32.disable_quick_edit()
    except Exception:
        pass


def ask(prompt: str, default: str = "") -> str:
    try:
        s = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return default
    return s or default


def yes(prompt: str, default: bool = False) -> bool:
    s = ask(prompt + (" [Y/n] " if default else " [y/N] ")).lower()
    if not s:
        return default
    return s in ("y", "yes", "是", "好", "1")


def pause(text: str = "按回车继续……") -> None:
    """跑完以后等一下再关黑窗口。从图形界面启动的（LNPCR_GUI=1）不等：界面自己留着输出，这一项做完就结束。"""
    import os

    if os.environ.get("LNPCR_GUI") == "1":
        return
    try:
        input(text)
    except (EOFError, KeyboardInterrupt):
        pass
