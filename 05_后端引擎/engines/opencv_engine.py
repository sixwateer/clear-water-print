"""OpenCV 修复引擎：零模型依赖、开箱即用，作为保证闭环可用的基线引擎。

算法：基于 OpenCV 的 Navier-Stokes / Telea 图像修复，对框选区域重建像素。
画质增强：可选的非锐化掩膜（Unsharp Mask）提升局部清晰度。
"""

import time

import cv2
import numpy as np
from PIL import Image, ImageFilter

from .base import BaseEngine, EngineResult


class OpenCVEngine(BaseEngine):
    name = "opencv"
    label = "OpenCV 快速修复（无需模型）"
    requires_model = False

    # 强度 -> (inpaint 半径, 膨胀核大小)。强度越高，覆盖边缘越充分。
    _STRENGTH_MAP = {
        1: (3, 3),
        2: (5, 5),
        3: (7, 9),
    }

    def inpaint(
        self,
        image: Image.Image,
        rects: list[dict],
        strength: int = 2,
        enhance: bool = True,
        face: bool = False,
        method: str = "telea",
        **kwargs,
    ) -> EngineResult:
        t0 = time.perf_counter()
        rgb = image.convert("RGB")
        bgr = cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)
        h, w = bgr.shape[:2]

        # 构建掩码：框选区域置 255
        mask = np.zeros((h, w), dtype=np.uint8)
        for r in rects:
            x1 = max(0, int(r["x"]))
            y1 = max(0, int(r["y"]))
            x2 = min(w, int(r["x"] + r["w"]))
            y2 = min(h, int(r["y"] + r["h"]))
            if x2 > x1 and y2 > y1:
                cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)

        radius, kernel = self._STRENGTH_MAP.get(int(strength), (5, 5))
        # 轻微膨胀，覆盖水印抗锯齿边缘，减少残留描边
        mask = cv2.dilate(mask, np.ones((kernel, kernel), np.uint8), iterations=1)

        flag = cv2.INPAINT_TELEA if method == "telea" else cv2.INPAINT_NS
        result = cv2.inpaint(bgr, mask, radius, flag)

        out = Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB))

        if enhance:
            # 非锐化掩膜：仅增强局部对比，尽量保留原始细节
            out = out.filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=3))

        elapsed = (time.perf_counter() - t0) * 1000
        return EngineResult(
            image=out,
            engine=self.name,
            elapsed_ms=round(elapsed, 1),
            meta={"method": method, "radius": radius, "dilate": kernel, "enhance": enhance},
        )
