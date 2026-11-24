#!/bin/bash
# 做 龙娘pcr.exe（放到项目文件夹最外层）。在哪个系统上做都行，只要装了 Go（1.21 以上），不用联网、不用别的库。
# 图标 / 版本信息改了才需要前两步（要 Python + Pillow、llvm-rc、llvm-cvtres）；没改就只有最后一步 go build。
set -e
cd "$(dirname "$0")"
if [ "$1" = "res" ]; then
    python3 make_ico.py ../../../assets/logo.png launcher.ico
    llvm-rc /C 65001 /FO launcher.res launcher.rc
    llvm-cvtres /MACHINE:X64 /OUT:rsrc_windows_amd64.syso launcher.res
    rm -f launcher.res
fi
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags "-H windowsgui" -o ../../../龙娘pcr.exe .
echo "做好了：$(cd ../../.. && pwd)/龙娘pcr.exe"
