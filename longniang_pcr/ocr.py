"""读画面上的字（RapidOCR）。用在：角色的名字（「读角色」、角色加入、招募）、「战斗准备」页面上敌人的名字、页面标题。

OCR 是可选的：没装、模型没下载下来、或者中途出错，一律返回空，由调用方按“没读出来”处理，不会让整个流程停下。

读法有两种，2026-11-17 在真机上吃过亏以后定的规矩：
  单行：已经知道字在哪（名字横条、标题），就把那一行裁出来直接“认字”，不让它先“找字”。又快又稳，优先用。
  检测：让它自己先找字在哪、再认。它找字之前会把图的短边拉到 736 像素——把一小条名字直接给它，字会被放大到三四百像素高，
        反而找不到（「可可萝」三个字清清楚楚却读成空的，角色一览的标题时灵时不灵，都是这个原因）。所以走这条路时，
        先把那一小条贴到一张大画布中间，让字在它眼里是四十像素左右高。
两种读法、两种图（把笔画描成白底黑字的 / 原图）轮着试，调用方拿自己的名单去核对，对上了就停（label_reads）。
"""
from __future__ import annotations

from typing import Any, Callable, Iterator

import numpy as np

_reader: Callable[[np.ndarray], list[str]] | None = None                    # 检测 + 识别：整张图里所有的字
_liner: Callable[[np.ndarray], list[tuple[str, float]]] | None = None       # 只识别：这张图就是一行字
_itemizer: Callable[[np.ndarray], list[tuple[str, tuple[int, int, int, int], float]]] | None = None   # 检测 + 识别，连位置一起给：[(字, (x, y, 宽, 高), 把握)]
_state = "untried"          # untried / ok / missing
_error = ""
_line_error = ""
_line_fails = 0
_items_error = ""           # “带位置的读字”最近一次为什么没读成（写进记录里：2026-11-24 真机上它一段字都没读回来，当时没留下原因）
_items_checked = False      # “一段都没读到”的时候，已经拿不带位置的读法核对过一次了
_raw: Callable[[np.ndarray], Any] | None = None      # 读字组件原样的结果（只在核对的时候用）
context: dict[str, Any] = {}      # 正在读哪一块、用的哪种读法（自测里的假 OCR 靠它知道该回什么；排查时也有用）
LINE_MIN_SCORE = 0.45             # 单行读法的把握低于这个就当没读出来


def _seq(x: Any) -> list[Any]:
    """结果对象里的一个字段 → 列表。字段可能是 None、元组，也可能是 numpy 数组（那种不能拿 “x or []” 判断，会直接报错）。"""
    if x is None:
        return []
    try:
        return list(x)
    except TypeError:
        return []


def _texts(res: Any) -> list[str]:
    if res is None:
        return []
    if hasattr(res, "txts"):
        return [str(x) for x in (res.txts or [])]
    if isinstance(res, tuple) and res:
        res = res[0]
    out = []
    for item in res or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            out.append(str(item[1]))
    return out


def _lines(res: Any) -> list[tuple[str, float]]:
    """“只识别”的结果 → [(字, 把握)]。新版 RapidOCR 给的是带 txts / scores 的对象，老版是 ([[字, 把握], …], 用时)。"""
    if res is None:
        return []
    if hasattr(res, "txts"):
        txts = list(res.txts or [])
        scores = list(getattr(res, "scores", None) or [])
        return [(str(t), float(scores[i]) if i < len(scores) else 1.0) for i, t in enumerate(txts)]
    if isinstance(res, tuple) and res:
        res = res[0]
    out = []
    for item in res or []:
        if isinstance(item, (list, tuple)) and item and isinstance(item[0], str):
            out.append((item[0], float(item[1]) if len(item) > 1 and isinstance(item[1], (int, float)) else 1.0))
    return out


def _items(res: Any) -> list[tuple[str, tuple[int, int, int, int], float]]:
    """“检测 + 识别”的结果 → [(字, (x, y, 宽, 高), 把握)]。新版 RapidOCR 给带 boxes / txts / scores 的对象，老版是 ([[四个角, 字, 把握], …], 用时)。"""
    def rect(box: Any) -> tuple[int, int, int, int] | None:
        try:
            pts = np.asarray(box, dtype=np.float32).reshape(-1, 2)
            x0, y0, x1, y1 = float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())
            return int(round(x0)), int(round(y0)), int(round(x1 - x0)), int(round(y1 - y0))
        except Exception:  # noqa: BLE001
            return None

    out: list[tuple[str, tuple[int, int, int, int], float]] = []
    if res is None:
        return out
    if hasattr(res, "txts"):
        txts = _seq(res.txts)
        boxes = next((_seq(getattr(res, k)) for k in ("boxes", "dt_boxes", "det_boxes") if getattr(res, k, None) is not None), [])
        scores = _seq(getattr(res, "scores", None))
        for i, t in enumerate(txts):
            b = rect(boxes[i]) if i < len(boxes) else None
            if t and b:
                try:
                    sc = float(scores[i]) if i < len(scores) else 1.0
                except (TypeError, ValueError):
                    sc = 1.0
                out.append((str(t), b, sc))
        return out
    if isinstance(res, tuple) and res:
        res = res[0]
    for item in res or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[1], str):
            b = rect(item[0])
            if item[1] and b:
                out.append((item[1], b, float(item[2]) if len(item) > 2 and isinstance(item[2], (int, float)) else 1.0))
    return out


def _full_call(engine: Any) -> Callable[[np.ndarray], Any]:
    """“检测 + 识别”的调用：每一次都把三个开关写明。

    为什么（2026-11-25 用户真机上的记录：“同一张图不带位置能读到 1 段字，带位置的一段都没拿到；结果是 TextRecOutput”）：
    新版 RapidOCR 会把调用时给的开关**记在自己身上**（`update_params` 里直接 `setattr`，没给的才沿用）。单行读法用的是
    `use_det=False`——它只要用过一次，后面不写开关的 `engine(img)` 就一直不“找字”了：整张图被当成一行字去认，
    回来的是只有字、没有位置的 TextRecOutput。所以整张图找字（公会选择页上找公会、挂机时读对话框、读战利品清单）在真机上一直读不到位置。
    老版本（rapidocr_onnxruntime）不记，这样写两边都对；万一哪个版本不认这几个参数，就退回不写开关的调用。"""
    def call(img: np.ndarray) -> Any:
        try:
            return engine(img, use_det=True, use_cls=True, use_rec=True)
        except TypeError:
            return engine(img)
    return call


def _load() -> None:
    global _reader, _liner, _itemizer, _state, _error, _raw
    try:
        try:
            from rapidocr import RapidOCR
        except ImportError:
            from rapidocr_onnxruntime import RapidOCR
        import logging

        for name in list(logging.root.manager.loggerDict):          # 它自己的提示信息不往窗口里打，免得盖住正常的记录
            if "rapidocr" in name.lower():
                logging.getLogger(name).setLevel(logging.ERROR)
        engine = RapidOCR()
        full = _full_call(engine)
        _reader = lambda img: _texts(full(img))          # noqa: E731
        _itemizer = lambda img: _items(full(img))        # noqa: E731
        _raw = full
        _liner = lambda img: _lines(engine(img, use_det=False, use_cls=False, use_rec=True))          # noqa: E731
        _state = "ok"
    except Exception as e:  # noqa: BLE001  装没装、能不能加载，都只是“有没有 OCR”的区别
        _state, _error = "missing", f"{type(e).__name__}: {e}"


def set_reader(fn: Callable[[np.ndarray], list[str]] | None, line: Any = "same") -> None:
    """换成别的读字函数（自测用）；传 None 恢复成没试过的状态。
    line 是单行读法：不给 = 用同一个函数；给 None = 假装这台机器没有单行读法；也可以给一个返回 [(字, 把握)] 的函数。"""
    global _reader, _liner, _itemizer, _state, _line_fails, _line_error, _items_error, _items_checked
    _reader, _state, _line_fails, _line_error, _items_error, _items_checked = fn, ("ok" if fn else "untried"), 0, "", "", False
    if fn is None:
        _itemizer = None
    if fn is None or line is None:
        _liner = None
    elif line == "same":
        _liner = lambda img: [(t, 1.0) for t in fn(img)]          # noqa: E731
    else:
        _liner = line


def set_items(fn: Callable[[np.ndarray], list[tuple[str, tuple[int, int, int, int], float]]] | None) -> None:
    """换成别的“带位置的读字”函数（自测用）；传 None = 没有。"""
    global _itemizer, _state
    _itemizer = fn
    if fn is not None:
        _state = "ok"


def available() -> bool:
    if _state == "untried":
        _load()
    return _state == "ok"


def read_items(img: np.ndarray) -> list[tuple[str, tuple[int, int, int, int], float]]:
    """检测 + 识别，连位置一起给：[(字, (x, y, 宽, 高), 把握)]，坐标是 img 自己的像素。读不了返回 []。"""
    out = read_items_or_none(img)
    return out if out is not None else []


def read_items_or_none(img: np.ndarray) -> list[tuple[str, tuple[int, int, int, int], float]] | None:
    """和 read_items 一样，但分得清“画面上没有字”（[]）和“这一下根本没读成”（None：组件不在、读的时候出错了）。
    挂机恢复用它：没读成 = 看不见画面上写的是什么，那就一下都不许点。"""
    global _items_error, _items_checked
    if not available() or _itemizer is None or img is None or img.size == 0:
        return None
    try:
        out = [(t, b, s) for t, b, s in _itemizer(img) if t]
    except Exception as e:  # noqa: BLE001
        _items_error = f"读的时候出错了：{type(e).__name__}: {e}"[:300]
        return None
    if not out and not _items_checked and _reader is not None:       # 一段都没有：是画面上真没字，还是“字读到了、位置没拿到”？核一次
        _items_checked = True
        try:
            texts = [t for t in _reader(img) if t]
            if texts:
                shape = ""
                if _raw is not None:
                    res = _raw(img)
                    names = [a for a in dir(res) if not a.startswith("_") and not callable(getattr(res, a, None))][:14]
                    shape = f"；结果是 {type(res).__name__}，里面有 {'、'.join(names)}"
                _items_error = f"同一张图不带位置能读到 {len(texts)} 段字，带位置的一段都没拿到{shape}"[:400]
        except Exception as e:  # noqa: BLE001
            _items_error = f"核对的时候出错了：{type(e).__name__}: {e}"[:300]
    return out


def items_problem() -> str:
    """“带位置的读字”要是出过问题，返回一句说明（只说一次）；没问题返回空串。"""
    global _items_error
    note, _items_error = _items_error, ""
    return note


def why_missing() -> str:
    return _error


def line_mode() -> str:
    """单行读法现在能不能用（写进记录里，方便排查）。"""
    if not available():
        return "没有 OCR"
    return "可用" if _liner is not None else ("不可用：" + (_line_error or "这个版本不支持"))


def read_texts(img: np.ndarray) -> list[str]:
    """检测 + 识别：img 是 BGR 图，返回读到的每一段字；读不了返回 []。注意小图要先用 on_canvas 贴到大画布上。"""
    if not available() or _reader is None:
        return []
    try:
        return [t for t in _reader(img) if t]
    except Exception:  # noqa: BLE001
        return []


def read_line(img: np.ndarray) -> str:
    """只识别：img 就是裁好的一行字。读不了、或者把握太低，返回空串。"""
    global _liner, _line_fails, _line_error
    if not available() or _liner is None or img is None or img.size == 0:
        return ""
    try:
        got = _liner(img)
        _line_fails = 0
    except Exception as e:  # noqa: BLE001
        _line_fails += 1
        _line_error = f"{type(e).__name__}: {e}"
        if _line_fails >= 3:            # 这个版本的 RapidOCR 用不了“只识别”：以后都走检测那条路
            _liner = None
        return ""
    context["line"] = [(t, round(s, 2)) for t, s in got]
    return "".join(t for t, s in got if t and s >= LINE_MIN_SCORE)


# ---- 把一小块里的字准备成好读的样子 ----
def cut(img: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """box 是 1280×720 坐标；img 是原始截图（多大都行），从原图上取，比先缩到 720p 再放大清楚。"""
    k = img.shape[1] / 1280.0
    x, y, w, h = box
    return img[max(0, int(round(y * k))):int(round((y + h) * k)), max(0, int(round(x * k))):int(round((x + w) * k))]


def ink_of(crop: np.ndarray, ink: str, soft: bool = False) -> np.ndarray:
    """哪些像素是笔画（0～1）。white：带描边的白字（名字横条、敌人的名字）；dark：浅底上的深色字（对话框里的名字）。
    soft=False 卡得严，用来找字在哪（不会把横条的圆角、背景里的亮块算进来）；soft=True 把笔画边上半透明的那一圈也算上，
    描出来的字更粗更完整，用来给 OCR 读。"""
    if ink == "white":
        lo, span = (140.0, 75.0) if soft else (175.0, 60.0)
        return np.clip((crop.min(axis=2).astype(np.float32) - lo) / span, 0.0, 1.0)
    hi, span = (190.0, 75.0) if soft else (170.0, 60.0)
    return np.clip((hi - crop.max(axis=2).astype(np.float32)) / span, 0.0, 1.0)


def bands(ink: np.ndarray, max_lines: int = 1) -> list[tuple[int, int, int, int]]:
    """笔画图 → 每一行字的范围 (x0, y0, x1, y1)，从上到下。没有像样的字返回 []。"""
    solid = ink > 0.5
    rows = solid.sum(axis=1) >= 2
    bridge = 2 if max_lines == 1 else 0             # 只有一行字时，中间断一两行还算同一行；两行字的名字（招募页）行距很小，不能连
    runs: list[list[int]] = []
    for y, on in enumerate(rows):
        if not on:
            continue
        if runs and y - runs[-1][1] <= bridge + 1:
            runs[-1][1] = y
        else:
            runs.append([y, y])
    runs = [r for r in runs if r[1] - r[0] + 1 >= 6]
    if not runs:
        return []
    tall = max(r[1] - r[0] + 1 for r in runs)
    runs = [r for r in runs if r[1] - r[0] + 1 >= 0.5 * tall]
    if len(runs) > max_lines:                       # 行数比该有的多：留最高的几行
        keep = sorted(sorted(runs, key=lambda r: r[0] - r[1])[:max_lines])
        runs = keep
    out = []
    for y0, y1 in runs:
        cols = np.where(solid[y0:y1 + 1].sum(axis=0) >= 1)[0]
        if len(cols) < 4:
            continue
        out.append((int(cols[0]), y0, int(cols[-1]) + 1, y1 + 1))
    return out


def _pad_box(b: tuple[int, int, int, int], shape: tuple[int, ...], frac: float = 0.22) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = b
    m = max(3, int(round((y1 - y0) * frac)))
    return max(0, x0 - m), max(0, y0 - m), min(shape[1], x1 + m), min(shape[0], y1 + m)


def _tall_enough(img: np.ndarray, want: int = 48) -> np.ndarray:
    """识别模型会把一行字缩放到 48 像素高：字太小的先用好一点的办法放大，比它自己拉伸清楚。"""
    import cv2

    h = img.shape[0]
    if h >= want:
        return img
    k = min(3.0, want / max(1, h))
    return cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)


def line_images(crop: np.ndarray, ink: str | None, max_lines: int = 1) -> list[dict[str, Any]]:
    """把一小块分成一行一行：每行给出 白底黑字的图（bw）、原图（raw）、字有多高（h）。分不出来返回 []。"""
    import cv2

    if not ink or crop.size == 0:
        return []
    soft = ink_of(crop, ink, soft=True)
    out = []
    found = bands(ink_of(crop, ink), max_lines)
    for i, b in enumerate(found):
        x0, y0, x1, y1 = _pad_box(b, crop.shape)
        if i > 0:                                   # 两行字挨得近：留白不要伸到上一行 / 下一行的笔画里
            y0 = max(y0, (found[i - 1][3] + b[1] + 1) // 2)
        if i + 1 < len(found):
            y1 = min(y1, (b[3] + found[i + 1][1]) // 2)
        bw = (255.0 - soft[y0:y1, x0:x1] * 255.0).astype(np.uint8)
        edge = max(4, (b[3] - b[1]) // 4)
        bw = cv2.cvtColor(cv2.copyMakeBorder(bw, edge, edge, edge, edge, cv2.BORDER_CONSTANT, value=255), cv2.COLOR_GRAY2BGR)
        out.append({"bw": _tall_enough(bw), "raw": _tall_enough(np.ascontiguousarray(crop[y0:y1, x0:x1])), "h": b[3] - b[1]})
    return out


def on_canvas(img: np.ndarray, text_h: float, fill: Any = None) -> np.ndarray:
    """把一小块贴到大画布中间，让“检测”看到的字是四十像素左右高（它会把短边拉到 736）。fill 不给 = 用这一块边上的颜色。"""
    h, w = img.shape[:2]
    side = int(max(h + 40, min(1600, round(max(8.0, text_h) * 736.0 / 40.0))))
    cw = int(max(side, w + 80))
    if fill is None:
        ring = np.concatenate([img[0], img[-1], img[:, 0], img[:, -1]]).reshape(-1, 3)
        fill = [int(v) for v in np.median(ring, axis=0)]
    canvas = np.empty((side, cw, 3), np.uint8)
    canvas[:] = fill
    y, x = (side - h) // 2, (cw - w) // 2
    canvas[y:y + h, x:x + w] = img
    return canvas


def label_reads(img: np.ndarray, box: tuple[int, int, int, int], ink: str | None = "white", lines: int = 1,
                prefer: str | None = None) -> Iterator[tuple[str, str]]:
    """读一块已知位置的字，几种读法轮着来，每种给出 (读法, 读到的字)。调用方拿去核对，对上了就不用往下要了。

    ink：这一块的字是什么样的（white / dark / None = 不知道，整块当一行）；lines：最多几行；prefer：上次哪种读法读对了，这次先试它。
    """
    crop = cut(img, box)
    if crop.size == 0 or crop.shape[0] < 6 or crop.shape[1] < 6 or not available():
        return
    rows = line_images(crop, ink, lines)
    guess_h = max(r["h"] for r in rows) if rows else crop.shape[0] * 0.6
    plans: list[tuple[str, Callable[[], str]]] = []
    if rows:
        plans.append(("单行·描字", lambda: "".join(read_line(r["bw"]) for r in rows)))
        plans.append(("单行·原图", lambda: "".join(read_line(r["raw"]) for r in rows)))
        plans.append(("检测·描字", lambda: "".join("".join(read_texts(on_canvas(r["bw"], r["bw"].shape[0] * 0.55, 255))) for r in rows)))
    else:
        plans.append(("单行·原图", lambda: read_line(_tall_enough(crop))))
    plans.append(("检测·原图", lambda: "".join(read_texts(on_canvas(crop, guess_h)))))
    if prefer:
        plans.sort(key=lambda p: p[0] != prefer)
    for how, fn in plans:
        if how.startswith("单行") and _liner is None:
            continue
        context.clear()
        context.update(how=how, box=tuple(box), ink=ink, rows=len(rows))
        yield how, fn()


def read_box(norm: np.ndarray, box: tuple[int, int, int, int], zoom: float = 1.0) -> str:
    """读一小块里的字，返回第一种读法读到的非空结果；读不了返回空串。（zoom 是以前的参数，现在不用了。）"""
    for _how, text in label_reads(norm, box, ink=None):
        if text:
            return text
    return ""


def read_region(img: np.ndarray, box: tuple[int, int, int, int], zoom: float = 1.0, white: bool = False) -> str:
    """老接口：读一小块，white=True 表示是带描边的白字。新代码用 label_reads（能拿名单去核对每一种读法的结果）。"""
    for _how, text in label_reads(img, box, ink="white" if white else None):
        if text:
            return text
    return ""
