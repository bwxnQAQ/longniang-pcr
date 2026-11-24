"""装依赖。只用标准库，所以在依赖还没装的时候也能跑。

必装：numpy、opencv-python、psutil、pillow
可选（装不上不影响阶段 0 的主要测试）：MaaFw（MaaFramework）、onnxruntime + rapidocr（OCR）
都装进 %LOCALAPPDATA%\\longniang-pcr\\venv，不动电脑上别的 Python。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

CORE = [("numpy", "numpy"), ("cv2", "opencv-python"), ("psutil", "psutil"), ("PIL", "pillow")]
OPTIONAL = [("maa", "MaaFw"), ("onnxruntime", "onnxruntime"), ("rapidocr", "rapidocr")]


def runtime_dir() -> Path:
    base = os.environ.get("LNPCR_RUNTIME") or os.path.join(os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache")), "longniang-pcr")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def has(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def ready() -> bool:
    """必装的依赖是不是都在（很快，不联网）。不在的话要走 ensure() 去装——那个要显示进度，得有窗口。"""
    return all(has(mod) for mod, _pkg in CORE)


def pip_install(pkgs: list[str]) -> bool:
    uv = os.environ.get("LNPCR_UV") or str(runtime_dir() / "bin" / "uv.exe")
    if os.path.exists(uv):
        cmd = [uv, "pip", "install", "--python", sys.executable] + pkgs
    else:
        cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"] + pkgs
    try:
        return subprocess.call(cmd) == 0
    except OSError as e:
        print(f"  安装命令没能运行：{e}")
        return False


def ensure(retry_optional: bool = False) -> bool:
    """确保依赖齐全。返回 False 表示必装的没装上。"""
    need = [pkg for mod, pkg in CORE if not has(mod)]
    if need:
        print(f"  [3/3] 安装依赖：{'、'.join(need)}（需要联网，一两分钟）")
        pip_install(need)
        importlib.invalidate_caches()
        still = [pkg for mod, pkg in CORE if not has(mod)]
        if still:
            print("")
            print(f"  这些依赖没装上：{'、'.join(still)}")
            print("  多半是网络问题。检查网络后再双击一次“龙娘pcr.exe”就会接着装。")
            return False
    marker = runtime_dir() / "optional_tried.json"
    tried: dict[str, str] = {}
    if marker.exists() and not retry_optional:
        try:
            tried = json.loads(marker.read_text(encoding="utf-8"))
        except Exception:
            tried = {}
    changed = False
    for mod, pkg in OPTIONAL:
        if has(mod):
            continue
        if tried.get(pkg) == "failed":
            continue
        print(f"  安装可选组件：{pkg}")
        ok = pip_install([pkg])
        importlib.invalidate_caches()
        tried[pkg] = "ok" if ok and has(mod) else "failed"
        changed = True
        if tried[pkg] == "failed":
            print(f"  （{pkg} 没装上，先跳过。它是可选的；做「首次设置」的时候会再试一次）")
    if changed or retry_optional:
        tried["_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            marker.write_text(json.dumps(tried, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
    return True


if __name__ == "__main__":
    sys.exit(0 if ensure("--retry" in sys.argv) else 1)
