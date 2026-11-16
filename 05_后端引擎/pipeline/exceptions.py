"""异常层次：区分可回退异常与致命异常，驱动回退决策。

设计原则：
- ``RecoverableError`` 及其子类：当前引擎失败，Orchestrator 应尝试下一个引擎。
- ``FatalError`` 及其子类：输入或环境根本性问题，不回退，立即终止并上报。
"""


class PipelineError(Exception):
    """融合流程异常基类。"""

    pass


# ---------- 可回退异常（触发回退）----------

class RecoverableError(PipelineError):
    """当前引擎可恢复失败，应回退到下一引擎。"""

    #: 便于上层识别的简短原因码
    code = "recoverable"

    def __init__(self, message: str, *, cause: Exception | None = None, **details):
        super().__init__(message)
        self.message = message
        self.cause = cause
        self.details = details

    def to_dict(self) -> dict:
        return {
            "type": type(self).__name__,
            "code": self.code,
            "message": self.message,
            "cause": f"{type(self.cause).__name__}: {self.cause}" if self.cause else None,
            "details": self.details,
        }


class EngineUnavailableError(RecoverableError):
    """引擎依赖不满足（如缺 torch / ffmpeg / 平台接口不可用）。"""

    code = "engine_unavailable"


class ParseFailedError(RecoverableError):
    """引擎 A 源头解析失败（无有效链接、平台不支持、接口变更、超时）。"""

    code = "parse_failed"


class TemplateMismatchError(RecoverableError):
    """反向 Alpha 混合：图片中未匹配到已注册的水印模板。"""

    code = "template_mismatch"


class DetectionError(RecoverableError):
    """引擎 B：YOLO 检测失败或未检出水印（置信度过低）。"""

    code = "detection_failed"


class InpaintingError(RecoverableError):
    """擦除阶段失败（LaMA / E2FGVI-HQ）。"""

    code = "inpainting_failed"


class RestorationError(RecoverableError):
    """画质修复阶段失败（Real-ESRGAN）。"""

    code = "restoration_failed"


class QualityCheckError(RecoverableError):
    """输出质量校验不通过（全黑、尺寸异常、像素无变化）。"""

    code = "quality_check_failed"


class TimeoutError_(RecoverableError):
    """引擎执行超时。"""

    code = "timeout"


# ---------- 致命异常（不回退）----------

class FatalError(PipelineError):
    """输入或环境根本性问题，不触发回退。"""

    code = "fatal"

    def __init__(self, message: str, **details):
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict:
        return {"type": type(self).__name__, "code": self.code,
                "message": self.message, "details": self.details}


class UnauthorizedError(FatalError):
    """未确认授权：合规红线，直接拒绝处理。"""

    code = "unauthorized"


class InvalidInputError(FatalError):
    """输入非法（无图片、格式错误、参数越界）。"""

    code = "invalid_input"


class AllEnginesFailedError(FatalError):
    """所有引擎均失败，无法产出结果。附带完整轨迹。"""

    code = "all_engines_failed"

    def __init__(self, message: str, trace: list[dict], **details):
        super().__init__(message, **details)
        self.trace = trace

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["trace"] = self.trace
        return d
