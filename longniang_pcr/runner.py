"""运行器：看一眼 → 认页面 → （单步模式下问你）→ 拟人点击 → 记日志。

守住几条线：
- 认不出的画面不动手，等一会儿还认不出就把最近几帧存下来、请你在模拟器里手动点过去（工具自己还是不碰），
  认出下一个画面以后接着跑；等到上限还没人管才停（2026-11-26 用户定的；Limits.unknown_wait = 0 时和以前一样直接停）；
- 单步模式下每一下点击都先告诉你要点哪里，等你回车；你确认之后还会再看一眼画面，变了就不点；
- 有步数和时间上限；随时可以按停止键；
- 自动跑的时候你自己动手点了模拟器：先停手，等你停够一会儿再重新看画面接着来（hands.py）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from .human import Human
from .runlog import RunLog
from .stop import StopFlag, Stopped
from .vision.pages import NORM_H, NORM_W, PageBook, PageResult

NBox = tuple[float, float, float, float]         # 1280×720 坐标的 x, y, w, h


class Halt(Exception):
    """拿不准，停下来交给人。"""


@dataclass
class Limits:
    max_taps: int = 60
    max_seconds: float = 600.0
    unknown_timeout: float = 20.0                # 认不出的画面等这么久以后，请你来点（unknown_wait = 0 时到这里就停）
    unknown_wait: float = 0.0                    # 请你来点以后最多再等多少秒；到了还认不出就停。0 = 不等（tools/walk.py 按设置给，默认 1800）
    wait_timeout: float = 90.0                   # 加载、数据连接这类等待最多这么久
    poll: float = 0.22
    settle: float = 0.25                         # 一个页面至少连续出现这么久才算数
    settle_pages: dict[str, float] = field(default_factory=lambda: {"map": 1.2})
    # ↑ 地图要多等一会儿：对话框弹出来之前，地图会先露出来将近 1 秒（2026-11-16 演练里实测）


REACT_FLOOR = 0.12          # 画面早就看到了、想的时间也够了：点之前最少还是留这么一小下


@dataclass
class Seen:
    img: np.ndarray
    res: PageResult
    t: float = field(default_factory=time.time)      # 这一眼是什么时候看的（点之前“反应 / 想一想”的时间从这一刻算起）

    @property
    def page(self) -> str:
        return self.res.page


def _default_ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return "q"


class Runner:
    def __init__(self, dev: Any, book: PageBook, human: Human, log: RunLog, stop: StopFlag,
                 step_mode: bool = True, limits: Limits | None = None,
                 ask: Callable[[str], str] | None = None):
        self.dev, self.book, self.human, self.log, self.stop = dev, book, human, log, stop
        self.step_mode = step_mode
        self.limits = limits or Limits()
        self.ask = ask or _default_ask
        self.t0 = time.time()
        self.taps = 0
        self.step_no = 0
        self.recovery: Any = None                    # 挂机恢复（afk.Recovery）：认不出的画面先让它看一眼；没挂就和以前一样
        self.hands: Any = None                       # 你手动操作模拟器时先让一让（hands.Hands）；没挂就和以前一样
        self.hands_poll = 0.5
        self.settled: str | None = None              # 流程刚自己等过这个页面稳定（见 observe）：下一次看到它不用再多看一眼
        self.hand_asks: list[float] = []             # 认不出画面、请你手动点过去的那几次：每次等了多少秒（流程靠它知道“画面被你动过”）
        self.on_ask: Callable[[str], None] | None = None     # 请你来点的那一刻叫一声（右下角通知）；没挂就只写在记录里

    # ---- 上限 ----
    def _check_limits(self) -> None:
        self.stop.check()
        if time.time() - self.t0 > self.limits.max_seconds:
            raise Halt(f"到时间上限了（{self.limits.max_seconds:.0f} 秒）")
        if self.taps >= self.limits.max_taps:
            raise Halt(f"到点击次数上限了（{self.limits.max_taps} 次）")

    def check(self) -> None:
        """流程里自己轮询画面时调用：检查停止键和上限。"""
        self._check_limits()

    def yield_to_hands(self, page: str = "") -> bool:
        """你在手动操作模拟器：等到你停手够久再接着。等过返回 True——调用的地方必须重新看画面，不能照着之前看到的去点。
        单步模式不管这个：每一下本来就要你点头。"""
        h = self.hands
        if h is None or self.step_mode or not h.busy():
            return False
        t = last = time.time()
        self.log.say(f"      你在操作模拟器，我先不动；你停手 {h.quiet:.0f} 秒以后我重新看画面接着来。（停止键照常能用）")
        self.log.event("hands", what="wait", page=page)
        while h.busy():
            self.stop.check()
            self.stop.sleep(self.hands_poll)
            if time.time() - last >= 120:
                last = time.time()
                self.log.say(f"      …还在等你停手（已经让了 {last - t:.0f} 秒）")
        waited = time.time() - t
        self.t0 += waited                            # 让你的这段时间不算进时间上限
        h.waits.append(round(waited, 1))
        self.log.event("hands", what="resume", page=page, waited=round(waited, 1))
        self.log.say(f"      你停手了（让了 {waited:.0f} 秒），我重新看一下画面。")
        return True

    def _own_touch(self, on: bool) -> None:
        """告诉“盯着你动手”的那一位：这一下是工具自己点的，别算到你头上。"""
        h = self.hands
        if h is not None and hasattr(h, "own"):
            try:
                h.own(on)
            except Exception:  # noqa: BLE001
                pass

    def to_device(self, box: NBox) -> tuple[float, float, float, float]:
        w, h = self.dev.size
        sx, sy = w / NORM_W, h / NORM_H
        return box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy

    # ---- 看 ----
    def look(self) -> Seen:
        img = self.dev.screenshot()
        self.log.keep(img)
        return Seen(img, self.book.recognize(img))

    def observe(self, quiet: bool = False) -> Seen:
        """等到出现一个认识的、可以操作的页面（连续两次看到同一个页面才算数）。

        认不出的画面：先等 unknown_timeout 秒（过场、动画常常几秒就过去；换日、连接出错这类挂机恢复认得的会自己处理）。
        还认不出就请你在模拟器里手动点过去——工具不碰这个画面，只是接着看；认出下一个画面就接着跑。
        等你的这段时间不算进时间上限；最多等 unknown_wait 秒，到了还认不出才停。"""
        start = time.time()
        unknown_since: float | None = None
        prev: Seen | None = None
        since = 0.0                                  # prev 这个页面是从什么时候开始连续出现的
        last_note = ""
        ask_since: float | None = None               # 从什么时候开始在等你手动点（None = 没在等）
        ask_tick = ask_said = 0.0
        while True:
            self._check_limits()
            if self.yield_to_hands():                # 你在自己点：这段时间不算“认不出来”，也不让挂机恢复去碰
                unknown_since, prev, start = None, None, time.time()
                ask_tick = time.time()               # 让手的那段 yield_to_hands 已经从时间上限里扣过了
                continue
            s = self.look()
            now = time.time()
            if ask_since is not None:                # 等你的这段时间不算进时间上限
                self.t0 += max(0.0, now - ask_tick)
                ask_tick = now
            settled, self.settled = self.settled, None       # “已经等稳了”只管紧接着的这一眼
            if not s.res.known:
                unknown_since = unknown_since or now
                if self.recovery is not None and self.recovery.try_fix(s, now - unknown_since):
                    # 换日、连接出错、标题画面这类：它认得，已经点了一下。重新计时，接着看
                    unknown_since, prev, start = None, None, time.time()
                    continue
                if ask_since is not None:
                    if now - ask_since > self.limits.unknown_wait:
                        self.log.event("halt", why="unknown", note=s.res.note, asked=round(now - ask_since, 1))
                        raise Halt(f"这个画面我认不出来（{s.res.name}{'，' + s.res.note if s.res.note else ''}），"
                                   f"请你手动点过去以后又等了 {self.limits.unknown_wait / 60:.0f} 分钟，还是没等到认识的画面")
                    if now - ask_said >= 300.0:
                        ask_said = now
                        self.log.say(f"      …还在等你把这个画面点过去（已经等了 {(now - ask_since) / 60:.0f} 分钟）")
                elif now - unknown_since > self.limits.unknown_timeout:
                    files = self.log.dump_recent("unknown")
                    if self.limits.unknown_wait <= 0:
                        self.log.event("halt", why="unknown", note=s.res.note, shots=files)
                        raise Halt(f"这个画面我认不出来（{s.res.name}{'，' + s.res.note if s.res.note else ''}），"
                                   f"等了 {self.limits.unknown_timeout:.0f} 秒还是不认识")
                    ask_since = ask_tick = ask_said = now
                    what = f"{s.res.name}{'，' + s.res.note if s.res.note else ''}"
                    self.log.say(f"  ※ 这个画面我认不出来（{what}），已经等了 {self.limits.unknown_timeout:.0f} 秒。")      # 不用“!”开头：界面把那种行当成“怎么结束的”
                    self.log.say(f"    请你在模拟器里手动点过去——我不碰这个画面，认出下一个画面以后自己接着跑。"
                                 f"（最多等 {self.limits.unknown_wait / 60:.0f} 分钟；停止键照常能用；这几张截图已经存下来了）")
                    self.log.event("ask_hand", what="wait", name=s.res.name, note=s.res.note, shots=files)
                    if self.on_ask is not None:
                        try:
                            self.on_ask("有个画面我认不出来，请你在模拟器里手动点过去，我会接着跑。")
                        except Exception:  # noqa: BLE001 —— 通知发不出去不影响别的
                            pass
                prev = None
            elif s.res.wait:
                unknown_since = None
                if not quiet and s.res.name != last_note:
                    self.log.say(f"      …{s.res.name}", detail=True)
                    last_note = s.res.name
                prev = None
            else:
                unknown_since = None
                ok = False
                if settled == s.page:                # 调用方刚说过“这个页面我已经等它稳了”：这一眼就算数
                    self.log.event("see", page=s.page, name=s.res.name, page_kind=s.res.kind, score=round(s.res.score, 3), fast=True)
                    ok = True
                elif prev is None or prev.page != s.page:
                    since = now
                elif now - since >= self.limits.settle_pages.get(s.page, self.limits.settle):
                    self.log.event("see", page=s.page, name=s.res.name, page_kind=s.res.kind, score=round(s.res.score, 3))
                    ok = True
                if ok:
                    if ask_since is not None:        # 刚才在等你：认出来了，接着跑。记一笔，流程会把记着的进度按现在的画面重来
                        waited = now - ask_since
                        self.hand_asks.append(round(waited, 1))
                        self.log.say(f"      认出来了（现在是「{s.res.name}」），等了你 {waited:.0f} 秒，接着跑。")
                        self.log.event("ask_hand", what="resume", page=s.page, waited=round(waited, 1))
                    return s
                prev = s
            if ask_since is not None:                # 等你的时候不算“卡死”（不然会去关游戏重开）
                start = now
            patient = self.recovery is not None and self.recovery.recovering     # 从标题画面进游戏要加载很久，有时还要下载
            if now - start > (max(self.limits.wait_timeout, 600.0) if patient else self.limits.wait_timeout) + self.limits.unknown_timeout:
                if self.recovery is not None and self.recovery.stuck(now - start):      # 卡死：关掉游戏重开，再走回来
                    unknown_since, prev, start = None, None, time.time()
                    continue
                files = self.log.dump_recent("stuck")
                self.log.event("halt", why="stuck", shots=files)
                raise Halt(f"等了 {now - start:.0f} 秒，画面一直没有停在能操作的页面上")
            self.stop.sleep(self.limits.poll)

    def hand_over(self, seen: Seen, what: str) -> None:
        """这一步工具拿不准：单步模式下请你来点，点完回车；自动模式下直接停。"""
        self.log.shot(seen.img, f"{seen.page}_handover", png=True)
        if not self.step_mode:
            raise Halt(what)
        self.step_no += 1
        self.log.say(f"[第 {self.step_no} 步] 现在是：{seen.res.name}")
        self.log.say(f"      {what}")
        self.log.event("hand_over", page=seen.page, what=what)
        t_ask = time.time()
        ans = self.ask("      请你在游戏里点好，然后回车；q = 退出 > ").strip().lower()
        self.t0 += time.time() - t_ask
        if ans == "q":
            raise Stopped("你选择了退出")

    def pause(self, seconds: float) -> None:
        self._check_limits()
        self.stop.sleep(seconds)

    def wait_leave(self, page: str, timeout: float = 8.0) -> bool:
        """等当前页面消失（点击生效的标志）。超时返回 False。"""
        end = time.time() + timeout
        while time.time() < end:
            self._check_limits()
            s = self.look()
            if s.page != page:
                return True
            self.stop.sleep(self.limits.poll)
        return False

    # ---- 点 ----
    def swipe(self, seen: Seen, start: tuple[float, float], end: tuple[float, float], label: str,
              duration: float | None = None, on_tick: Any = None, hold_end: float | None = None) -> str:
        """在 seen 这个页面上从 start 拖到 end（1280×720 坐标）。返回值和 tap 一样。"""
        self._check_limits()
        self.step_no += 1
        w, h = self.dev.size
        sx, sy = w / NORM_W, h / NORM_H
        d0, d1 = (start[0] * sx, start[1] * sy), (end[0] * sx, end[1] * sy)
        self.log.say(f"[第 {self.step_no} 步] 现在是：{seen.res.name}", detail=not self.step_mode)      # 单步模式要你点头：细节照常给你看
        self.log.say(f"      打算：{label}（从 {d0[0]:.0f}, {d0[1]:.0f} 拖到 {d1[0]:.0f}, {d1[1]:.0f}）", detail=not self.step_mode)
        shot = self.log.shot(_arrow(seen.img, d0, d1), f"{seen.page}_{self.step_no:02d}")
        if self.step_mode:
            t_ask = time.time()
            ans = self.ask("      回车 = 执行；m = 这一步我自己拖；a = 后面都自动；q = 退出 > ").strip().lower()
            self.t0 += time.time() - t_ask
            if ans == "q":
                raise Stopped("你选择了退出")
            if ans == "a":
                self.step_mode = False
                self.log.event("auto_on", step=self.step_no)
                self.log.say("      好，后面不再逐步问了。想停随时按停止键。")
            if ans == "m":
                self.log.event("manual", page=seen.page, label=label, shot=shot)
                return "manual"
        else:
            self.human.wait(self._react(seen, False))
            self.stop.check()
        if self.yield_to_hands(seen.page):
            self.log.event("skip_changed", page=seen.page, now="", label=label, why="hands")
            return "changed"
        again = self.look()
        if again.page != seen.page:
            self.log.say(f"      画面已经变成「{again.res.name}」了，这一下不拖，重新看。")
            self.log.event("skip_changed", page=seen.page, now=again.page, label=label)
            return "changed"
        t0 = time.time()
        self._own_touch(True)
        try:
            self.human.swipe(d0, d1, duration, on_tick=on_tick, hold_end=hold_end)
        finally:
            self._own_touch(False)
        self.taps += 1
        if not self.step_mode:
            self.log.did(f"  {seen.res.name}：{label}")
        self.log.event("swipe", page=seen.page, label=label, start=[round(v) for v in d0], end=[round(v) for v in d1],
                       seconds=round(time.time() - t0, 2), shot=shot)
        return "tapped"

    def _react(self, seen: Seen, think: bool) -> float:
        """点之前还要等多久。反应时间（think=True 是“想一想”的时间）从看到这个画面那一刻算起：
        中间认卡、排队伍、推演已经花掉的时间算在里面，只补上还差的那一截；最少也留一小下（REACT_FLOOR）。"""
        want = self.human.react_delay(think)
        spent = max(0.0, time.time() - getattr(seen, "t", time.time()))
        return max(min(want, REACT_FLOOR), want - spent)

    def tap(self, seen: Seen, box: NBox, label: str, think: bool = False) -> str:
        """在 seen 这个页面上点 box。返回 "tapped" / "manual"（你选择自己点）/ "changed"（画面已经变了，没点）。"""
        self._check_limits()
        self.step_no += 1
        dbox = self.to_device(box)
        cx, cy = dbox[0] + dbox[2] / 2, dbox[1] + dbox[3] / 2
        self.log.say(f"[第 {self.step_no} 步] 现在是：{seen.res.name}", detail=not self.step_mode)
        self.log.say(f"      打算：点「{label}」（屏幕坐标 {cx:.0f}, {cy:.0f} 附近）", detail=not self.step_mode)
        shot = self.log.shot(_mark(seen.img, dbox), f"{seen.page}_{self.step_no:02d}")
        if self.step_mode:
            t_ask = time.time()
            ans = self.ask("      回车 = 执行；m = 这一步我自己点；a = 后面都自动；q = 退出 > ").strip().lower()
            self.t0 += time.time() - t_ask           # 等你回车的时间不算进时间上限
            if ans == "q":
                raise Stopped("你选择了退出")
            if ans == "a":
                self.step_mode = False
                self.log.event("auto_on", step=self.step_no)
                self.log.say("      好，后面不再逐步问了。想停随时按停止键。")
            if ans == "m":
                self.log.event("manual", page=seen.page, label=label, shot=shot)
                self.log.say("      好，你来点，我看着。")
                return "manual"
        else:
            self.human.wait(self._react(seen, think))
            self.stop.check()
        if self.yield_to_hands(seen.page):           # 你刚才自己点过：就算还是同一个页面，里面选了什么也可能变了
            self.log.event("skip_changed", page=seen.page, now="", label=label, why="hands")
            return "changed"
        again = self.look()                          # 等的这段时间里画面可能变了：点之前总是再看一眼
        if again.page != seen.page:
            self.log.say(f"      画面已经变成「{again.res.name}」了，这一下不点，重新看。")
            self.log.event("skip_changed", page=seen.page, now=again.page, label=label)
            return "changed"
        self._own_touch(True)
        try:
            rec = self.human.tap(dbox, label)
        finally:
            self._own_touch(False)
        self.taps += 1
        self.log.event("tap", page=seen.page, label=label, x=rec.x, y=rec.y, press_ms=round(rec.press_ms, 1),
                       drift=rec.drift, box=[round(v, 1) for v in dbox], shot=shot)
        self.log.say(f"      点了 ({rec.x}, {rec.y})，按了 {rec.press_ms:.0f} 毫秒", detail=True)
        if not self.step_mode:
            self.log.did(f"  {seen.res.name}：点「{label}」")
        return "tapped"


def _arrow(img: np.ndarray, p0: tuple[float, float], p1: tuple[float, float]) -> np.ndarray:
    import cv2
    out = img.copy()
    cv2.arrowedLine(out, (int(p0[0]), int(p0[1])), (int(p1[0]), int(p1[1])), (0, 0, 255), 4, tipLength=0.06)
    return out


def _mark(img: np.ndarray, dbox: tuple[float, float, float, float]) -> np.ndarray:
    import cv2
    out = img.copy()
    x, y, w, h = (int(round(v)) for v in dbox)
    cv2.rectangle(out, (x, y), (x + w, y + h), (0, 0, 255), 3)
    return out
