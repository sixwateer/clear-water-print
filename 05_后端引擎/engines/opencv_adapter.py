"""OpenCV 兜底引擎适配器：将现有 OpenCVEngine 包装为 FusionEngine。

作为融合流程的最后一道防线——永远可用、零依赖、秒级响应。
当前 AI 模型未安装时，其修复逻辑与引擎B的降级路径一致。
"""

from pipeline.context import ProcessContext
from pipeline.states import EngineKind
from .fusion import FusionEngine, EngineOutcome
from .opencv_engine import OpenCVEngine


class OpenCVFusionEngine(FusionEngine):
    """OpenCV 兜底引擎。"""

    kind = EngineKind.OPENCV
    name = "opencv"
    label = "兜底 · OpenCV 快速修复（零依赖）"

    def __init__(self):
        self._engine = OpenCVEngine()

    @property
    def available(self) -> bool:
        return True

    def execute(self, ctx: ProcessContext) -> EngineOutcome:
        result = self._engine.inpaint(
            image=ctx.image,
            rects=ctx.rects or [{"x": 0, "y": 0, "w": ctx.image.width, "h": ctx.image.height}],
            strength=ctx.strength,
            enhance=ctx.enhance,
            face=ctx.face,
        )
        return EngineOutcome(
            image=result.image,
            engine=self.name,
            lossless=False,
            elapsed_ms=result.elapsed_ms,
            meta={"impl": "opencv-telea", "detail": result.meta},
        )
