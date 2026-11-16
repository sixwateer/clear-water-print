"""处理状态定义：融合流程的完整状态机。

状态流转（正常路径）::

    PENDING → SELECTING → (ENGINE_A | ENGINE_ALPHA | ENGINE_B) → SUCCEEDED

失败回退路径::

    PENDING → SELECTING → ENGINE_A → FAILED_RETRY → ENGINE_ALPHA → SUCCEEDED

引擎 B 内部子阶段通过 ``step`` 字段细化，不单独占用顶层状态。
"""

from enum import Enum


class ProcessStatus(str, Enum):
    """顶层处理状态。"""

    PENDING = "pending"                # 已创建，等待处理
    SELECTING = "selecting"            # 引擎选择决策中
    ENGINE_A = "engine_a"              # 引擎 A：源头解析中
    ENGINE_ALPHA = "engine_alpha"      # 反向 Alpha 混合中
    ENGINE_B = "engine_b"              # 引擎 B：AI 修复流水线中
    FAILED_RETRY = "failed_retry"      # 当前引擎失败，准备回退
    SUCCEEDED = "succeeded"            # 处理成功
    FAILED = "failed"                  # 全部引擎失败，终止


class EngineKind(str, Enum):
    """引擎类型标识。"""

    SOURCE = "source"       # 引擎 A：源头解析
    ALPHA = "alpha"         # 反向 Alpha 混合
    AI = "ai"               # 引擎 B：AI 修复流水线
    OPENCV = "opencv"       # 兜底：OpenCV 快速修复


# 回退优先级：A → Alpha → B → OpenCV
FALLBACK_ORDER = [
    EngineKind.SOURCE,
    EngineKind.ALPHA,
    EngineKind.AI,
    EngineKind.OPENCV,
]
