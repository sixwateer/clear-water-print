"""融合引擎统一契约。

所有参与融合编排的引擎（引擎 A / Alpha / 引擎 B / 兜底）都实现 ``FusionEngine``，
返回统一的 ``EngineOutcome``，便于 Orchestrator 无差别调度与回退。
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from pipeline.context import ProcessContext
from pipeline.exceptions import RecoverableError


@dataclass
class EngineOutcome:
    """单个引擎的执行产出。"""

    image: Image.Image
    engine: str
    lossless: bool = False
    elapsed_ms: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


class FusionEngine(ABC):
    """融合引擎基类。

    子类实现：
    - ``kind``: 引擎类型（EngineKind）
    - ``available``: 依赖是否满足
    - ``execute``: 执行处理，失败时抛出 ``RecoverableError`` 子类以触发回退
    """

    kind = None
    name: str = "fusion"
    label: str = "融合引擎"

    @property
    @abstractmethod
    def available(self) -> bool:
        """当前引擎是否可用。"""
        raise NotImplementedError

    @abstractmethod
    def execute(self, ctx: ProcessContext) -> EngineOutcome:
        """执行处理。失败应抛 RecoverableError 子类。"""
        raise NotImplementedError

    def _timed(self, outcome_factory) -> EngineOutcome:
        """计时包装（供子类使用）。"""
        t0 = time.perf_counter()
        outcome = outcome_factory()
        outcome.elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        return outcome
