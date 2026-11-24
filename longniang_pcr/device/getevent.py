"""解析 `getevent`：模拟器里的原始触摸事件。

用途有两个：
1. 录制时拿到你手点的真实数据（按下、移动、抬起的精确时刻和坐标）；
2. 把工具发出的触摸和你手点的逐项对比，挑最像真人的触摸方式。

支持三种上报方式：多点触控协议 B（有 SLOT / TRACKING_ID）、协议 A（SYN_MT_REPORT）、
老式单点（ABS_X / ABS_Y + BTN_TOUCH）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT, SYN_MT_REPORT = 0x00, 0x02
BTN_TOUCH = 0x14A
ABS_X, ABS_Y = 0x00, 0x01
ABS_MT_SLOT = 0x2F
ABS_MT_TOUCH_MAJOR = 0x30
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36
ABS_MT_TRACKING_ID = 0x39
ABS_MT_PRESSURE = 0x3A

# [   12345.678901] /dev/input/event4: 0003 0035 000001f4
_LINE = re.compile(
    rb"\[\s*(\d+)\.(\d+)\]\s+(/dev/input/event\d+):\s+([0-9a-fA-F]{4})\s+([0-9a-fA-F]{4})\s+([0-9a-fA-F]{8})"
)


def parse_line(line: bytes) -> tuple[float, str, int, int, int] | None:
    """返回 (设备时间秒, 设备路径, type, code, value)；不是事件行就返回 None。"""
    m = _LINE.search(line)
    if not m:
        return None
    sec, frac, path, t, c, v = m.groups()
    dev_t = int(sec) + int(frac) / (10 ** len(frac))
    return dev_t, path.decode("ascii"), int(t, 16), int(c, 16), int(v, 16)


# ---------------------------------------------------------------- getevent -p

_ABS = re.compile(r"\b([0-9a-fA-F]{4})\s*:\s*value\s+(-?\d+),\s*min\s+(-?\d+),\s*max\s+(-?\d+)")


@dataclass
class InputDevice:
    path: str
    name: str = ""
    abs: dict[int, tuple[int, int]] = field(default_factory=dict)  # code -> (min, max)
    has_btn_touch: bool = False
    props: list[str] = field(default_factory=list)

    @property
    def is_touch(self) -> bool:
        mt = ABS_MT_POSITION_X in self.abs and ABS_MT_POSITION_Y in self.abs
        st = ABS_X in self.abs and ABS_Y in self.abs and self.has_btn_touch
        return mt or st

    @property
    def x_range(self) -> tuple[int, int] | None:
        return self.abs.get(ABS_MT_POSITION_X) or self.abs.get(ABS_X)

    @property
    def y_range(self) -> tuple[int, int] | None:
        return self.abs.get(ABS_MT_POSITION_Y) or self.abs.get(ABS_Y)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "is_touch": self.is_touch,
            "x_range": self.x_range,
            "y_range": self.y_range,
            "abs": {f"{k:04x}": v for k, v in self.abs.items()},
            "has_btn_touch": self.has_btn_touch,
            "props": self.props,
        }


def parse_devices(text: str) -> list[InputDevice]:
    """解析 `getevent -p` 的输出。"""
    devs: list[InputDevice] = []
    cur: InputDevice | None = None
    section = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        m = re.match(r"\s*add device \d+:\s*(\S+)", line)
        if m:
            cur = InputDevice(path=m.group(1))
            devs.append(cur)
            section = ""
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.startswith("name:"):
            cur.name = s[5:].strip().strip('"')
            continue
        if s.startswith("KEY"):
            section = "KEY"
        elif s.startswith("ABS"):
            section = "ABS"
        elif s.startswith("input props:"):
            section = "PROPS"
            continue
        elif re.match(r"^[A-Z]{2,4}\s*\(", s):
            section = "OTHER"
        if section == "KEY":
            body = s.split(":", 1)[1] if ":" in s and s.startswith("KEY") else s
            for tok in body.split():
                if re.fullmatch(r"[0-9a-fA-F]{4}", tok) and int(tok, 16) == BTN_TOUCH:
                    cur.has_btn_touch = True
        elif section == "ABS":
            for m2 in _ABS.finditer(s):
                cur.abs[int(m2.group(1), 16)] = (int(m2.group(3)), int(m2.group(4)))
        elif section == "PROPS":
            if s and s != "<none>":
                cur.props.append(s)
    return devs


# ---------------------------------------------------------------- 事件 -> 触点采样


@dataclass
class Sample:
    kind: str  # down / move / up
    dev: str
    slot: int
    dev_t: float
    host_t: float
    x: int | None
    y: int | None
    pressure: int | None = None
    major: int | None = None


class _Slot:
    __slots__ = ("tid", "x", "y", "p", "major", "active", "want_down", "want_up", "dirty")

    def __init__(self) -> None:
        self.tid = -1
        self.x: int | None = None
        self.y: int | None = None
        self.p: int | None = None
        self.major: int | None = None
        self.active = False
        self.want_down = False
        self.want_up = False
        self.dirty = False


class _DevState:
    def __init__(self) -> None:
        self.cur = 0
        self.slots: dict[int, _Slot] = {}
        self.saw_b = False  # 见过 TRACKING_ID
        self.saw_a = False  # 见过 SYN_MT_REPORT
        self.a_cur: dict[str, int] = {}
        self.a_points: list[dict[str, int]] = []
        self.btn: int | None = None
        self.btn_changed = False
        self.st_dirty = False

    def slot(self, i: int | None = None) -> _Slot:
        i = self.cur if i is None else i
        s = self.slots.get(i)
        if s is None:
            s = self.slots[i] = _Slot()
        return s


class TouchAssembler:
    """把一行行事件拼成触点采样（按下 / 移动 / 抬起）。"""

    def __init__(self) -> None:
        self.devs: dict[str, _DevState] = {}

    def feed(self, dev_t: float, path: str, etype: int, code: int, value: int, host_t: float) -> list[Sample]:
        st = self.devs.get(path)
        if st is None:
            st = self.devs[path] = _DevState()
        if etype == EV_ABS:
            if code == ABS_MT_SLOT:
                st.cur = value
            elif code == ABS_MT_TRACKING_ID:
                st.saw_b = True
                s = st.slot()
                if value == 0xFFFFFFFF:
                    s.want_up = True
                else:
                    s.tid = value
                    s.want_down = True
            elif code == ABS_MT_POSITION_X:
                s = st.slot()
                s.x = value
                s.dirty = True
                st.a_cur["x"] = value
            elif code == ABS_MT_POSITION_Y:
                s = st.slot()
                s.y = value
                s.dirty = True
                st.a_cur["y"] = value
            elif code == ABS_MT_PRESSURE:
                st.slot().p = value
                st.a_cur["p"] = value
            elif code == ABS_MT_TOUCH_MAJOR:
                st.slot().major = value
            elif code == ABS_X:
                st.slot(0).x = value
                st.st_dirty = True
            elif code == ABS_Y:
                st.slot(0).y = value
                st.st_dirty = True
            return []
        if etype == EV_KEY:
            if code == BTN_TOUCH:
                st.btn = value
                st.btn_changed = True
            return []
        if etype != EV_SYN:
            return []
        if code == SYN_MT_REPORT:
            st.saw_a = True
            if "x" in st.a_cur or "y" in st.a_cur:
                st.a_points.append(st.a_cur)
            st.a_cur = {}
            return []
        if code != SYN_REPORT:
            return []
        return self._flush(st, path, dev_t, host_t)

    def _flush(self, st: _DevState, path: str, dev_t: float, host_t: float) -> list[Sample]:
        out: list[Sample] = []

        def emit(kind: str, i: int, s: _Slot) -> None:
            out.append(Sample(kind, path, i, dev_t, host_t, s.x, s.y, s.p, s.major))

        if st.saw_b:
            for i, s in sorted(st.slots.items()):
                if s.want_down and not s.active:
                    s.active = True
                    emit("down", i, s)
                elif s.dirty and s.active and not s.want_up:
                    emit("move", i, s)
                if s.want_up:
                    if s.active:
                        emit("up", i, s)
                    s.active = False
                    s.tid = -1
                s.want_down = s.want_up = s.dirty = False
        elif st.saw_a:
            s = st.slot(0)
            if st.a_points:
                p = st.a_points[0]
                s.x = p.get("x", s.x)
                s.y = p.get("y", s.y)
                s.p = p.get("p", s.p)
                if not s.active:
                    s.active = True
                    emit("down", 0, s)
                else:
                    emit("move", 0, s)
            elif s.active:
                s.active = False
                emit("up", 0, s)
            st.a_points = []
            st.a_cur = {}
            for sl in st.slots.values():
                sl.dirty = False
        else:  # 老式单点
            s = st.slot(0)
            if st.btn_changed and st.btn == 1 and not s.active:
                s.active = True
                emit("down", 0, s)
            elif st.btn_changed and st.btn == 0 and s.active:
                s.active = False
                emit("up", 0, s)
            elif st.st_dirty and s.active:
                emit("move", 0, s)
            s.dirty = False
        st.btn_changed = False
        st.st_dirty = False
        return out


# ---------------------------------------------------------------- 采样 -> 手势


class GestureBuilder:
    """把采样拼成一次次完整的触摸（按下到抬起）。"""

    def __init__(self) -> None:
        self.open: dict[tuple[str, int], dict[str, Any]] = {}
        self.count = 0

    def feed(self, s: Sample) -> dict[str, Any] | None:
        key = (s.dev, s.slot)
        if s.kind == "down":
            self.open[key] = {
                "dev": s.dev,
                "slot": s.slot,
                "t_down_dev": s.dev_t,
                "t_down_host": s.host_t,
                "points": [[0.0, s.x, s.y, s.pressure]],
            }
            return None
        g = self.open.get(key)
        if g is None:
            return None
        g["points"].append([round(s.dev_t - g["t_down_dev"], 6), s.x, s.y, s.pressure])
        if s.kind != "up":
            return None
        del self.open[key]
        self.count += 1
        g["id"] = self.count
        g["t_up_dev"] = s.dev_t
        g["t_up_host"] = s.host_t
        g["press_ms"] = round((s.dev_t - g["t_down_dev"]) * 1000, 2)
        xs = [p[1] for p in g["points"] if p[1] is not None]
        ys = [p[2] for p in g["points"] if p[2] is not None]
        g["x0"], g["y0"] = (xs[0] if xs else None), (ys[0] if ys else None)
        g["x1"], g["y1"] = (xs[-1] if xs else None), (ys[-1] if ys else None)
        g["span"] = [max(xs) - min(xs) if xs else 0, max(ys) - min(ys) if ys else 0]
        g["n_points"] = len(g["points"])
        return g


AXIS_MODES = ("none", "rot90", "rot270", "rot180")


@dataclass
class AxisMap:
    """原始触摸坐标 -> 屏幕像素。

    MuMu 6（安卓 15）的 1920x1080 平板模式，在安卓里其实是一块 1080x1920 的竖屏转了 90 度：
    触摸屏的原始坐标是竖屏方向的，换算关系实测为 sx = ry，sy = 1080 - rx（即 mode="rot90"）。
    """

    x_range: tuple[int, int]
    y_range: tuple[int, int]
    width: int
    height: int
    mode: str = "none"

    @classmethod
    def auto(cls, x_range: tuple[int, int], y_range: tuple[int, int], width: int, height: int) -> "AxisMap":
        xs, ys = x_range[1] - x_range[0], y_range[1] - y_range[0]
        # 原始范围是“竖的”而画面是“横的”（或反过来），说明屏幕转了 90 度；两边一样长就看不出来，按不转算
        mode = "rot90" if xs != ys and (xs > ys) != (width > height) else "none"
        return cls(x_range, y_range, width, height, mode)

    def with_mode(self, mode: str) -> "AxisMap":
        return AxisMap(self.x_range, self.y_range, self.width, self.height, mode)

    def map(self, x: int | None, y: int | None) -> tuple[float | None, float | None]:
        if x is None or y is None:
            return None, None
        (x0, x1), (y0, y1) = self.x_range, self.y_range
        u = (x - x0) / (x1 - x0) if x1 > x0 else 0.0
        v = (y - y0) / (y1 - y0) if y1 > y0 else 0.0
        w, h = self.width, self.height
        if self.mode == "rot90":
            sx, sy = v * w, (1 - u) * h
        elif self.mode == "rot270":
            sx, sy = (1 - v) * w, u * h
        elif self.mode == "rot180":
            sx, sy = (1 - u) * w, (1 - v) * h
        else:
            sx, sy = u * w, v * h
        return round(sx, 2), round(sy, 2)
