"""挂机时会撞上的系统画面（2026-11-24）。

过夜挂机一定会遇到：国服每天 5 点换日，下一次和服务器说话时弹「日期变更」，点了「确认」游戏就退回标题画面；
偶尔还有连接出错的弹窗。以前这些画面工具都不认识，等 20 秒就停。这里把它们认出来，按固定的办法走回迷宫首页。

只做这几件事，别的一概不碰：
- 「日期变更」、连接出错这类系统弹窗：点「确认」/「重试」；
- 标题画面：点一下画面中间进游戏；
- 进游戏路上的登录奖励、公告：点「跳过」/「关闭」，或者点一下画面中间翻过去；
- 看到最下面那排导航：点「冒险」（之后的「冒险」页、迷宫首页是工具本来就认识的页面，走原来的路）。
画面上出现 密码 / 验证码 / 实名 / 支付 / 充值 这些字：马上停，交给人（不替你登录、不过验证、不碰付费）。
对不上上面任何一条的画面：照旧等一会儿就停。每一下都存截图、记日志，次数有上限。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from . import ocr as OCR
from .vision.pages import to_norm

NBox = tuple[float, float, float, float]

BLOCK = ("密码", "验证码", "实名", "支付", "充值", "付款")
TITLE_CUES = ("点击屏幕", "点击画面", "轻触屏幕", "触摸屏幕", "触碰屏幕", "TOUCH", "TAPTO", "点击开始", "开始游戏", "点击进入")
PAY_WORDS = ("宝石", "钻石", "购买", "扭蛋", "付费", "月卡", "礼包", "消耗")     # 对话框里有这些字：像是要花东西的确认，「确认」绝不点
NO_POKE = ("购买", "付费", "月卡", "礼包")                                      # 整页画面上有这些字：像是卖东西的页面，不许“点一下画面中间”（只找「关闭」「跳过」）
MAINT_WORDS = ("维护中", "正在维护", "停服维护", "服务器维护")                   # 没有「关闭」的对话框里有这些字：游戏在维护，停下等你
RESUME_CUES = ("进行中", "未完成", "继续挑战", "继续探索", "继续上次", "中断的", "是否继续", "要继续")   # 往回走时：问要不要接着打没打完的那一局
NET_CUES = ("连接", "通信", "网络", "超时", "错误", "失败", "中断", "异常")     # 弹窗里有这些字 = 和服务器没说上话
RETRY = ("重试", "再试", "重新连接", "重连")
DOWNLOAD_CUES = ("数据", "资源", "MB", "追加")                                    # 对话框里写着“下载”，又有这些字：进游戏前要先下一点数据（更新以后常有），这是进游戏必经的一步
CLIENT_CUES = ("版本", "客户端", "商店", "前往", "安装", "升级")                  # 写着“下载 / 更新”，又有这些字：是要去应用商店更新客户端——那就出了游戏，不碰
OKAY = ("返回标题", "回到标题", "确认", "确定", "OK")
NAV_OTHERS = ("主菜单", "角色", "公会之家", "公会小屋", "扭蛋", "我的主页", "主页", "剧情")
NAV_LABELS = ("我的主页", "公会之家", "公会小屋", "主菜单", "角色", "强化", "剧情", "冒险", "扭蛋")    # 主页 / 冒险页最下面那排导航按钮上的字
NORM_H = 720.0
DIALOG_PAD = 10.0                               # 对话框的范围上下各放宽这么多
NAV_Y = 640.0                                   # 最下面那排导航在这条线以下（1280×720）
CENTER: NBox = (560.0, 270.0, 160.0, 90.0)      # 画面中间的一块：标题画面、登录奖励点这里翻过去
ADV_CUES = ("主线关卡", "深域关卡", "团队战", "竞技场", "追忆的战场", "黎明界迷宫")      # 冒险页上那几块入口的名字（照真机截图）
QUIET_SPOT: NBox = (100.0, 190.0, 180.0, 170.0) # 冒险页左边那块立绘，上面没有按钮。冒险页的画面中间正好压着「主线关卡」「探险」两个入口，不能往那儿点
LAB_Y = 450.0                                   # 冒险页上「黎明界迷宫」那块入口的名字在这条线以下、导航那一排以上
MAX_ACTS = 60                                   # 一次运行里，这里最多替你点这么多下
MAX_POKES = 30                                  # 其中“点一下画面中间”最多这么多下（每次回迷宫的路上重新数）
MAX_EPISODES = 4                                # 一次运行里最多走回来几次（换日一天一次；再多说明网络一直有问题）
BLIND_MAX = 5                            # 往回走的路上连着这么多次没读成字（每次隔 ACT_GAP 秒，一共十几秒）就停下
POKE_GAPS = (3.0, 4.0, 6.0, 8.0, 10.0)          # 两次“点一下画面中间”之间至少隔多久（越往后隔得越久，最后一个数一直用下去）
EPISODE_SECONDS = 900.0                         # 每走回来一次，时间上限放宽这么多
WAIT_TIMEOUT = 600.0                            # 走回来的路上，加载 / 下载这类等待最多等这么久
NET_MAX, NET_WINDOW = 6, 180.0                  # 连接出错的弹窗这么多秒里出了这么多次：网络多半真有问题，停下
RELAUNCH_MAX = 2                                # 一次运行里最多替你重新启动游戏几次（闪退、卡死）
GENERIC_AFTER, GENERIC_MAX = 6.0, 6             # 一局里面遇到不认识的对话框：停了这么久才动手；一次运行最多这么多个
FG_AFTER, FG_GAP = 8.0, 10.0                    # 画面连着这么久认不出才去问系统“游戏还在不在前台”；两次询问至少隔这么久
ACT_GAP = 2.5                                   # 认不出的画面至少等这么久再动手（弹窗有弹出动画，加载有一闪而过的画面）


@dataclass
class Act:
    kind: str                                   # daychange / retry / neterr / download / resume / title / skip / close / info / cancel / nav / lab / poke / wait（不点，只是等）
    label: str
    box: NBox


@dataclass
class Block:
    why: str


def _clean(t: str) -> str:
    return t.replace(" ", "").replace("　", "")


def _pad(box: tuple[float, float, float, float]) -> NBox:
    x, y, w, h = box
    return (x - 6.0, y - 4.0, w + 12.0, h + 8.0)


def guard_text(items: list[tuple[str, tuple[int, int, int, int], float]]) -> str:
    """查“不许碰”的字用的全文：读得没把握的字也算数（宁可多停）。
    只有一样不算：主页 / 冒险页最下面那排导航按钮上的字。那一排里就有「扭蛋」两个字，主页、冒险页上永远看得见——
    它不是弹窗在问的事，算进来的话这两页上的任何弹窗都会被当成“要花东西的确认”。要认得出至少三个导航按钮才当它是那一排。"""
    low = [(_clean(t), b) for t, b, _s in items if b[1] + b[3] / 2.0 >= NAV_Y]
    row = "".join(t for t, _ in low)
    is_nav = sum(1 for w in NAV_LABELS if w in row) >= 3
    out = []
    for t, b, _s in items:
        c = _clean(t)
        if is_nav and b[1] + b[3] / 2.0 >= NAV_Y:
            for w in NAV_LABELS:
                c = c.replace(w, "")
        out.append(c)
    return "".join(out)


def looks_like_adventure(text: str) -> bool:
    """读到的字里有冒险页上至少三个入口的名字：这是冒险页（哪怕整页没认出来）。"""
    return sum(1 for w in ADV_CUES if w in text) >= 3


def poke_box(text: str, page: str = "") -> NBox:
    """要“点一下，把盖着的东西翻过去”的时候点哪里：冒险页点左边的立绘（中间是别的玩法的入口，点进去就出了迷宫的范围），别的点画面中间。"""
    return QUIET_SPOT if page == "adventure" or looks_like_adventure(text) else CENTER


def _find(texts: list[tuple[str, tuple[int, int, int, int]]], words: tuple[str, ...], min_y: float = 0.0,
          exact: bool = False) -> tuple[int, int, int, int] | None:
    """按 words 的先后找：排在前面的词优先。同一个词出现好几处时取最靠下的那一处——按钮在对话框下面，
    而对话框的标题也常常就叫「确认」，取第一处会点到标题上去。"""
    for w in words:
        hits = [b for t, b in texts if b[1] + b[3] / 2.0 >= min_y and ((t == w) if exact else (w in t and len(t) <= len(w) + 6))]
        if hits:
            return max(hits, key=lambda b: b[1] + b[3] / 2.0)
    return None


def decide(items: list[tuple[str, tuple[int, int, int, int], float]], dialog: bool, recovering: bool,
           poke_ok: bool, generic_ok: bool = False, bar_y: float | None = None) -> Act | Block | None:
    """看着读到的字决定点哪里。items = 文字识别的结果（1280×720 坐标）；dialog = 画面上有蓝色标题栏的对话框；
    recovering = 正在从游戏外面往迷宫走；poke_ok = 现在可以“点一下画面中间”；bar_y = 最上面那个对话框标题栏的 y。拿不准返回 None。

    对话框一个压一个的时候（比如在「公会选择确认」上点「出发」弹出“连接出错”），底下那个对话框的字照样读得到——
    它写着“将消耗 1 张迷宫通行证”，它的「取消」按钮也还看得见。所以给了 bar_y 就只看最上面这个对话框自己的范围：
    游戏里的对话框上下居中（7 张真机截图量过，下沿正好在 720 − bar_y），范围取 bar_y ～ 720 − bar_y，左右不限。
    “密码、验证码、支付”这几个字不受这个范围限制，整个画面上有就停。"""
    faint = guard_text(items)                                                        # 找“不许碰”的字：读得没把握的也算数，宁可多停（导航那一排除外）
    for w in BLOCK:
        if w in faint:
            return Block(f"画面上有「{w}」两个字")
    if dialog and bar_y is not None:                                                 # 只留最上面这个对话框范围里的字
        top, bottom = float(bar_y) - DIALOG_PAD, NORM_H - float(bar_y) + DIALOG_PAD
        items = [i for i in items if top <= i[1][1] + i[1][3] / 2.0 <= bottom]
        faint = guard_text(items)
    texts = [(_clean(t), b) for t, b, s in items if s >= 0.5 and _clean(t)]          # 找按钮、找“这是什么弹窗”的线索：只信读得有把握的
    joined = "".join(t for t, _ in texts)
    if dialog:
        if any(w in faint for w in MAINT_WORDS) and _find(texts, ("关闭",)) is None:
            return Block("游戏在维护（对话框里写着维护）")
        if ("下载" in faint or "更新客户端" in faint or "版本更新" in faint) and not any(w in faint for w in PAY_WORDS if w != "消耗"):
            # 写着“下载”的对话框（“消耗流量”里的“消耗”不算要花东西）。两种：去应用商店更新客户端——出了游戏，停下；进游戏前下一点数据——必经的一步，点「确认」
            if any(w in faint for w in CLIENT_CUES):
                return Block("游戏要更新客户端（要去应用商店下载新版本）")
            b = _find(texts, RETRY) if any(w in joined for w in NET_CUES) else None
            if b is not None:                            # 下载到一半出错了
                return Act("retry", "重试（下载 / 连接出错）", _pad(b))
            if recovering and "下载" in joined and any(w in joined.upper() for w in DOWNLOAD_CUES):
                b = _find(texts, ("确认", "确定", "OK")) or _find(texts, ("下载", "开始下载"), exact=True)
                if b is not None:                        # 之后的下载进度条当成加载来等
                    return Act("download", "确认（进游戏前要下载一点数据）", _pad(b))
            return None
        if any(w in faint for w in PAY_WORDS):          # 计划里定的：付费确认一律取消或停下。走回迷宫的路上点「取消」/「关闭」，平时停下交给你
            b = _find(texts, ("取消", "关闭")) if recovering else None
            return Act("cancel", "取消（像是要花宝石 / 买东西的确认，一律不点「确认」）", _pad(b)) if b is not None else None
        if "日期" in joined and "变更" in joined:
            b = _find(texts, OKAY)
            if b is not None:
                return Act("daychange", "确认（日期变更：游戏会回到标题画面）", _pad(b))
        if any(w in joined for w in NET_CUES):
            b = _find(texts, RETRY)
            if b is not None:
                return Act("retry", "重试（连接出错）", _pad(b))
            b = _find(texts, OKAY)
            if b is not None:
                return Act("neterr", "确认（连接出错：可能会回到标题画面）", _pad(b))
        if recovering and any(w in joined for w in RESUME_CUES):
            b = _find(texts, ("继续", "再开") + OKAY)
            if b is not None:                            # 回到迷宫时游戏问“有一局还没打完，要不要接着打”：接着打
                return Act("resume", "确认（接着打没打完的那一局）", _pad(b))
        # 不认识的对话框（计划里定的：公告、推销这类“只关不点”）：有「关闭」就关掉；只有一个「确认」、没有「取消」的提示框，点那个唯一的按钮。
        # 往回走的路上马上处理；平时（一局里面）要等它稳稳地停了一会儿才动（generic_ok），次数有上限，每次都存原图
        if recovering or generic_ok:
            b = _find(texts, ("关闭",))
            if b is not None:
                return Act("close", "关闭（不认识的弹窗，只关不点）", _pad(b))
            b = _find(texts, ("跳过",))
            if b is not None:
                return Act("skip", "跳过", _pad(b))
            b = _find(texts, OKAY)
            if b is not None and _find(texts, ("取消", "否", "不了", "返回")) is None:
                return Act("info", "确认（只有这一个按钮的提示框）", _pad(b))
        return None
    if any(c in joined.upper() for c in TITLE_CUES):
        return Act("title", "点一下画面中间（标题画面，进游戏）", CENTER)
    if not recovering:
        return None
    if "下载" in joined and any(w in joined.upper() for w in ("%", "MB", "下载中", "正在下载")):
        return Act("wait", "正在下载数据，等它下完", CENTER)       # 不点，只是告诉外面“这不是卡住了”
    b = _find(texts, ("跳过", "SKIP"))
    if b is not None:
        return Act("skip", "跳过", _pad(b))
    b = _find(texts, ("关闭",))
    if b is not None:                                # 先关弹窗再点导航：主页 / 冒险页自己没有「关闭」，看得见它就说明上面盖着东西，导航点了也没用
        return Act("close", "关闭（回迷宫路上的公告）", _pad(b))
    if looks_like_adventure(joined):                 # 冒险页整页没认出来（比如活动换了，入口上的角标变了）：照着字找「黎明界迷宫」那块入口
        lab = _find([(t, b) for t, b in texts if b[1] + b[3] / 2.0 < NAV_Y], ("黎明界迷宫",), min_y=LAB_Y, exact=True)
        if lab is not None:
            return Act("lab", "黎明界迷宫（冒险页上的入口）", _pad(lab))
    nav = _find(texts, ("冒险",), min_y=NAV_Y)
    if nav is not None and _find(texts, NAV_OTHERS, min_y=NAV_Y) is not None and not looks_like_adventure(joined):
        return Act("nav", "冒险（最下面那排导航）", _pad(nav))
    if poke_ok and not any(w in faint for w in NO_POKE):
        if looks_like_adventure(joined):
            return Act("poke", "点一下左边的立绘（冒险页上像是盖着东西，翻过去）", QUIET_SPOT)
        return Act("poke", "点一下画面中间（标题画面 / 登录奖励，翻过去）", CENTER)
    return None


BLIND = ("这台电脑上读字的组件没装好（或者这一下没读成）：我看不出画面上写的是什么——有没有密码、验证码、实名、支付、充值这些字——"
         "所以不替你点画面走回迷宫，停下交给你。在界面上点一次「准备运行环境」再试")


def read_screen(img: Any) -> list[tuple[str, tuple[int, int, int, int], float]] | None:
    """读整张画面上的字。None = 没读成（看不见）。看不见的时候挂机恢复一下都不点：那几条“见到某些字就停”的线全靠它。"""
    try:
        return OCR.read_items_or_none(to_norm(img))
    except Exception:  # noqa: BLE001
        return None


class Recovery:
    """挂在 Runner 上：认不出的画面先交给它看一眼，它能处理就点一下，不能处理就让 Runner 照旧等到超时停下。
    读不了字的时候（read_screen 返回 None）什么都不点：正在往回走就停下说明，平时就当没有这个功能。"""

    def __init__(self, runner: Any, on: bool = True, relaunch: bool = True):
        self.r = runner
        self.on = bool(on)
        self.relaunch_on = bool(relaunch)           # 游戏闪退 / 卡死时要不要替你重新启动它
        self.relaunches = 0
        self.last_fg = 0.0
        self.net_times: list[float] = []
        self.generic = 0                            # 一局里面替你关掉 / 点掉的不认识的对话框有几个
        self.recovering = False                 # 正在从游戏外面往迷宫走
        self.why = ""
        self.acts = 0
        self.pokes = 0
        self.episodes = 0
        self.last_poke = 0.0
        self.last_act = 0.0
        self.blind = 0                              # 连着几次没读成字
        self.nav_streak = 0                         # 连着几次想点导航上的「冒险」
        self.wait_since, self.wait_said = 0.0, False     # 下载进度从什么时候开始等的
        self.log: list[str] = []                # 这一次运行里处理过什么（给最后的小结用）

    # ---- 流程那边调用 ----
    def begin(self, why: str) -> None:
        """流程认出了「日期变更」之类：从现在起是“往迷宫走”的状态。"""
        from .runner import Halt
        if not self.recovering:
            self.episodes += 1
            if self.episodes > MAX_EPISODES:
                raise Halt(f"这一次运行里已经从游戏外面走回迷宫 {MAX_EPISODES} 次了（{why}），不太对劲，停下")
            self.pokes, self.last_poke, self.nav_streak = 0, 0.0, 0
            self.r.limits.max_seconds += EPISODE_SECONDS      # 走回来这段路不占原来的时间额度
            self.r.log.say(f"      —— {why}：我自己走回迷宫（标题画面 → 主页 → 冒险 → 黎明界迷宫），这段路上只点「确认」「跳过」「关闭」「冒险」和画面中间 ——")
            self.r.log.event("recover_begin", why=why, episode=self.episodes)
            self.log.append(why)
        self.recovering, self.why = True, why

    def done(self, where: str) -> None:
        if self.recovering:
            self.r.log.say(f"      —— 回到「{where}」了，接着原来的流程 ——")
            self.r.log.event("recover_done", where=where, acts=self.acts, pokes=self.pokes)
        self.recovering = False

    # ---- Runner 那边调用 ----
    def try_fix(self, seen: Any, waited: float) -> bool:
        """seen = 认不出的那张画面；waited = 已经连续认不出多少秒。点了一下返回 True。"""
        from .runner import Halt
        if not self.on or waited < ACT_GAP:
            return False
        now = time.time()
        if now - self.last_act < ACT_GAP:
            return False
        dialog = seen.res.bar_y is not None
        items = read_screen(seen.img)
        if items is None:                            # 看不见字：不点。正在往回走的话连着几次都看不见就停下说明
            self.blind += 1
            self.last_act = now
            if self.recovering and self.blind >= BLIND_MAX:
                self.r.log.shot(seen.img, "afk_blind", png=True)
                self.r.log.event("halt", why="afk_blind", n=self.blind)
                raise Halt(BLIND)
            return False
        self.blind = 0
        gap = POKE_GAPS[min(self.pokes, len(POKE_GAPS) - 1)]
        poke_ok = self.recovering and self.pokes < MAX_POKES and now - self.last_poke >= gap and waited >= min(gap, 3.0)
        generic_ok = dialog and waited >= GENERIC_AFTER and self.generic < GENERIC_MAX
        act = decide(items, dialog, self.recovering, poke_ok, generic_ok, bar_y=seen.res.bar_y if dialog else None)
        if isinstance(act, Act) and act.kind in ("nav", "lab"):
            self.nav_streak += 1                     # 连着点「冒险」/「黎明界迷宫」都没走掉：上面多半盖着没有「关闭」的东西（登录奖励之类），改成点一下把它翻过去
            if self.nav_streak > 2 and poke_ok and not any(w in guard_text(items) for w in NO_POKE):
                spot = poke_box(guard_text(items))
                act, self.nav_streak = Act("poke", ("点一下左边的立绘" if spot is QUIET_SPOT else "点一下画面中间") + "（点了两次都没反应，上面像是盖着东西）", spot), 0
        elif act is not None:
            self.nav_streak = 0
        if isinstance(act, Act) and act.kind == "wait":      # 下载进度：不点，接着等（最多 WAIT_TIMEOUT 秒）
            self.wait_since = self.wait_since or now
            if now - self.wait_since > WAIT_TIMEOUT:
                raise Halt(f"数据下载了 {WAIT_TIMEOUT / 60:.0f} 分钟还没下完，停下交给你")
            if not self.wait_said:
                self.wait_said = True
                self.r.log.say("      …游戏在下载数据，等它下完")
                self.r.log.event("afk", what="wait", label=act.label)
            self.last_act = now
            return True
        self.wait_since, self.wait_said = 0.0, False
        if act is None:
            return self._crashed(seen, waited)
        if isinstance(act, Act) and act.kind == "poke" and self._crashed(seen, max(waited, FG_AFTER)):
            return True                              # 要“点画面中间”之前先确认游戏还在最前面：闪退到桌面上可不能乱点
        texts = [t for t, _b, _s in items][:40]
        if isinstance(act, Block):
            shot = self.r.log.shot(seen.img, "afk_block", png=True)
            self.r.log.event("halt", why="afk_block", note=act.why, shot=shot, texts=texts)
            raise Halt(f"{act.why}，停下交给你" if "维护" in act.why or "更新客户端" in act.why else f"{act.why}（登录、验证、付费这类画面我不碰），停下交给你")
        if act.kind in ("neterr", "retry"):          # “重试”是原地再试一次，不算回到游戏外面；点「确认」的那种才会退回标题画面
            self.net_times = [t for t in self.net_times if now - t < NET_WINDOW] + [now]
            if len(self.net_times) >= NET_MAX:
                self.r.log.shot(seen.img, "afk_net", png=True)
                raise Halt(f"连接出错的弹窗 {NET_WINDOW / 60:.0f} 分钟里出了 {len(self.net_times)} 次，网络多半真有问题，停下")
        if self.acts >= MAX_ACTS:
            raise Halt(f"处理系统弹窗 / 回迷宫的路上已经点了 {MAX_ACTS} 下还没走回去，停下")
        if act.kind in ("daychange", "neterr", "title") and not self.recovering:
            self.begin({"daychange": "游戏换日了（每天 5 点）", "neterr": "和服务器的连接出了问题", "title": "游戏回到了标题画面"}[act.kind])
        if act.kind in ("close", "skip", "info") and not self.recovering:
            self.generic += 1
            shot = self.r.log.shot(seen.img, "unknown_dialog", png=True)      # 留一张原图：以后照着它把这个弹窗正式认下来
            self.r.log.say(f"      出来一个不认识的对话框（读到的字：{'、'.join(texts[:8])}）：{act.label}。截图存了（{shot}），这是这次运行里的第 {self.generic} 个。")
        self.r.log.event("afk", what=act.kind, label=act.label, dialog=dialog, texts=texts, waited=round(waited, 1))
        res = self.r.tap(seen, act.box, act.label)
        self.last_act = time.time()
        if res == "tapped":
            self.acts += 1
            self.r.limits.max_taps += 1          # 这些不算进本来的点击额度
            if act.kind in ("poke", "title"):
                self.pokes += 1
                self.last_poke = self.last_act
        return res in ("tapped", "manual")


    def nudge(self, seen: Any) -> bool:
        """往回走的路上停在主页 / 冒险页、点「冒险」却点不动（多半是上面盖着登录奖励、公告之类的小弹窗，底下的页面照样认得出来）：
        找「关闭」「跳过」点一下；找不到就点一下画面中间。点了返回 True。"""
        if not self.on or not self.recovering or self.acts >= MAX_ACTS:
            return False
        items = read_screen(seen.img)
        if items is None:                            # 看不见字：不点
            return False
        texts = [(_clean(t), b) for t, b, s in items if s >= 0.5 and _clean(t)]
        joined = guard_text(items)                                                   # 读得没把握的字也算数；最下面那排导航（里面有「扭蛋」）不算
        if any(w in joined for w in BLOCK) or any(w in joined for w in PAY_WORDS):
            return False                             # 有登录、付费这类字：不碰，让外面照旧“点了几次没反应”停下
        b = _find(texts, ("关闭", "跳过"))
        if b is not None:
            box, label = _pad(b), "关闭 / 跳过（盖在页面上的弹窗）"
        elif self.pokes < MAX_POKES:
            box = poke_box(joined, getattr(seen, "page", ""))
            label = ("点一下左边的立绘" if box is QUIET_SPOT else "点一下画面中间") + "（页面上像是盖着东西）"
            self.pokes += 1
        else:
            return False
        self.r.log.event("afk", what="nudge", label=label, texts=[t for t, _ in texts][:40])
        if self.r.tap(seen, box, label) == "tapped":
            self.acts += 1
            self.r.limits.max_taps += 1
            self.last_act = time.time()
            return True
        return False

    # ---- 闪退 / 卡死 ----
    def can_see(self) -> bool:
        """读字的组件在不在。不在就别往游戏外面走：走回来的路上全靠读字。"""
        return OCR.available()

    def _relaunch(self, seen: Any, why: str, restart: bool) -> bool:
        from .runner import Halt
        dev = self.r.dev
        if not self.on or not self.relaunch_on or not hasattr(dev, "launch_game"):
            return False
        if not self.can_see():                       # 重新启动以后要从标题画面走回来，看不见字就走不了：不启动，让外面照旧停下
            return False
        if self.relaunches >= RELAUNCH_MAX:
            raise Halt(f"{why}，这一次运行里已经替你重新启动过 {RELAUNCH_MAX} 次游戏了，不再试，停下")
        self.relaunches += 1
        if seen is not None:
            self.r.log.shot(seen.img, "afk_relaunch", png=True)
        self.r.log.say(f"      {why}：{'把游戏彻底关掉再' if restart else ''}重新启动游戏（第 {self.relaunches} 次，最多 {RELAUNCH_MAX} 次），然后走回迷宫。")
        self.r.log.event("relaunch", why=why, restart=restart, n=self.relaunches)
        if not dev.launch_game(restart=restart):
            raise Halt(f"{why}，想重新启动游戏但命令没发出去，停下")
        self.begin(why)
        self.last_act = time.time()
        return True

    def _crashed(self, seen: Any, waited: float) -> bool:
        """画面一直认不出、别的规则也对不上：问一下系统游戏还在不在最前面。不在（闪退了，或者被别的应用盖住）就重新启动它。"""
        dev = self.r.dev
        now = time.time()
        if not self.relaunch_on or waited < FG_AFTER or now - self.last_fg < FG_GAP or not hasattr(dev, "foreground"):
            return False
        self.last_fg = now
        fg, game = dev.foreground(), getattr(getattr(dev, "target", None), "game", None)
        if not fg or not game or fg == game:
            return False
        return self._relaunch(seen, f"游戏不在最前面了（现在最前面的是 {fg}，多半是闪退）", restart=False)

    def stuck(self, waited: float) -> bool:
        """画面很久都没停在能操作的页面上（一直在转圈、黑屏）：当成卡死，把游戏关掉重开。处理了返回 True。"""
        return self._relaunch(None, f"画面 {waited:.0f} 秒都没停在能操作的页面上，像是卡死了", restart=True)


def keep_awake(on: bool) -> bool:
    """挂机时别让电脑自己睡过去（屏幕照样可以关）。只对这个程序运行期间有效，程序一退出系统就恢复原样。成功返回 True。"""
    try:
        import ctypes
        es_continuous, es_system_required = 0x80000000, 0x00000001
        flags = es_continuous | (es_system_required if on else 0)
        return bool(ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags)))      # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 —— 不是 Windows，或者调用不了：不影响别的
        return False
