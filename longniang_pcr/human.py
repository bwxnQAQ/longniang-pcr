"""拟人化执行：让每一下点击的落点、按压时长、节奏都像人，而且“随机得有习惯”。

初始参数来自阶段 0 的录制（2026-11-16，667 次点击）：
- 按压多在 65～108 毫秒，中位数 81 毫秒；
- 画面稳定到点下去，中位数约 0.3 秒。
其余还是计划里的初始值，后面录得多了再换。所有等待都能被紧急停止打断。
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field, asdict
from typing import Any

from .stop import StopFlag

Box = tuple[float, float, float, float]          # x, y, w, h（设备像素）


@dataclass
class HumanParams:
    press_median_ms: float = 81.0                # 按压时长：对数正态
    press_sigma: float = 0.16
    press_min_ms: float = 55.0
    press_max_ms: float = 190.0
    drift_prob: float = 0.55                     # 按住时手指轻微挪动的概率
    drift_px: float = 2.5
    spread: float = 1 / 6                        # 落点标准差 = 按钮宽高的 1/6
    margin: float = 0.12                         # 离按钮边缘至少留这么多（比例）
    bias_x: float = 0.0                          # “个人习惯”：落点整体偏移（按钮宽高的比例），每台电脑固定
    bias_y: float = 0.06
    react_median_s: float = 0.32                 # 画面稳定后到点击
    react_sigma: float = 0.38
    react_min_s: float = 0.18
    react_max_s: float = 1.2
    think_min_s: float = 1.5                     # 需要判断的地方（选遗物、选路）
    think_max_s: float = 6.0
    between_min_s: float = 0.2                   # 同一画面连续两次操作之间
    between_max_s: float = 0.7
    idle_prob: float = 0.02                      # 偶尔发呆
    idle_min_s: float = 5.0
    idle_max_s: float = 30.0
    fatigue_per_hour: float = 0.07               # 连续运行越久越慢
    swipe_min_s: float = 0.2
    swipe_max_s: float = 0.6
    step_ms: float = 8.0                         # 滑动时两个触摸点之间的间隔

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "HumanParams":
        p = cls()
        for k, v in (d or {}).items():
            if hasattr(p, k) and isinstance(v, (int, float)):
                setattr(p, k, float(v))
        return p

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TapRecord:
    x: int
    y: int
    press_ms: float
    drift: int
    box: Box | None = None
    label: str = ""
    t: float = field(default_factory=time.time)


class Human:
    def __init__(self, dev: Any, params: HumanParams | None = None, stop: StopFlag | None = None,
                 rng: random.Random | None = None, idle: bool = True):
        self.dev = dev
        self.p = params or HumanParams()
        self.stop = stop or StopFlag()
        self.rng = rng or random.Random()
        self.idle = idle                         # 单步模式下关掉“发呆”
        self.t0 = time.time()
        self.taps = 0

    # ---- 时间 ----
    def _fatigue(self) -> float:
        return 1.0 + self.p.fatigue_per_hour * (time.time() - self.t0) / 3600.0

    def _lognorm(self, median: float, sigma: float, lo: float, hi: float) -> float:
        for _ in range(8):
            v = median * math.exp(self.rng.gauss(0.0, sigma))
            if lo <= v <= hi:
                return v
        return min(max(median, lo), hi)

    def react_delay(self, think: bool = False) -> float:
        if think:
            base = self.rng.uniform(self.p.think_min_s, self.p.think_max_s)
        else:
            base = self._lognorm(self.p.react_median_s, self.p.react_sigma, self.p.react_min_s, self.p.react_max_s)
        return base * self._fatigue()

    def press_ms(self) -> float:
        return self._lognorm(self.p.press_median_ms, self.p.press_sigma, self.p.press_min_ms, self.p.press_max_ms)

    def wait(self, seconds: float) -> None:
        self.stop.sleep(seconds)

    def between(self) -> None:
        self.wait(self.rng.uniform(self.p.between_min_s, self.p.between_max_s) * self._fatigue())

    # ---- 落点 ----
    def pick_point(self, box: Box) -> tuple[int, int]:
        x, y, w, h = box
        cx = x + w * (0.5 + self.p.bias_x)
        cy = y + h * (0.5 + self.p.bias_y)
        lo_x, hi_x = x + w * self.p.margin, x + w * (1 - self.p.margin)
        lo_y, hi_y = y + h * self.p.margin, y + h * (1 - self.p.margin)
        for _ in range(12):
            px = self.rng.gauss(cx, w * self.p.spread)
            py = self.rng.gauss(cy, h * self.p.spread)
            if lo_x <= px <= hi_x and lo_y <= py <= hi_y:
                return int(round(px)), int(round(py))
        return int(round(min(max(cx, lo_x), hi_x))), int(round(min(max(cy, lo_y), hi_y)))

    # ---- 动作 ----
    def tap(self, box: Box, label: str = "") -> TapRecord:
        """在 box 里点一下：按下 →（也许轻微挪一下）→ 抬起。"""
        self.stop.check()
        x, y = self.pick_point(box)
        ms = self.press_ms()
        drift = 0
        try:
            self.dev.down(x, y)
            if self.rng.random() < self.p.drift_prob:
                n = self.rng.choice((1, 1, 2, 3))
                cx, cy = float(x), float(y)
                slices = sorted(self.rng.uniform(0.15, 0.9) for _ in range(n))
                used = 0.0
                for frac in slices:
                    time.sleep(max(0.0, (frac - used) * ms / 1000.0))
                    used = frac
                    cx += self.rng.uniform(-1, 1) * self.p.drift_px / n
                    cy += self.rng.uniform(-0.6, 1) * self.p.drift_px / n
                    self.dev.move(cx, cy)
                    drift += 1
                time.sleep(max(0.0, (1.0 - used) * ms / 1000.0))
            else:
                time.sleep(ms / 1000.0)              # 按压只有几十毫秒，不拆开，保证时长准确
        finally:
            self.dev.up()
        self.taps += 1
        rec = TapRecord(x, y, ms, drift, box, label)
        if self.idle and self.rng.random() < self.p.idle_prob:
            self.wait(self.rng.uniform(self.p.idle_min_s, self.p.idle_max_s))
        return rec

    def swipe(self, start: tuple[float, float], end: tuple[float, float], duration: float | None = None,
              on_tick: Any = None, tick_s: float = 0.05, hold_end: float | None = None) -> None:
        """拖动：轨迹带一点弧度，先加速后减速，结尾稍微过头再回来。

        on_tick：拖动过程中每隔 tick_s 秒调用一次（用来边拖边截图，量画面挪了多少）。
        hold_end：抬手前按住不动这么久（秒），画面就不会被“甩”出去继续滑。
        """
        self.stop.check()
        x0, y0 = start
        x1, y1 = end
        dist = math.hypot(x1 - x0, y1 - y0)
        if duration is None:
            duration = min(self.p.swipe_max_s, max(self.p.swipe_min_s, 0.18 + dist / 2600.0)) * self.rng.uniform(0.9, 1.15)
        nx, ny = (-(y1 - y0) / (dist + 1e-6), (x1 - x0) / (dist + 1e-6))
        bow = self.rng.uniform(-0.06, 0.06) * dist
        over = self.rng.uniform(0.0, 0.025) * dist
        ox, oy = ((x1 - x0) / (dist + 1e-6) * over, (y1 - y0) / (dist + 1e-6) * over)
        steps = max(6, int(duration * 1000.0 / self.p.step_ms))
        last_tick = time.perf_counter()
        try:
            self.dev.down(x0, y0)
            t_start = time.perf_counter()
            for i in range(1, steps + 1):
                u = i / steps
                e = u * u * (3 - 2 * u)              # 先慢、中间快、后慢
                px = x0 + (x1 + ox - x0) * e + nx * bow * math.sin(math.pi * u) + self.rng.uniform(-0.7, 0.7)
                py = y0 + (y1 + oy - y0) * e + ny * bow * math.sin(math.pi * u) + self.rng.uniform(-0.7, 0.7)
                self.dev.move(px, py)
                if on_tick is not None and time.perf_counter() - last_tick >= tick_s:
                    on_tick()
                    last_tick = time.perf_counter()
                target = t_start + duration * u
                time.sleep(max(0.0, target - time.perf_counter()))
                if self.stop.is_set():
                    break
            if over > 1.0 and not self.stop.is_set():
                for k in range(1, 4):                # 回到真正的终点
                    self.dev.move(x1 + ox * (1 - k / 3), y1 + oy * (1 - k / 3))
                    time.sleep(self.p.step_ms / 1000.0)
            hold = self.rng.uniform(0.03, 0.09) if hold_end is None else hold_end
            t_hold = time.perf_counter() + hold
            while time.perf_counter() < t_hold and not self.stop.is_set():
                if on_tick is not None:
                    on_tick()
                time.sleep(min(tick_s, max(0.0, t_hold - time.perf_counter())))
        finally:
            self.dev.up()
        self.stop.check()
