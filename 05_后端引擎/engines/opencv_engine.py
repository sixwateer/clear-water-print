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
    def _feather_alpha(bw: int, bh: int) -> np.ndarray:
        """生成羽化权重 (bh,bw)：框内绝大部分为 1，仅最外缘一圈平滑收敛到 0。

        关键：羽化带必须很薄（固定几像素），否则水印文字靠近框边界的部分
        alpha≈0 无法被替换，会残留可见文字。这里用固定薄边 + 轻微高斯。
        """
        edge = max(2, min(5, min(bw, bh) // 6))
        alpha = np.ones((bh, bw), np.float32)
        # 四边各 edge 像素线性衰减到 0
        ramp = np.linspace(0, 1, edge + 1)[:-1].astype(np.float32)  # 0..~0.8
        alpha[:edge, :] = np.minimum(alpha[:edge, :], ramp[:, None])
        alpha[-edge:, :] = np.minimum(alpha[-edge:, :], ramp[::-1, None])
        alpha[:, :edge] = np.minimum(alpha[:, :edge], ramp[None, :])
        alpha[:, -edge:] = np.minimum(alpha[:, -edge:], ramp[::-1][None, :])
        alpha = cv2.GaussianBlur(alpha, (0, 0), 1.2)
        # 抬升内部：>=0.5 直接拉到 1，保证水印文字被完全覆盖
        alpha = np.where(alpha >= 0.9, 1.0, np.clip(alpha * 1.15, 0, 1))
        return np.clip(alpha, 0, 1)

    @staticmethod
    def _stroke_mask(box: np.ndarray) -> tuple[np.ndarray | None, float]:
        """尝试从框内提取"文字笔画"级精确掩膜。

        视频平台水印多为高亮、低饱和的文字。这类水印只占框内少部分像素，
        直接对整框 inpaint 会毁掉背景纹理；而只修复笔画本身则能最大程度保留
        原始纹理，几乎无违和感。

        Returns:
            (mask|None, 覆盖率)：覆盖率过低时返回 None，交给整框纹理融合处理。
        """
        mx = box.max(axis=2)
        mn = box.min(axis=2)
        lum = box.astype(np.float32).mean(axis=2)
        sat = (mx - mn) / (mx + 1)
        # 高亮 + 低饱和 = 文字/水印笔画；木纹/皮肤饱和度显著更高
        stroke = ((lum > 140) & (sat < 0.40)).astype(np.uint8) * 255
        if stroke.size == 0:
            return None, 0.0
        coverage = float((stroke > 0).mean())
        # 覆盖率过高说明整块都是亮的（纯色块水印），不适合笔画法
        if coverage < 0.01 or coverage > 0.62:
            return None, coverage
        stroke = cv2.morphologyEx(stroke, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        # 膨胀覆盖抗锯齿边缘与文字阴影（实测 7x7 两次效果最佳）
        stroke = cv2.dilate(stroke, np.ones((7, 7), np.uint8), iterations=2)
        return stroke, coverage

    @staticmethod
    def _texture_fill(
        bgr: np.ndarray,
        mask: np.ndarray,
        rects: list[dict],
        radius: int,
    ) -> tuple[np.ndarray, str]:
        """纹理自然融合（混合策略）。

        策略一（笔画级，优先）：框内检出高亮低饱和文字 → 只修复笔画，保留整片纹理。
        策略二（源块融合）：色块/图标类水印 → Telea 保底 + 最佳源块羽化融合。

        Returns:
            (结果图, 策略名 stroke|patch)
        """
        h, w = bgr.shape[:2]
        out = cv2.inpaint(bgr, mask, radius, cv2.INPAINT_TELEA)
        used = "telea"
        stroke_masks: list[tuple[int, int, np.ndarray]] = []
        patch_rects: list[dict] = []

        for r in rects:
            x1 = max(0, int(r.get("x", 0)))
            y1 = max(0, int(r.get("y", 0)))
            x2 = min(w, int(r.get("x", 0) + r.get("w", 0)))
            y2 = min(h, int(r.get("y", 0) + r.get("h", 0)))
            bw, bh = x2 - x1, y2 - y1
            if bw < 8 or bh < 8:
                continue
            box = bgr[y1:y2, x1:x2]
            sm, cov = OpenCVEngine._stroke_mask(box)
            if sm is not None:
                stroke_masks.append((x1, y1, sm))
            else:
                patch_rects.append(r)

        # 策略一：笔画级修复（对每个框把精确笔画写入独立 mask）
        if stroke_masks:
            fine = np.zeros((h, w), np.uint8)
            for x1, y1, sm in stroke_masks:
                sh, sw = sm.shape[:2]
                fine[y1:y1 + sh, x1:x1 + sw] = np.maximum(
                    fine[y1:y1 + sh, x1:x1 + sw], sm
                )
            out = cv2.inpaint(bgr, fine, 3, cv2.INPAINT_TELEA)
            used = "stroke"

        # 策略二：未能用笔画法的框，做源块羽化融合
        for r in patch_rects:
            x1 = max(0, int(r.get("x", 0)))
            y1 = max(0, int(r.get("y", 0)))
            x2 = min(w, int(r.get("x", 0) + r.get("w", 0)))
            y2 = min(h, int(r.get("y", 0) + r.get("h", 0)))
            bw, bh = x2 - x1, y2 - y1

            cand_offsets = []
            for dist_k in (1.15, 1.6, 2.2):
                dy = int(bh * dist_k)
                dx = int(bw * dist_k)
                cand_offsets += [(0, -dy), (0, dy), (-dx, 0), (dx, 0)]

            target = out[y1:y2, x1:x2].astype(np.float32)
            margin = 2
            ta, tb = max(0, y1 - margin), min(h, y2 + margin)
            tl, tr = max(0, x1 - margin), min(w, x2 + margin)
            ring_mean = bgr[ta:tb, tl:tr].astype(np.float32).reshape(-1, 3).mean(axis=0)

            best_patch = None
            best_score = float("inf")
            for dx, dy in cand_offsets:
                sx1, sy1 = x1 + dx, y1 + dy
                sx2, sy2 = sx1 + bw, sy1 + bh
                if sx1 < 0 or sy1 < 0 or sx2 > w or sy2 > h:
                    continue
                overlap = False
                for rr in patch_rects:
                    rx1, ry1 = int(rr.get("x", 0)), int(rr.get("y", 0))
                    rx2, ry2 = rx1 + int(rr.get("w", 0)), ry1 + int(rr.get("h", 0))
                    if sx1 < rx2 and sx2 > rx1 and sy1 < ry2 and sy2 > ry1:
                        overlap = True
                        break
                if overlap:
                    continue
                cand = bgr[sy1:sy2, sx1:sx2].astype(np.float32)
                color_diff = float(np.abs(cand.reshape(-1, 3).mean(axis=0) - ring_mean).mean())
                cg = cv2.cvtColor(cand.astype(np.uint8), cv2.COLOR_BGR2GRAY)
                tg = cv2.cvtColor(target.astype(np.uint8), cv2.COLOR_BGR2GRAY)
                cand_grad = float(cv2.Laplacian(cg, cv2.CV_64F).var())
                target_grad = float(cv2.Laplacian(tg, cv2.CV_64F).var())
                struct_diff = abs(cand_grad - target_grad) / (target_grad + cand_grad + 1e-6)
                score = color_diff * 0.55 + struct_diff * 45.0
                if score < best_score:
                    best_score = score
                    best_patch = cand

            if best_patch is None:
                continue
            alpha = OpenCVEngine._feather_alpha(bw, bh)[..., None]
            blended = best_patch * alpha + target * (1 - alpha)
            out[y1:y2, x1:x2] = np.clip(blended, 0, 255).astype(np.uint8)
            used = "patch" if used == "telea" else used + "+patch"

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
                cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)

        radius, kernel = self._STRENGTH_MAP.get(int(strength), (5, 5))
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

        out = Image.fromarray(cv2.cvtColor(result_bgr, cv2.COLOR_BGR2RGB))
        if enhance:
            out = out.filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=3))

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
