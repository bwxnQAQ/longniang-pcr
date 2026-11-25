"""导出排查包：出了问题的时候点一下，把排查要用的东西打成一个 zip，发给作者就能查。

装进去的：最近几次运行的记录（log.txt、events.jsonl、summary.txt）和关键截图（停下 / 认不出 / 卡住时的画面、伤害报告、
战斗失败、最终首领跟前……再加最近一次运行的最后几十张），界面的日志，设置，学到的数据（打赢过的队、伤害记录这些小文件），
还有一页环境信息（系统、Python、几个组件的版本、模拟器分辨率）。
不装的：录制、整个头像库这类大文件；超过上限（默认 40 MB）就不再往里放截图。
注意：截图是游戏画面，上面看得到角色和玩家名字；环境信息里有项目文件夹的路径（带电脑的用户名）。发给别人之前知道一下。
只读文件、写一个 zip，不碰游戏。zip 在项目文件夹的「排查包」里。
"""
from __future__ import annotations

import json
import os
import platform
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import _common  # noqa: F401
from longniang_pcr import console, paths

RUNS = 3                    # 装最近几次运行
LAST_SHOTS = 40             # 最近一次运行：最后这么多张截图都装
MAX_MB = 40.0               # 整个包里的截图最多这么大（记录文件不算，它们压得很小）
KEY_SHOTS = ("halt", "unknown", "stuck", "unsure", "handover", "damage_report", "defeat", "before_final_boss", "lab_home", "team_",
             "enemy_", "loot", "first_run", "join_name", "result", "chest", "ime", "guild_not_found", "no_effect", "card_lost")
# “为什么停下”的那些截图：最要紧，额度先给它们（2026-11-25 有用户发来的包里，40 MB 被前面几十张编队截图占满了，
# 停下时存的 6 张“认不出的画面”一张都没装进来——偏偏要看的就是它）
STOP_SHOTS = ("unknown", "halt", "stuck", "unsure", "handover", "guild_not_found", "no_effect", "card_lost", "ime", "shop_unreadable", "first_run")
STOP_PER_GROUP = 2          # 同一次停下连着存的一串（“认不出的画面”一次存 6 张，几乎一样）：只装头尾两张
SMALL_JSON_MB = 3.0         # data/learned 里比这个大的 json 不装（头像库）
OUT_DIR = "排查包"


def pick_shots(run_dir: Path, last: int = 0) -> list[Path]:
    """这一次运行里要装的截图：名字里带关键字的 + 最后 last 张。按名字（也就是时间）排。"""
    shots = sorted((run_dir / "shots").glob("*.*")) if (run_dir / "shots").is_dir() else []
    keep = {p for p in shots if any(k in p.name for k in KEY_SHOTS)}
    keep |= set(shots[-last:]) if last > 0 else set()
    return sorted(keep)


def stop_shots(run_dir: Path) -> list[Path]:
    """这一次运行里“为什么停下”的截图。连着存的一串（序号挨着、名字同一类）只留头尾，省地方。"""
    shots = sorted((run_dir / "shots").glob("*.*")) if (run_dir / "shots").is_dir() else []
    out: list[Path] = []
    group: list[Path] = []

    def flush() -> None:
        if group:
            out.extend(group if len(group) <= STOP_PER_GROUP else [group[0], group[-1]])
            group.clear()

    last_no, last_kind = None, None
    for p in shots:
        kind = next((k for k in STOP_SHOTS if k in p.name), None)
        if kind is None:
            continue
        head = p.name.split("_", 1)[0]
        no = int(head) if head.isdigit() else None
        if not (group and kind == last_kind and no is not None and last_no is not None and no == last_no + 1):
            flush()
        group.append(p)
        last_no, last_kind = no, kind
    flush()
    return out


def ordered_shots(run_dirs_newest_first: list[Path]) -> list[tuple[Path, Path]]:
    """要装的截图，按要紧的程度排好（额度从前往后给）：
    1. 每次运行里“为什么停下”的那些（最新的运行在前）；2. 最近一次运行的最后几十张；3. 各次运行里别的关键截图（最新的在前）。"""
    out: list[tuple[Path, Path]] = []
    seen: set[Path] = set()

    def take(rd: Path, shots: list[Path]) -> None:
        for p in shots:
            if p not in seen:
                seen.add(p)
                out.append((rd, p))

    for rd in run_dirs_newest_first:
        take(rd, stop_shots(rd))
    if run_dirs_newest_first:
        rd = run_dirs_newest_first[0]
        shots = sorted((rd / "shots").glob("*.*")) if (rd / "shots").is_dir() else []
        take(rd, list(reversed(shots[-LAST_SHOTS:])))            # 从最后一张往前给：离停下越近的越先装
    for rd in run_dirs_newest_first:
        take(rd, list(reversed(pick_shots(rd, 0))))              # 别的关键截图也是离结束近的先装
    return out


def env_info(root: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "system": platform.platform(), "python": sys.version.split()[0],
                            "project": str(root), "path_has_non_ascii": any(ord(c) > 127 for c in str(root))}
    try:
        from importlib import metadata

        for pkg in ("numpy", "opencv-python", "opencv-python-headless", "rapidocr", "rapidocr-onnxruntime", "onnxruntime", "MaaFw"):
            try:
                info.setdefault("packages", {})[pkg] = metadata.version(pkg)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    try:                                             # 哪一版（V1.0 起有版本号）
        import longniang_pcr

        info["version"] = str(getattr(longniang_pcr, "__version__", ""))
    except Exception:  # noqa: BLE001
        pass
    try:                                             # 代码有没有被动过：记最新改动的那个文件和时间
        files = [p for d in ("longniang_pcr", "tools") for p in (root / d).rglob("*.py") if "dev" not in p.parts]
        newest = max(files, key=lambda p: p.stat().st_mtime)
        info["code"] = {"files": len(files), "newest": str(newest.relative_to(root)), "newest_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(newest.stat().st_mtime))}
    except Exception:  # noqa: BLE001
        pass
    return info


def build(root: Path | None = None, out: Path | None = None, runs: int = RUNS, max_mb: float = MAX_MB, say=print) -> Path:
    """打包，返回 zip 的路径。"""
    root = Path(root or paths.PROJECT_ROOT)
    out_dir = Path(out or root / OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"龙娘pcr_排查包_{time.strftime('%Y%m%d-%H%M%S')}.zip"
    budget = max_mb * 1024 * 1024
    used, skipped, counts = 0.0, 0, {"runs": 0, "shots": 0, "files": 0}
    run_root = root / "logs" / "runs"
    run_dirs = sorted([p for p in run_root.iterdir() if p.is_dir()], key=lambda p: p.name)[-runs:] if run_root.is_dir() else []
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        def add(p: Path, arc: str) -> None:
            try:
                z.write(p, arc)
                counts["files"] += 1
            except OSError:
                pass

        newest_first = list(reversed(run_dirs))
        for rd in newest_first:
            counts["runs"] += 1
            for name in ("log.txt", "events.jsonl", "summary.txt"):
                if (rd / name).is_file():
                    add(rd / name, f"runs/{rd.name}/{name}")
        for rd, shot in ordered_shots(newest_first):  # 截图的额度按要紧的程度给：先是“为什么停下”的，再是最近一次的最后几十张，最后才是别的
            try:
                size = shot.stat().st_size
            except OSError:
                continue
            if used + size > budget:
                skipped += 1
                continue
            add(shot, f"runs/{rd.name}/shots/{shot.name}")
            used += size
            counts["shots"] += 1
        gui_log = root / "logs" / "gui.log"
        if gui_log.is_file():
            try:
                data = gui_log.read_bytes()[-200_000:]
                z.writestr("gui.log", data)
            except OSError:
                pass
        if (root / "config" / "settings.json").is_file():
            add(root / "config" / "settings.json", "config/settings.json")
        learned = root / "data" / "learned"
        big = []
        for p in sorted(learned.glob("*.json")) if learned.is_dir() else []:
            if p.stat().st_size <= SMALL_JSON_MB * 1024 * 1024:
                add(p, f"learned/{p.name}")
            else:
                big.append(f"{p.name}（{p.stat().st_size / 1e6:.1f} MB，没装）")
        info = env_info(root)
        info.update(runs=[rd.name for rd in run_dirs], shots=counts["shots"], shots_skipped=skipped, big_files=big)
        z.writestr("环境信息.json", json.dumps(info, ensure_ascii=False, indent=1))
    say(f"    装了最近 {counts['runs']} 次运行的记录、{counts['shots']} 张截图" + (f"（另有 {skipped} 张因为超过 {max_mb:g} MB 没装）" if skipped else "")
        + "，还有设置、学到的数据和环境信息。")
    return target


def main() -> int:
    console.setup()
    print("")
    print("  导出排查包：把最近几次运行的记录、关键截图、设置和环境信息打成一个 zip。只读文件，不碰游戏。")
    try:
        target = build()
    except Exception as e:  # noqa: BLE001
        print(f"  × 没打成：{type(e).__name__}: {e}")
        return 1
    print(f"  ✓ 打好了：{target}（{target.stat().st_size / 1e6:.1f} MB）")
    print("  把这个 zip 发给作者（QQ 群 891856490），并说一下“当时在做什么、哪里不对”。")
    print("  提醒：里面有游戏截图（看得到角色和玩家名字）和项目文件夹的路径，发之前知道一下。")
    try:
        os.startfile(str(target.parent))             # noqa: S606  打开那个文件夹，方便拿文件（只在 Windows 上有）
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    code = main()
    console.pause()
    sys.exit(code)
