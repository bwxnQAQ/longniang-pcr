"""黎明界迷宫：五个区域一路走到最终首领跟前。

选路、编队、事件的做法见 tools/walk.py 和 README（这里就是 walk.py 加上 --full）。
V1.0（2026-11-25）的规矩：
  不带 --spend（界面上没勾「使用门票」）：只打一局，走到最终首领跟前就停下、任务结束——不撤退、不打最终首领、不用门票，交给人。
  带了 --spend（那个勾每次都要重新勾）：打掉最终首领、结算，每成功打完一局用 1 张门票（通行证）；--laps N 打几局（成功打完才算一局）；
      --settle N 分数线——走到最终首领跟前估分没到 N 的局撤退重打，不用门票、不算一局。
"""
from __future__ import annotations

import sys

import _common  # noqa: F401
from longniang_pcr import console

import walk

if __name__ == "__main__":
    if "--full" not in sys.argv:
        sys.argv.append("--full")
    code = walk.main()
    console.pause()
    sys.exit(code)
