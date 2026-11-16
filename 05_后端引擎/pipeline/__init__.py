"""融合编排层：双引擎融合的水印去除流程。

对外主要入口：
    from pipeline import Orchestrator, ProcessContext

详见各模块文档。
"""

from .states import ProcessStatus, EngineKind, FALLBACK_ORDER
from .exceptions import (
    PipelineError, RecoverableError, FatalError,
    EngineUnavailableError, ParseFailedError, TemplateMismatchError,
    DetectionError, InpaintingError, RestorationError, QualityCheckError,
    TimeoutError_, UnauthorizedError, InvalidInputError, AllEnginesFailedError,
)
from .context import ProcessContext, ProcessResult
from .orchestrator import Orchestrator, OrchestratorConfig

__all__ = [
    "Orchestrator", "OrchestratorConfig",
    "ProcessStatus", "EngineKind", "FALLBACK_ORDER",
    "PipelineError", "RecoverableError", "FatalError",
    "EngineUnavailableError", "ParseFailedError", "TemplateMismatchError",
    "DetectionError", "InpaintingError", "RestorationError", "QualityCheckError",
    "TimeoutError_", "UnauthorizedError", "InvalidInputError", "AllEnginesFailedError",
    "ProcessContext", "ProcessResult",
]
