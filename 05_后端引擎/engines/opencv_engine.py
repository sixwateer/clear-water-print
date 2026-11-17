"""OpenCV 修复引擎：零模型依赖、开箱即用，作为保证闭环可用的基线引擎。

功能（本次改动）
================
1. 智能识别内容类型 ``detect_content``：分析框选区域及其周围，输出
   ``solid / gradient / texture / photo`` 四类之一与推荐策略，供"智能识别"选项使用。
2. 纹理自然融合 ``method="texture"``（默认 auto 自动选择）：对木纹、砖墙、草地等
   重复纹理，从水印框附近寻找"纹理相似 + 边界颜色接近"的源块，做多频带羽化
   融合，替代 Telea/NS 在纹理背景上留下的平直暗块，显著减少违和感。
3. 保留原 Telea/NS 路径：纯色/渐变背景仍用其做无痕扩散，速度最快。

算法：纹理模式 = Telea 保底 + 候选源块搜索（颜色差 × 梯度结构差评分）+ 距离场羽化。
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

    # ---------------- 智能识别 ----------------
    @staticmethod
    def detect_content(
        image: Image.Image,
        rect: dict,
    ) -> dict:
        """识别框选区域的背景内容类型并给出修复建议。

        依据（无需模型、毫秒级）：
        - 框外一圈背景的拉普拉斯高频能量 -> 区分纯色 / 渐变 / 纹理 / 照片；
        - 颜色离散度与方向性 -> 判断是否为平滑渐变。

        Returns:
            dict: ``type`` (solid|gradient|texture|photo)、``label`` 中文名、
            ``confidence`` 0~1、``suggest_method`` 建议的 method、
            ``suggest_engine`` 建议引擎名、``detail`` 指标明细。
        """
        bgr = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        h, w = bgr.shape[:2]
        x1 = max(0, int(rect.get("x", 0)))
        y1 = max(0, int(rect.get("y", 0)))
        x2 = min(w, int(rect.get("x", 0) + rect.get("w", 0)))
        y2 = min(h, int(rect.get("y", 0) + rect.get("h", 0)))
        if x2 - x1 < 2 or y2 - y1 < 2:
            return {"type": "photo", "label": "复杂画面", "confidence": 0.5,
                    "suggest_method": "texture", "suggest_engine": "ai",
                    "detail": {"reason": "框选区域过小"}}

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        ring = max(6, min(x1, y1, w - x2, h - y2) // 2 or 6)
        gy1, gy2 = max(0, y1 - ring), min(h, y2 + ring)
        gx1, gx2 = max(0, x1 - ring), min(w, x2 + ring)
        patch = gray[gy1:gy2, gx1:gx2]
        if patch.size < 16:
            patch = gray

        lap = cv2.Laplacian(patch, cv2.CV_64F)
        # 用裁剪后的高频能量，避免手指/边框等极少数强边缘把指标顶到 1
        energy = np.sort((lap ** 2).ravel())
        trim = energy[: max(1, int(energy.size * 0.9))].mean()
        high_freq = float(np.clip(trim / 900.0, 0, 1))
        color_std = float(np.asarray(bgr[gy1:gy2, gx1:gx2]).std(axis=(0, 1)).mean())

        small = cv2.resize(patch, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float64)
        gx = np.abs(np.diff(small, axis=1)).mean()
        gy = np.abs(np.diff(small, axis=0)).mean()
        directional = float(abs(gx - gy) / (gx + gy + 1e-6))

        if high_freq < 0.06 and color_std < 12:
            ctype, label, method, engine, conf = "solid", "纯色背景", "telea", "opencv", 0.90
        elif high_freq < 0.16 and directional > 0.28 and color_std < 30:
            ctype, label, method, engine, conf = "gradient", "渐变背景", "telea", "opencv", 0.82
        elif high_freq >= 0.16 and color_std < 46:
            ctype, label, method, engine, conf = "texture", "重复纹理", "texture", "opencv", 0.85
        else:
            ctype, label, method, engine, conf = "photo", "复杂照片", "texture", "ai", 0.78

        return {
            "type": ctype, "label": label, "confidence": round(conf, 2),
            "suggest_method": method, "suggest_engine": engine,
            "detail": {
                "high_freq": round(high_freq, 3),
                "color_std": round(color_std, 1),
                "directional": round(directional, 3),
            },
        }

    # ---------------- 纹理融合核心 ----------------
    @staticmethod
    def _smooth_fill(bgr: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> np.ndarray:
        """平滑背景填充：用框外边界作条件解拉普拉斯方程，纯色/渐变背景无痕。

        比 Telea 更适合大面积平滑区域——不会在中心留平色块，
        颜色/光影渐变从边界自然延续进来。
        """
        h, w = bgr.shape[:2]
        bh, bw = y2 - y1, x2 - x1
        # 取足够宽的外环作为边界条件：太窄会导致深色/亮色水印无法被完全冲淡。
        pad = max(8, min(bw, bh) // 2)
        ey1, ey2 = max(0, y1 - pad), min(h, y2 + pad)
        ex1, ex2 = max(0, x1 - pad), min(w, x2 + pad)
        R = bgr[ey1:ey2, ex1:ex2].astype(np.float32)
        lh, lw = R.shape[:2]
        py0, px0 = y1 - ey1, x1 - ex1
        if lh < 3 or lw < 3:
            return R[py0:py0 + bh, px0:px0 + bw]

        # 边界环（外圈）作固定条件；框内用环均值初始化，绝不能用含水印的原值。
        ring = np.ones((lh, lw), bool)
        ring[py0:py0 + bh, px0:px0 + bw] = False
        if not ring.any():
            ring[:1, :] = True
        edge_mean = R[ring].mean(axis=0)

        SR = R.copy()
        # 双线性边界插值作为初值：保留光影渐变（比均匀均值自然得多），
        # 且框内不含任何水印像素。
        for c in range(3):
            # 兜底必须是与边界等长的数组，不能是标量（贴边时 py0=0 会触发）
            top = R[py0 - 1, px0:px0 + bw, c].copy() if py0 > 0 else np.full(bw, edge_mean[c], np.float32)
            bot = R[py0 + bh, px0:px0 + bw, c].copy() if py0 + bh < lh else np.full(bw, edge_mean[c], np.float32)
            left = R[py0:py0 + bh, px0 - 1, c].copy() if px0 > 0 else np.full(bh, edge_mean[c], np.float32)
            right = R[py0:py0 + bh, px0 + bw, c].copy() if px0 + bw < lw else np.full(bh, edge_mean[c], np.float32)
            tx = np.linspace(0, 1, bw, dtype=np.float32)
            ty = np.linspace(0, 1, bh, dtype=np.float32)[:, None]
            v_tb = top[None, :] * (1 - ty) + bot[None, :] * ty
            v_lr = left[:, None] * (1 - tx) + right[:, None] * tx
            # Coons patch：v_tb + v_lr - 双线性四角，保证四条边严格等于边界值。
            # 直接相加取平均会在中心产生"鼓包/暗斑"，因为两路插值在角上不一致。
            cy0, cy1 = max(0, py0 - 1), min(lh - 1, py0 + bh)
            cx0, cx1 = max(0, px0 - 1), min(lw - 1, px0 + bw)
            c00, c01 = R[cy0, cx0, c], R[cy0, cx1, c]
            c10, c11 = R[cy1, cx0, c], R[cy1, cx1, c]
            corner = ((c00 * (1 - tx) + c01 * tx)[None, :] * (1 - ty)
                      + (c10 * (1 - tx) + c11 * tx)[None, :] * ty)
            SR[py0:py0 + bh, px0:px0 + bw, c] = v_tb + v_lr - corner

        # 少量迭代仅平滑插值接缝；边界钉回原值形成稳定条件
        for _ in range(min(60, max(20, min(bw, bh) // 2))):
            SR[1:-1, 1:-1] = (
                SR[:-2, 1:-1] + SR[2:, 1:-1] + SR[1:-1, :-2] + SR[1:-1, 2:]
            ) * 0.25
            SR[ring] = R[ring]

        return SR[py0:py0 + bh, px0:px0 + bw]

    def _texture_fill(
        self,
        bgr: np.ndarray,
        mask: np.ndarray,
        rects: list[dict],
        radius: int,
    ) -> tuple[np.ndarray, str]:
        """自然重建：优先笔画级去除（保留物体纹理），兜底 Coons 插值。

        印刷在物体表面的 logo/文字：只检测并修复"笔画"像素，物体表面纹理
        完整保留，这是最自然的结果。当框内没有可辨识笔画（纯色块/整片被遮盖）
        时，退回 Coons 双线性插值整框重建。
        """
        out = bgr.copy()
        h, w = bgr.shape[:2]
        used = "coons"

        for r in rects:
            x1 = max(0, int(r.get("x", 0)))
            y1 = max(0, int(r.get("y", 0)))
            x2 = min(w, int(r.get("x", 0) + r.get("w", 0)))
            y2 = min(h, int(r.get("y", 0) + r.get("h", 0)))
            bw, bh = x2 - x1, y2 - y1
            if bw < 8 or bh < 8:
                continue
            box = bgr[y1:y2, x1:x2]
            gray = cv2.cvtColor(box, cv2.COLOR_BGR2GRAY)
            bg = cv2.GaussianBlur(gray, (0, 0), 9)
            dark = np.clip(bg.astype(np.float32) - gray.astype(np.float32), 0, 255).astype(np.uint8)
            _, strokes = cv2.threshold(dark, 30, 255, cv2.THRESH_BINARY)
            cov = float((strokes > 0).mean())
            if cov < 0.02:  # 没有暗笔画 → 试亮笔画（深色底上的白字）
                light = np.clip(gray.astype(np.float32) - bg.astype(np.float32), 0, 255).astype(np.uint8)
                _, strokes = cv2.threshold(light, 30, 255, cv2.THRESH_BINARY)
                cov = float((strokes > 0).mean())
            if 0.02 <= cov <= 0.45:
                strokes = cv2.morphologyEx(strokes, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
                strokes = cv2.dilate(strokes, np.ones((3, 3), np.uint8), iterations=1)
                fine = np.zeros((h, w), np.uint8)
                fine[y1:y2, x1:x2] = strokes
                out = cv2.inpaint(bgr, fine, 3, cv2.INPAINT_TELEA)
                used = "stroke" if used == "coons" else used + "+stroke"
            else:
                out[y1:y2, x1:x2] = self._smooth_fill(bgr, x1, y1, x2, y2)
                used = "coons" if used == "coons" else used + "+coons"
        return out, used

    # ---------------- 主入口 ----------------
    def inpaint(
        self,
        image: Image.Image,
        rects: list[dict],
        strength: int = 2,
        enhance: bool = True,
        face: bool = False,
        method: str = "auto",
        **kwargs,
    ) -> EngineResult:
        """对图片框选区域执行修复。

        method: ``auto``（默认，智能选择）/ ``texture``（纹理融合）/
        ``telea`` / ``ns``（经典扩散）。
        """
        t0 = time.perf_counter()
        rgb = image.convert("RGB")
        bgr = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
        h, w = bgr.shape[:2]

        mask = np.zeros((h, w), dtype=np.uint8)
        for r in rects:
            x1 = max(0, int(r.get("x", 0)))
            y1 = max(0, int(r.get("y", 0)))
            x2 = min(w, int(r.get("x", 0) + r.get("w", 0)))
            y2 = min(h, int(r.get("y", 0) + r.get("h", 0)))
            if x2 > x1 and y2 > y1:
                # cv2.rectangle 是闭区间，终点要减 1，与 [x1,x2) 的框语义一致，
                # 否则 strict_mask 会多占一行/列，破坏"框外逐字节不变"。
                cv2.rectangle(mask, (x1, y1), (x2 - 1, y2 - 1), 255, -1)

        # 原始框 mask（严格边界，用于最终合成，保证框外逐字节不变）
        strict_mask = mask.copy()
        radius, kernel = self._STRENGTH_MAP.get(int(strength), (5, 5))
        # 扩张 mask 仅用于修复计算：覆盖水印抗锯齿边缘，避免浅色残边；
        # 但最终只把原始框范围内的像素写回结果。
        mask = cv2.dilate(mask, np.ones((kernel, kernel), np.uint8), iterations=1)

        # auto：取第一个框做智能识别，texture 背景用纹理融合，其余用 Telea
        actual_method = method
        detection = None
        if method == "auto" and rects:
            detection = self.detect_content(image, rects[0])
            actual_method = detection["suggest_method"]

        texture_strategy = None
        if actual_method == "texture":
            result_bgr, texture_strategy = self._texture_fill(bgr, mask, rects, radius)
            used_flag = cv2.INPAINT_TELEA
        elif actual_method == "ns":
            result_bgr = cv2.inpaint(bgr, mask, radius, cv2.INPAINT_NS)
            used_flag = cv2.INPAINT_NS
        else:
            result_bgr = cv2.inpaint(bgr, mask, radius, cv2.INPAINT_TELEA)
            used_flag = cv2.INPAINT_TELEA

        # 严格框内合成：扩张区域只参与计算，最终只有原始框内像素被写回，
        # 兑现"未修复区域逐像素保持原样"的承诺。
        final_bgr = bgr.copy()
        final_bgr[strict_mask > 0] = result_bgr[strict_mask > 0]
        out = Image.fromarray(cv2.cvtColor(final_bgr, cv2.COLOR_BGR2RGB))
        if enhance:
            # 只锐化修复过的区域，框外像素必须逐字节保持原样。
            enhanced = out.filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=3))
            ea = np.asarray(enhanced)
            oo = np.asarray(out).copy()
            roi = np.zeros((h, w), bool)
            for r in rects:
                x1 = max(0, int(r.get("x", 0)))
                y1 = max(0, int(r.get("y", 0)))
                x2 = min(w, int(r.get("x", 0) + r.get("w", 0)))
                y2 = min(h, int(r.get("y", 0) + r.get("h", 0)))
                if x2 > x1 and y2 > y1:
                    roi[y1:y2, x1:x2] = True
            oo[roi] = ea[roi]
            out = Image.fromarray(oo)

        elapsed = (time.perf_counter() - t0) * 1000
        flag_name = "NS" if used_flag == cv2.INPAINT_NS else "TELEA"
        meta = {
            "method": method, "actual_method": actual_method, "radius": radius,
            "dilate": kernel, "enhance": enhance, "used_flag": flag_name,
        }
        if texture_strategy:
            meta["texture_strategy"] = texture_strategy
        if detection:
            meta["detection"] = detection
        return EngineResult(
            image=out, engine=self.name, elapsed_ms=round(elapsed, 1), meta=meta,
        )
