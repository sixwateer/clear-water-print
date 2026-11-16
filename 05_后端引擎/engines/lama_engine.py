"""LaMA AI 修复引擎（可选，高质量）。

基于 large-mask inpainting 模型，对大块水印区域的重建效果显著优于传统算法。
依赖 torch + simple-lama-inpainting，模型约 200MB，首次运行自动下载。
依赖不满足时 ``available`` 返回 False，服务会自动降级到 OpenCV 引擎。

安装（可选）：
    pip install torch --index-url https://download.pytorch.org/whl/cu121
    pip install simple-lama-inpainting
"""

import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

from .base import BaseEngine, EngineResult

_MODEL_DIR = Path(__file__).resolve().parent.parent / "models"


class LamaEngine(BaseEngine):
    name = "lama"
    label = "LaMA AI 智能修复（高质量）"
    requires_model = True

    def __init__(self):
        self._model = None
        self._err: str | None = None

    def _load(self):
        if self._model is not None:
            return True
        if self._err:
            return False
        try:
            from simple_lama_inpainting import SimpleLama
            _MODEL_DIR.mkdir(parents=True, exist_ok=True)
            self._model = SimpleLama()
            return True
        except Exception as e:  # noqa: BLE001 - 依赖缺失时降级
            self._err = f"{type(e).__name__}: {e}"
            return False

    @property
    def available(self) -> bool:
        try:
            import torch  # noqa: F401
            import simple_lama_inpainting  # noqa: F401
        except ImportError:
            return False
        return True

    @property
    def error(self) -> str | None:
        return self._err

    def inpaint(
        self,
        image: Image.Image,
        rects: list[dict],
        strength: int = 2,
        enhance: bool = True,
        face: bool = False,
        **kwargs,
    ) -> EngineResult:
        t0 = time.perf_counter()
        if not self._load():
            raise RuntimeError(f"LaMA 引擎不可用: {self._err}")

        rgb = image.convert("RGB")
        w, h = rgb.size
        mask = Image.new("L", (w, h), 0)
        from PIL import ImageDraw

        d = ImageDraw.Draw(mask)
        pad = {1: 1, 2: 3, 3: 5}.get(int(strength), 3)
        for r in rects:
            x, y, rw, rh = int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"])
            d.rectangle([x - pad, y - pad, x + rw + pad, y + rh + pad], fill=255)

        result: Image.Image = self._model(rgb, mask)
        if enhance:
            result = result.filter(ImageFilter.UnsharpMask(radius=1.0, percent=100, threshold=3))

        elapsed = (time.perf_counter() - t0) * 1000
        return EngineResult(
            image=result,
            engine=self.name,
            elapsed_ms=round(elapsed, 1),
            meta={"enhance": enhance, "note": "large-mask inpainting"},
        )
