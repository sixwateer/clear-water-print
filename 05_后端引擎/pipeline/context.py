"""处理上下文与统一结果模型。

ProcessContext 贯穿整个融合流程，记录输入、决策、状态轨迹；
ProcessResult 是对外返回的统一结构，便于集成方消费。
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from .exceptions import PipelineError
from .states import EngineKind, ProcessStatus


@dataclass
class ProcessContext:
    """一次处理请求的完整上下文。"""

    # --- 输入 ---
    image: Image.Image | None = None            # 图片输入（路线 B / Alpha）
    source_url: str | None = None               # 分享链接（引擎 A 输入）
    watermark_type: str = "auto"                # auto | template | generic
    template_id: str | None = None              # 指定水印模板（Alpha 引擎）
    rects: list[dict] = field(default_factory=list)  # 水印框（原图坐标）
    strength: int = 2
    enhance: bool = True
    face: bool = False
    authorized: bool = False                    # 合规：授权确认
    prefer_engine: str = "auto"                 # 调用方可指定优先引擎

    # --- 运行时状态 ---
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: ProcessStatus = ProcessStatus.PENDING
    current_engine: EngineKind | None = None
    trace: list[dict] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    result_image: Image.Image | None = None
    error: dict | None = None

    def log(
        self,
        event: str,
        *,
        engine: EngineKind | None = None,
        level: str = "info",
        **details,
    ) -> None:
        """追加一条状态轨迹。"""
        self.trace.append({
            "ts": round(time.time(), 3),
            "event": event,
            "engine": engine.value if engine else (
                self.current_engine.value if self.current_engine else None
            ),
            "level": level,
            "status": self.status.value if isinstance(self.status, ProcessStatus) else self.status,
            **details,
        })

    @property
    def elapsed_ms(self) -> float:
        return round((time.time() - self.started_at) * 1000, 1)


@dataclass
class ProcessResult:
    """对外统一结果（不含图像二进制，图像由 API 层编码）。"""

    task_id: str
    status: str
    engine_used: str | None
    lossless: bool
    elapsed_ms: float
    trace: list[dict]
    image: Image.Image | None = None
    error: dict | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, include_image: bool = False) -> dict:
        d = {
            "task_id": self.task_id,
            "status": self.status,
            "engine_used": self.engine_used,
            "lossless": self.lossless,
            "elapsed_ms": self.elapsed_ms,
            "trace": self.trace,
            "error": self.error,
            "meta": self.meta,
        }
        return d
