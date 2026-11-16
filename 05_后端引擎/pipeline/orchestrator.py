"""Orchestrator：双引擎融合的核心决策与调度器。

职责
====
1. 引擎选择：按策略与输入条件决定引擎尝试顺序（引擎A → Alpha → 引擎B → 兜底）。
2. 失败回退：当前引擎抛 RecoverableError 时，按回退链自动尝试下一引擎。
3. 状态轨迹：完整记录每次尝试、失败原因、耗时，便于审计与调试。
4. 异常处理：FatalError 立即终止；全部失败抛 AllEnginesFailedError。
5. 质量校验：对产出做基本校验，不通过则视为该引擎失败并回退。

引擎选择逻辑（select_order）
==========================
- ``prefer_engine`` 指定时，将其置于首位（仍保留后续回退）。
- 默认优先级：
    1. 引擎 A（source）：仅当有 source_url 且服务可用 → 无损。
    2. Alpha：仅当有图片且注册了模板 → 无损。
    3. 引擎 B（ai）：有图片时 → 有损但质量高。
    4. OpenCV：有图片时 → 兜底。

失败回退条件（由引擎抛出的 RecoverableError 子类决定）
=====================================================
- EngineUnavailableError : 依赖缺失 / 服务不可达
- ParseFailedError       : 引擎A 解析失败
- TemplateMismatchError  : Alpha 模板不匹配
- DetectionError         : 检测失败 / 未检出水印
- InpaintingError        : 擦除失败
- RestorationError       : 修复失败
- QualityCheckError      : 输出质量校验不通过
- TimeoutError_          : 执行超时

FatalError（UnauthorizedError / InvalidInputError）不回退，立即终止。
"""

from dataclasses import dataclass, field

from PIL import Image

from engines.fusion import FusionEngine
from .context import ProcessContext, ProcessResult
from .exceptions import (
    RecoverableError, FatalError, InvalidInputError, UnauthorizedError,
    AllEnginesFailedError, QualityCheckError,
)
from .states import EngineKind, FALLBACK_ORDER


@dataclass
class OrchestratorConfig:
    """编排器配置。"""

    allow_fallback: bool = True        # 是否启用引擎B内部的AI降级
    strict_quality: bool = False       # 严格质量校验（图像尺寸/全黑检测）
    min_match_score: float = 0.35      # Alpha 模板匹配置信度阈值
    max_attempts: int = 4              # 最多尝试引擎数


class Orchestrator:
    """融合编排器。

    Args:
        engines: {EngineKind: FusionEngine} 引擎注册表
        config: 编排配置
    """

    def __init__(self, engines: dict[EngineKind, FusionEngine], config: OrchestratorConfig | None = None):
        self.engines = engines
        self.config = config or OrchestratorConfig()

    # ---------- 决策 ----------

    def select_order(self, ctx: ProcessContext) -> list[EngineKind]:
        """根据输入与引擎可用性，生成本次处理的引擎尝试顺序。"""
        order: list[EngineKind] = []

        # 引擎 A：有分享链接且可用
        if ctx.source_url and self._usable(EngineKind.SOURCE):
            order.append(EngineKind.SOURCE)

        # Alpha：有图片、注册了模板且可用
        if ctx.image is not None and self._usable(EngineKind.ALPHA):
            order.append(EngineKind.ALPHA)

        # 引擎 B & 兜底：有图片
        if ctx.image is not None:
            if self._usable(EngineKind.AI):
                order.append(EngineKind.AI)
            if self._usable(EngineKind.OPENCV):
                order.append(EngineKind.OPENCV)

        # 若调用方指定了偏好引擎且在当前顺序中，提到首位
        if ctx.prefer_engine and ctx.prefer_engine != "auto":
            try:
                preferred = EngineKind(ctx.prefer_engine)
                if preferred in order:
                    order.remove(preferred)
                    order.insert(0, preferred)
            except ValueError:
                pass

        # 去重并裁剪
        seen = set()
        result = []
        for k in order:
            if k not in seen:
                seen.add(k)
                result.append(k)
        return result[: self.config.max_attempts]

    def _usable(self, kind: EngineKind) -> bool:
        eng = self.engines.get(kind)
        return bool(eng and eng.available)

    # ---------- 主流程 ----------

    def process(self, ctx: ProcessContext) -> ProcessResult:
        """执行融合处理，返回统一结果。"""
        try:
            self._validate(ctx)

            ctx.status = "selecting"
            ctx.log("select.start")
            order = self.select_order(ctx)
            ctx.log("select.order", order=[k.value for k in order])

            if not order:
                raise InvalidInputError(
                    "没有可用引擎：请提供 source_url（引擎A）或图片（Alpha/引擎B/兜底），"
                    "并确认对应引擎依赖已就绪"
                )

            last_error: RecoverableError | None = None
            for kind in order:
                engine = self.engines[kind]
                ctx.current_engine = kind
                ctx.status = self._status_for(kind)
                ctx.log("engine.attempt", engine=kind,
                        label=engine.label)

                try:
                    outcome = engine.execute(ctx)
                    self._quality_check(outcome.image, ctx)

                    # 成功
                    ctx.result_image = outcome.image
                    ctx.status = "succeeded"
                    ctx.log("engine.success", engine=kind,
                            lossless=outcome.lossless,
                            elapsed_ms=outcome.elapsed_ms,
                            meta=outcome.meta)
                    return ProcessResult(
                        task_id=ctx.task_id,
                        status="succeeded",
                        engine_used=outcome.engine,
                        lossless=outcome.lossless,
                        elapsed_ms=ctx.elapsed_ms,
                        trace=ctx.trace,
                        image=outcome.image,
                        meta=outcome.meta,
                    )

                except RecoverableError as e:
                    last_error = e
                    ctx.log("engine.failed", engine=kind, level="warn",
                            code=e.code, reason=e.message)
                    ctx.status = "failed_retry"
                    if not self._should_retry(kind, order):
                        break
                    continue

                except Exception as e:  # 未预期的引擎异常，视作可回退
                    last_error = RecoverableError(
                        f"引擎 {kind.value} 未预期异常: {e}", cause=e
                    )
                    ctx.log("engine.error", engine=kind, level="error",
                            reason=str(e))
                    ctx.status = "failed_retry"
                    if not self._should_retry(kind, order):
                        break
                    continue

            # 全部失败
            ctx.status = "failed"
            err = AllEnginesFailedError(
                f"所有引擎均失败：{last_error.message if last_error else '未知原因'}",
                trace=ctx.trace,
                attempted=[k.value for k in order],
            )
            ctx.error = err.to_dict()
            ctx.log("pipeline.failed", level="error", reason=err.message)
            return ProcessResult(
                task_id=ctx.task_id,
                status="failed",
                engine_used=None,
                lossless=False,
                elapsed_ms=ctx.elapsed_ms,
                trace=ctx.trace,
                error=err.to_dict(),
            )

        except FatalError as e:
            ctx.status = "failed"
            ctx.error = e.to_dict()
            ctx.log("pipeline.aborted", level="error", code=e.code, reason=e.message)
            return ProcessResult(
                task_id=ctx.task_id,
                status="failed",
                engine_used=None,
                lossless=False,
                elapsed_ms=ctx.elapsed_ms,
                trace=ctx.trace,
                error=e.to_dict(),
            )

    # ---------- 辅助 ----------

    def _validate(self, ctx: ProcessContext) -> None:
        if not ctx.authorized:
            raise UnauthorizedError("未确认授权：请确认对此内容拥有处理权或已获授权")
        if ctx.image is None and not ctx.source_url:
            raise InvalidInputError("输入为空：需提供图片或分享链接")

    def _status_for(self, kind: EngineKind) -> str:
        return {
            EngineKind.SOURCE: "engine_a",
            EngineKind.ALPHA: "engine_alpha",
            EngineKind.AI: "engine_b",
            EngineKind.OPENCV: "engine_b",  # 兜底归入引擎B阶段展示
        }.get(kind, "engine_b")

    def _should_retry(self, kind: EngineKind, order: list[EngineKind]) -> bool:
        try:
            idx = order.index(kind)
            return idx < len(order) - 1
        except ValueError:
            return False

    def _quality_check(self, image: Image.Image | None, ctx: ProcessContext) -> None:
        if not self.config.strict_quality or image is None:
            return
        if image.width < 16 or image.height < 16:
            raise QualityCheckError(f"输出尺寸异常: {image.size}")
        # 全黑 / 全白检测
        import numpy as np
        arr = np.asarray(image.convert("L"))
        if arr.max() - arr.min() < 3:
            raise QualityCheckError("输出近乎纯色，疑似处理失败")
