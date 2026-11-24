"""扫描角色：先在游戏里把角色读一遍（原来的「读角色」），再去资料站更新名单和头像（原来的「更新角色」）。

抽到新角色、游戏出了新角色以后按一下就行（2026-11-24 深夜用户定的：两步合成一个键）。
读角色那一步要游戏开着、停在主界面底部的「角色」页；它只点第一张卡和右边的 ▶，别的不碰。
更新角色那一步不碰游戏，只读两个公开的资料站（pcr.satroki.tech、redive.estertion.win）。
"""
from __future__ import annotations

import sys

import _common  # noqa: F401
from longniang_pcr import console

import roster
import update_chars


def main() -> int:
    console.setup()
    prog = sys.argv[0]
    print("")
    print("  扫描角色：① 在游戏里把你有的角色读一遍 → ② 去资料站更新名单、属性和头像。一共七八分钟。")
    print("  请先把游戏停在主界面底部的「角色」页（角色一览）。")
    sys.argv = [prog, "--yes"]
    code = roster.main()
    if code != 0:
        print("\n  ① 没读成（上面写了原因），② 先不做。把游戏停到「角色」页以后再点一次「扫描角色」。")
        return code
    print("\n  ① 读完了，接着做 ②。")
    sys.argv = [prog]
    return update_chars.main()


if __name__ == "__main__":
    code = main()
    console.pause()
    sys.exit(code)
