"""测试报告：边跑边往屏幕和文件里写，中途崩了也能留下已经跑完的部分。"""
from __future__ import annotations

import json
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def _jsonable(o: Any) -> Any:
    try:
        import numpy as np

        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except Exception:
        pass
    if isinstance(o, bytes):
        return o.decode("utf-8", "replace")
    return str(o)


class Report:
    def __init__(self, run_dir: Path, title: str):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.title = title
        self.data: dict[str, Any] = {
            "title": title,
            "started": time.strftime("%Y-%m-%d %H:%M:%S"),
            "errors": [],
            "problems": [],
        }
        self._txt = self.dir / "report.txt"
        self._json = self.dir / "report.json"
        self._txt.write_text("", encoding="utf-8")
        self.say(f"{title}    {self.data['started']}")

    # ---- 文字输出 ----
    def say(self, text: str = "") -> None:
        try:
            print(text, flush=True)
        except Exception:
            pass
        try:
            with self._txt.open("a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass

    def head(self, text: str) -> None:
        self.say("")
        self.say(f"== {text} ==")

    def info(self, text: str) -> None:
        self.say(f"  {text}")

    def ok(self, text: str) -> None:
        self.say(f"  [通过] {text}")

    def warn(self, text: str) -> None:
        self.say(f"  [注意] {text}")
        self.data["problems"].append({"level": "warn", "text": text})

    def bad(self, text: str) -> None:
        self.say(f"  [失败] {text}")
        self.data["problems"].append({"level": "fail", "text": text})

    # ---- 结构化数据 ----
    def put(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()

    def save(self) -> None:
        try:
            self._json.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=1, default=_jsonable),
                encoding="utf-8",
            )
        except Exception:
            pass

    @contextmanager
    def step(self, name: str):
        """一个测试步骤：出错只记录、不中断后面的步骤。"""
        self.head(name)
        t0 = time.perf_counter()
        try:
            yield
        except KeyboardInterrupt:
            raise
        except BaseException as e:  # noqa: BLE001  步骤之间互不影响
            tb = traceback.format_exc()
            self.say(f"  [出错] {type(e).__name__}: {e}")
            self.data["errors"].append({"step": name, "error": f"{type(e).__name__}: {e}", "traceback": tb})
            self.data["problems"].append({"level": "fail", "text": f"{name}：{type(e).__name__}: {e}"})
        finally:
            self.data.setdefault("step_seconds", {})[name] = round(time.perf_counter() - t0, 2)
            self.save()

    def finish(self) -> None:
        self.data["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.save()
