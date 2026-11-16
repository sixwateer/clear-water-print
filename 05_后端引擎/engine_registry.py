"""引擎注册表：集中装配所有融合引擎，供 Orchestrator 与 API 使用。

修改这里即可增删引擎或替换实现，无需改动编排逻辑。
"""

from pipeline.states import EngineKind
from pipeline.orchestrator import Orchestrator, OrchestratorConfig
from engines.source_engine import SourceEngine
from engines.alpha_engine import AlphaEngine
from engines.ai_pipeline import AIPipelineEngine
from engines.opencv_adapter import OpenCVFusionEngine
from engines.reverse_alpha import default_registry


def build_orchestrator(config: OrchestratorConfig | None = None) -> Orchestrator:
    """构建默认编排器（装配全部引擎）。"""
    engines = {
        EngineKind.SOURCE: SourceEngine(),
        EngineKind.ALPHA: AlphaEngine(registry=default_registry),
        EngineKind.AI: AIPipelineEngine(
            allow_fallback=True,
            strict=False,
        ),
        EngineKind.OPENCV: OpenCVFusionEngine(),
    }
    return Orchestrator(engines, config or OrchestratorConfig())


def describe_engines() -> list[dict]:
    """返回各引擎状态（供 /api/health 使用）。"""
    orch = build_orchestrator()
    return [
        {"kind": kind.value, "label": eng.label,
         "available": eng.available, "name": eng.name}
        for kind, eng in orch.engines.items()
    ]
