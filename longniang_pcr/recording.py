"""读录制文件夹。两种摆法都认：
- 原始录制：frames.jsonl + frames/（PNG / JPG 原图）
- 打包后解开的：meta/frames.jsonl + frames/*.jpg（1280×720）
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from . import imgio


class Rec:
    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self.name = self.folder.name
        meta = self.folder / "meta" / "frames.jsonl"
        self.packed = meta.exists()
        src = meta if self.packed else self.folder / "frames.jsonl"
        self.frames: list[dict[str, Any]] = [json.loads(line) for line in src.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.by_id: dict[int, dict[str, Any]] = {f["id"]: f for f in self.frames}

    def path(self, f: dict[str, Any]) -> Path:
        name = Path(str(f["file"]).replace("\\", "/")).name
        if self.packed:
            name = Path(name).stem + ".jpg"
        return self.folder / "frames" / name

    def image(self, fid: int) -> np.ndarray:
        p = self.path(self.by_id[fid])
        img = imgio.imread(p)
        if img is None:
            raise FileNotFoundError(str(p))
        return img
