"""反向 Alpha 混合引擎（固定模板水印无损恢复）。

作为融合流程中的"无损捷径"：若图片含已注册的固定模板水印，直接代数反解，
像素级恢复原始背景，优于 AI 修复。匹配失败时抛 TemplateMismatchError → 回退。
"""

import time

from PIL import Image

from pipeline.context import ProcessContext
from pipeline.exceptions import TemplateMismatchError
from .fusion import FusionEngine, EngineOutcome
from pipeline.states import EngineKind
from .reverse_alpha import TemplateRegistry, reverse_alpha_blend, default_registry


class AlphaEngine(FusionEngine):
    """反向 Alpha 混合引擎。"""

    kind = EngineKind.ALPHA
    name = "alpha"
    label = "反向Alpha混合 · 固定模板无损恢复"

    def __init__(self, registry: TemplateRegistry | None = None, threshold: float = 0.35):
        self.registry = registry or default_registry
        self.threshold = threshold

    @property
    def available(self) -> bool:
        # 有已注册模板即可用
        return len(self.registry.list()) > 0

    def execute(self, ctx: ProcessContext) -> EngineOutcome:
        if ctx.image is None:
            raise TemplateMismatchError("Alpha 引擎需要图片输入")
        if not self.available:
            raise TemplateMismatchError("未注册任何水印模板")

        t0 = time.perf_counter()
        match = self.registry.match(
            ctx.image,
            template_id=ctx.template_id,
            threshold=self.threshold,
        )
        if not match:
            raise TemplateMismatchError(
                "未匹配到固定水印模板（模板可能未注册或水印经压缩/缩放失配）",
                template_id=ctx.template_id,
            )

        template, score = match
        placement = template.placement(*ctx.image.size)
        result = reverse_alpha_blend(ctx.image, template, placement)

        return EngineOutcome(
            image=result,
            engine=self.name,
            lossless=True,  # 代数逆运算，像素级恢复
            elapsed_ms=round((time.perf_counter() - t0) * 1000, 1),
            meta={
                "template_id": template.id,
                "template_label": template.label,
                "match_score": round(score, 3),
                "placement": list(placement),
                "note": "反向Alpha混合代数逆运算（±1 量化误差）",
            },
        )
