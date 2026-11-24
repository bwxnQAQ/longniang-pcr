"""按饰品数量连续刷：一局一局打通（打掉最终首领、结算、开宝箱），把战利品读下来记账，目标没刷够就接着打。

每打通一局用 1 张门票（通行证）：不带 --spend（界面上不勾「使用门票」）就只说明、不动手。
每一局的走法和「打通一局」一样（见 tools/walk.py 和 README）。
"""
from __future__ import annotations

import sys

import _common  # noqa: F401
from longniang_pcr import console

import walk

if __name__ == "__main__":
    for flag in ("--full", "--farm"):
        if flag not in sys.argv:
            sys.argv.append(flag)
    code = walk.main()
    console.pause()
    sys.exit(code)
