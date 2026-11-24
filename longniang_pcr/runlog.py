"""运行日志：每次运行一个文件夹，里面有文字记录、逐步事件和截图，出了问题可以回看。

logs/runs/<时间>_<名字>/
  log.txt        人能直接读的流水账
  events.jsonl   每一步一行（看到了什么页面、打算做什么、实际点了哪里）
  shots/         每一步操作前的截图（JPG）；出错时最后几帧另存为 PNG
"""
from __future__ import annotations

import collections
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from . import imgio, paths


class RunLog:
    def __init__(self, name: str, echo: bool = True, root: Path | None = None):
        base = root or (paths.logs_dir() / "runs")
        self.dir = base / f"{paths.stamp()}_{name}"
        (self.dir / "shots").mkdir(parents=True, exist_ok=True)
        self.echo = echo
        self.brief = False                           # 窗口里只写干了什么（2026-11-24 晚用户要的：不用写到点击坐标这么细）；log.txt 和 events.jsonl 照旧写全
        self.t0 = time.time()
        self._log = open(self.dir / "log.txt", "a", encoding="utf-8")
        self._ev = open(self.dir / "events.jsonl", "a", encoding="utf-8")
        self._ring: collections.deque[tuple[float, np.ndarray]] = collections.deque(maxlen=6)
        self._n = 0

    def say(self, text: str = "", detail: bool = False) -> None:
        """写一行。detail=True 是“细节”（点在屏幕哪个坐标、按了多少毫秒、地图挪了几个像素、中途的加载画面）：
        brief 打开时这种行只进 log.txt，不在窗口里（界面的“详细输出”）显示。"""
        if self.echo and not (detail and self.brief):
            print(text, flush=True)
        self._log.write(f"[{time.strftime('%H:%M:%S')}] {text}\n")
        self._log.flush()

    def did(self, text: str) -> None:
        """brief 打开时在窗口里写一行“干了什么”（比如 队伍编组：点「战斗开始」）。不进 log.txt——那里有同一下的细节行。"""
        if self.echo and self.brief:
            print(text, flush=True)

    def event(self, kind: str, /, **data: Any) -> None:
        rec = {"t": round(time.time() - self.t0, 3), "kind": kind}
        rec.update(data)
        self._ev.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self._ev.flush()

    def keep(self, img: np.ndarray) -> None:
        """记住最近几帧（只放内存），出错时一起存下来。"""
        self._ring.append((time.time() - self.t0, img))

    def shot(self, img: np.ndarray, tag: str, png: bool = False) -> str:
        self._n += 1
        name = f"{self._n:04d}_{tag}" + (".png" if png else ".jpg")
        imgio.imwrite(self.dir / "shots" / name, img, imgio.PNG_FAST if png else imgio.JPG_90)
        return name

    def dump_recent(self, tag: str = "last") -> list[str]:
        out = []
        for t, img in list(self._ring):
            out.append(self.shot(img, f"{tag}_{t:07.2f}s", png=True))
        self._ring.clear()
        return out

    def crash(self, exc: BaseException, **extra) -> None:
        """工具自己出错了（不是游戏画面的问题）：把出错的位置原样写进记录，再把最近几帧画面存下来。

        不这么做的话，错误只会在黑窗口里闪一下，记录里就只是“写到一半没了下文”（2026-11-17 就是这样）。
        """
        import traceback
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self.say(f"\n  × 工具自己出错了：{type(exc).__name__}: {exc}")
        self.say("  这是程序的毛病，不是你操作的问题。游戏停在当前画面，没有继续点。")
        for line in tb.rstrip().splitlines():
            self.say("    " + line)
        try:
            self.event("crash", error=f"{type(exc).__name__}: {exc}", trace=tb, **extra)
            self.dump_recent("crash")
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        for f in (self._log, self._ev):
            try:
                f.close()
            except Exception:  # noqa: BLE001
                pass


# ---- 记录占的地方（2026-11-24，挂机用）：一局的截图有两三百兆，连着打几晚就是几十个 G ----
def _run_dirs(root: Path | None = None) -> list[Path]:
    import re
    base = root or (paths.logs_dir() / "runs")
    if not base.is_dir():
        return []
    return sorted(d for d in base.iterdir() if d.is_dir() and re.match(r"^\d{8}-\d{6}_", d.name))


def usage(root: Path | None = None) -> tuple[int, int]:
    """logs/runs 里现在有几次运行的记录、一共占多少字节。"""
    dirs, total = _run_dirs(root), 0
    for d in dirs:
        for f in d.rglob("*"):
            try:
                if f.is_file():
                    total += f.stat().st_size
            except OSError:
                pass
    return len(dirs), total


def prune_shots(keep: int, root: Path | None = None, skip: Path | None = None) -> tuple[int, int]:
    """只留最近 keep 次运行的截图：更早的那些，把 shots 文件夹里的图删掉（log.txt 和 events.jsonl 留着，还能看当时干了什么）。
    keep <= 0 = 什么都不删（默认）。skip = 正在写的这一次。返回（清了几次运行的截图, 腾出多少字节）。只动 logs/runs 下面“日期-时间_名字”这种文件夹。"""
    if keep <= 0:
        return 0, 0
    dirs = [d for d in _run_dirs(root) if skip is None or d.resolve() != Path(skip).resolve()]
    cleared, freed = 0, 0
    for d in dirs[:-keep] if keep < len(dirs) else []:
        shots = d / "shots"
        if not shots.is_dir():
            continue
        n = 0
        for f in shots.iterdir():
            try:
                if f.is_file() and f.suffix.lower() in (".jpg", ".png"):
                    size = f.stat().st_size
                    f.unlink()
                    freed += size
                    n += 1
            except OSError:
                pass
        cleared += 1 if n else 0
    return cleared, freed
