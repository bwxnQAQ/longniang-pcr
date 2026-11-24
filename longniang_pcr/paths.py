"""项目路径与运行环境目录。

项目本体放在用户指定的文件夹（路径里有中文）。Python 运行环境、缓存、临时文件
放在纯英文目录（Windows 上是 %LOCALAPPDATA%\\longniang-pcr），绕开第三方库对
中文路径的各种坑。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_NAME = "longniang-pcr"


def runtime_dir() -> Path:
    """纯英文的运行环境目录（Python 环境、缓存、临时文件）。"""
    env = os.environ.get("LNPCR_RUNTIME")
    if env:
        p = Path(env)
    elif os.environ.get("LOCALAPPDATA"):
        p = Path(os.environ["LOCALAPPDATA"]) / RUNTIME_NAME
    else:  # 非 Windows（只在开发自测时用到）
        p = Path.home() / ".cache" / RUNTIME_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def tmp_dir() -> Path:
    p = runtime_dir() / "tmp"
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    p = PROJECT_ROOT / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def recordings_dir() -> Path:
    p = PROJECT_ROOT / "recordings"
    p.mkdir(parents=True, exist_ok=True)
    return p


def stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def new_run_dir(kind: str, stage: str = "stage0") -> Path:
    """每次运行一个独立文件夹：logs/<stage>/<时间>_<kind>/"""
    d = logs_dir() / stage / f"{stamp()}_{kind}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_ascii(s: object) -> bool:
    try:
        str(s).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False
