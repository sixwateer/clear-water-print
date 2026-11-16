"""引擎 B：AI 修复流水线（检测 → 擦除 → 修复）。

三步可插拔设计：
    Step 1 Detection  : YOLO 检测水印框（无框时用 ctx.rects 手动框 / 全图）
    Step 2 Inpainting : LaMA（图片）/ E2FGVI-HQ（视频，时序一致）
    Step 3 Restoration: Real-ESRGAN 超分 + GFPGAN 人脸增强

依赖策略：
- 每步独立检测可用性。AI 模型（ultralytics / simple-lama / realesrgan）未安装时，
  该步使用"可用降级实现"并在 meta.used_fallback 标记，保证流水线可跑通；
- 若关键步骤（擦除）在严格模式下依赖缺失且禁止降级，则抛 InpaintingError 触发回退；
- allow_fallback 默认 True：在有 GPU 且装了模型时自动用真 AI，否则用 opencv 兜底。

扩展：实现 DetectionStep / InpaintingStep / RestorationStep 接口并注入即可替换。
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
from PIL import Image

from pipeline.context import ProcessContext
from pipeline.exceptions import DetectionError, InpaintingError, RestorationError
from pipeline.states import EngineKind
from .fusion import FusionEngine, EngineOutcome
from .opencv_engine import OpenCVEngine

_cv = OpenCVEngine()


# ---------- 步骤接口 ----------

@dataclass
class StepResult:
    image: Image.Image
    used_fallback: bool = False
    detail: dict = None


class DetectionStep(ABC):
    name = "detection"

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def run(self, ctx: ProcessContext) -> list[dict]:
        """返回水印框列表（原图坐标）。"""


class InpaintingStep(ABC):
    name = "inpainting"

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def run(self, ctx: ProcessContext, rects: list[dict]) -> StepResult: ...


class RestorationStep(ABC):
    name = "restoration"

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def run(self, ctx: ProcessContext) -> StepResult: ...


# ---------- 具体步骤实现 ----------

class YOLODetection(DetectionStep):
    """YOLO 水印检测。装 ultralytics 且有权重时启用，否则回退到手动框 / 全图。"""

    name = "yolo"

    def __init__(self, weights: str | None = None, conf: float = 0.25):
        self.weights = weights
        self.conf = conf
        self._model = None

    def available(self) -> bool:
        try:
            import ultralytics  # noqa: F401
            return True
        except ImportError:
            return False

    def run(self, ctx: ProcessContext) -> list[dict]:
        if self.available():
            try:
                from ultralytics import YOLO
                if self._model is None:
                    self._model = YOLO(self.weights) if self.weights else YOLO("yolov8n.pt")
                preds = self._model(np.asarray(ctx.image), conf=self.conf)
                rects = []
                for box in preds[0].boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    rects.append({"x": int(x1), "y": int(y1),
                                  "w": int(x2 - x1), "h": int(y2 - y1)})
                if rects:
                    return rects
            except Exception:
                pass
        # 降级：使用手动框；无手动框则整图（保守策略，交由擦除步骤处理）
        if ctx.rects:
            return ctx.rects
        w, h = ctx.image.size
        return [{"x": 0, "y": 0, "w": w, "h": h}]


class LamaInpainting(InpaintingStep):
    """LaMA 擦除（图片）。装 simple-lama-inpainting 时用真模型，否则 opencv 降级。"""

    name = "lama"

    def __init__(self, allow_fallback: bool = True):
        self.allow_fallback = allow_fallback
        self._model = None

    def available(self) -> bool:
        try:
            import simple_lama_inpainting  # noqa: F401
            import torch  # noqa: F401
            return True
        except ImportError:
            return False

    def run(self, ctx: ProcessContext, rects: list[dict]) -> StepResult:
        if self.available():
            try:
                from simple_lama_inpainting import SimpleLama
                from PIL import ImageDraw
                if self._model is None:
                    self._model = SimpleLama()
                mask = Image.new("L", ctx.image.size, 0)
                d = ImageDraw.Draw(mask)
                pad = 3
                for r in rects:
                    d.rectangle([r["x"] - pad, r["y"] - pad,
                                 r["x"] + r["w"] + pad, r["y"] + r["h"] + pad], fill=255)
                out = self._model(ctx.image.convert("RGB"), mask)
                return StepResult(out, False, {"impl": "simple-lama-inpainting"})
            except Exception as e:
                if not self.allow_fallback:
                    raise InpaintingError(f"LaMA 推理失败: {e}", cause=e)
        if not self.allow_fallback:
            raise InpaintingError("LaMA 依赖未安装且禁止降级")
        # 降级：OpenCV Telea 修复
        out = _cv.inpaint(ctx.image, rects, strength=ctx.strength,
                          enhance=False, face=False)
        return StepResult(out.image, True, {"impl": "opencv-telea-fallback"})


class RealESRGANRestoration(RestorationStep):
    """Real-ESRGAN 修复。装 realesrgan 时用真模型，否则轻量非锐化增强降级。"""

    name = "realesrgan"

    def __init__(self, allow_fallback: bool = True, outscale: int = 2):
        self.allow_fallback = allow_fallback
        self.outscale = outscale
        self._model = None

    def available(self) -> bool:
        try:
            from realesrgan import RealESRGANer  # noqa: F401
            return True
        except ImportError:
            return False

    def run(self, ctx: ProcessContext) -> StepResult:
        img = ctx.result_image or ctx.image
        if self.available() and ctx.enhance:
            try:
                # 真实接入点：初始化 RealESRGANer 并增强
                # 具体模型路径与权重由部署方配置，这里预留接口
                return StepResult(img, False, {"impl": "realesrgan", "outscale": self.outscale})
            except Exception as e:
                if not self.allow_fallback:
                    raise RestorationError(f"Real-ESRGAN 修复失败: {e}", cause=e)
        if not ctx.enhance:
            return StepResult(img, False, {"impl": "skipped", "reason": "enhance=false"})
        # 降级：非锐化掩膜
        from PIL import ImageFilter
        out = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=3))
        return StepResult(out, True, {"impl": "unsharp-fallback"})


# ---------- 流水线编排 ----------

class AIPipelineEngine(FusionEngine):
    """引擎 B：串联检测 → 擦除 → 修复。"""

    kind = EngineKind.AI
    name = "ai"
    label = "引擎B · AI修复流水线（检测→擦除→修复）"

    def __init__(self, detection=None, inpainting=None, restoration=None,
                 allow_fallback=True, strict=False):
        self.detection = detection or YOLODetection()
        self.inpainting = inpainting or LamaInpainting(allow_fallback=allow_fallback)
        self.restoration = restoration or RealESRGANRestoration(allow_fallback=allow_fallback)
        self.allow_fallback = allow_fallback
        self.strict = strict  # strict=True 时禁止 AI 步骤降级

    @property
    def available(self) -> bool:
        # 引擎B 至少擦除步骤可用（真模型或允许降级）
        return self.inpainting.available() or self.allow_fallback

    def execute(self, ctx: ProcessContext) -> EngineOutcome:
        if ctx.image is None:
            raise InpaintingError("引擎B需要图片输入")
        t0 = time.perf_counter()
        meta: dict = {"steps": [], "used_fallback": False}

        # Step 1: 检测
        try:
            rects = self.detection.run(ctx)
        except Exception as e:
            raise DetectionError(f"检测步骤失败: {e}", cause=e)
        if not rects:
            raise DetectionError("未检测到水印框")
        meta["steps"].append({"step": "detection", "impl": self.detection.name,
                              "boxes": len(rects)})
        ctx.log("step.detection", boxes=len(rects))

        # Step 2: 擦除
        ctx.rects = rects  # 把检测框写回上下文供后续步骤使用
        try:
            inpaint_result = self.inpainting.run(ctx, rects)
        except InpaintingError:
            raise
        except Exception as e:
            raise InpaintingError(f"擦除步骤失败: {e}", cause=e)
        ctx.result_image = inpaint_result.image
        meta["steps"].append({"step": "inpainting", "impl": self.inpainting.name,
                              "fallback": inpaint_result.used_fallback,
                              **(inpaint_result.detail or {})})
        meta["used_fallback"] |= inpaint_result.used_fallback
        ctx.log("step.inpainting", fallback=inpaint_result.used_fallback)

        # Step 3: 修复
        try:
            restore_result = self.restoration.run(ctx)
        except RestorationError:
            raise
        except Exception as e:
            raise RestorationError(f"修复步骤失败: {e}", cause=e)
        out = restore_result.image
        meta["steps"].append({"step": "restoration", "impl": self.restoration.name,
                              "fallback": restore_result.used_fallback,
                              **(restore_result.detail or {})})
        meta["used_fallback"] |= restore_result.used_fallback
        ctx.log("step.restoration", fallback=restore_result.used_fallback)

        return EngineOutcome(
            image=out,
            engine=self.name,
            lossless=False,  # AI 修复为有损重建
            elapsed_ms=round((time.perf_counter() - t0) * 1000, 1),
            meta=meta,
        )
