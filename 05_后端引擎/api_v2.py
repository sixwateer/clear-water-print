"""API v2：双引擎融合处理接口。

提供：
- POST /api/v2/process       融合处理（同步返回图片 + JSON 元数据）
- POST /api/v2/process/json  融合处理（仅返回 JSON 元数据，便于测试决策）
- POST /api/v2/detect        智能识别：分析框选区域内容类型并推荐修复方式
- GET  /api/v2/engines       查看引擎状态与回退顺序
- GET  /api/v2/templates     查看已注册的水印模板
- POST /api/v2/templates     注册固定水印模板（供 Alpha 无损引擎使用）
"""

import io
import json
import math
import time

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from PIL import Image

from pipeline.context import ProcessContext
from pipeline.orchestrator import OrchestratorConfig
from pipeline.states import FALLBACK_ORDER
from engine_registry import build_orchestrator, describe_engines
from engines.reverse_alpha import default_registry, make_solid_text_template
from engines.opencv_engine import OpenCVEngine

# 简易任务状态存储（内存，演示用；生产应换 Redis/DB）
_TASKS: dict[str, dict] = {}
_TASK_LIMIT = 200  # 上限：防止长跑内存无限增长，超出后淘汰最早任务


def _remember_task(task_id: str, info: dict) -> None:
    """写入任务状态并限制总量（简单 FIFO 淘汰）。"""
    _TASKS[task_id] = info
    while len(_TASKS) > _TASK_LIMIT:
        oldest = next(iter(_TASKS))
        _TASKS.pop(oldest, None)


router = APIRouter(prefix="/api/v2", tags=["fusion-v2"])


def _encode_png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _parse_rects(rects: str, *, allow_empty: bool = False) -> tuple[list[dict] | None, str | None]:
    """解析并校验水印框，返回 (框列表, 错误信息)。

    校验点：必须是列表、元素是 dict、x/y/w/h 必须是有限数值且 w/h > 0。
    避免非法结构在引擎内部触发未捕获异常（500），统一在这里转成 400。
    """
    try:
        data = json.loads(rects) if rects and rects.strip() else []
    except (json.JSONDecodeError, TypeError):
        return None, "rects 不是合法 JSON"
    if not isinstance(data, list):
        return None, "rects 必须是数组，例如 [{\"x\":10,\"y\":10,\"w\":50,\"h\":20}]"
    if not data:
        if allow_empty:
            return [], None
        return None, "rects 为空，请提供至少一个水印框"
    cleaned: list[dict] = []
    for i, r in enumerate(data):
        if not isinstance(r, dict):
            return None, f"rects[{i}] 必须是对象"
        box = {}
        for k in ("x", "y", "w", "h"):
            v = r.get(k, 0)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                return None, f"rects[{i}].{k} 必须是有限数值"
            box[k] = v
        if box["w"] <= 0 or box["h"] <= 0:
            return None, f"rects[{i}] 的 w/h 必须大于 0"
        cleaned.append(box)
    return cleaned, None


@router.get("/engines")
def get_engines():
    return {
        "fallback_order": [k.value for k in FALLBACK_ORDER],
        "engines": describe_engines(),
        "selection_logic": (
            "1) 有 source_url 且引擎A可用 → 源头解析(无损); "
            "2) 有图片且模板匹配 → 反向Alpha混合(无损); "
            "3) 有图片 → 引擎B AI修复(检测→擦除→修复); "
            "4) 兜底 OpenCV。失败按此链顺序回退。"
        ),
        # 面向前端"选择引擎"区的通俗名称/说明（替代内部代号）
        "engine_guide": [
            {"value": "auto", "name": "智能融合", "badge": "推荐",
             "desc": "自动判断水印类型，优先走无损通道，失败再逐级回退，最省心。",
             "best_for": "不确定水印类型时"},
            {"value": "source", "name": "源头解析", "badge": "无损",
             "desc": "用分享链接直接取平台原图，完全没有画质损失。需要可解析的分享链接。",
             "best_for": "有自己内容的分享链接"},
            {"value": "alpha", "name": "固定模板无损", "badge": "无损",
             "desc": "对已知样式的固定水印做像素级逆运算，理论上零损伤。需先注册模板。",
             "best_for": "样式固定的平台水印"},
            {"value": "ai", "name": "AI 智能修复", "badge": "高质量",
             "desc": "检测水印后用大模型重建背景，复杂照片/大水印效果最好，需安装模型。",
             "best_for": "复杂纹理、大面积水印"},
            {"value": "opencv", "name": "极速修复", "badge": "秒级",
             "desc": "零依赖、秒级完成，并支持木纹等重复纹理的自然融合。",
             "best_for": "纯色/渐变/重复纹理背景"},
        ],
    }


@router.post("/detect")
async def detect_content(
    file: UploadFile = File(..., description="原始图片"),
    rects: str = Form(..., description="水印框 JSON（原图坐标），取第一个框识别"),
):
    """智能识别：分析框选区域内容类型，返回修复建议（供前端自动推荐引擎/方式）。"""
    try:
        raw = await file.read()
        image = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        return JSONResponse({"error": f"图片解析失败: {e}"}, status_code=400)
    rect_list, err = _parse_rects(rects)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    try:
        result = OpenCVEngine.detect_content(image, rect_list[0])
    except Exception as e:
        return JSONResponse({"error": f"识别失败: {type(e).__name__}: {e}"}, status_code=422)
    return {"ok": True, **result}


@router.get("/templates")
def get_templates():
    return {"templates": default_registry.list()}


@router.post("/templates")
def add_template(
    template_id: str = Form(...),
    label: str = Form(...),
    width: int = Form(...),
    height: int = Form(...),
    foreground: str = Form("255,255,255"),
    alpha: float = Form(0.5),
    anchor: str = Form("bottom_right"),
    margin_x: int = Form(24),
    margin_y: int = Form(24),
):
    """注册纯色矩形固定水印模板（便捷入口）。"""
    try:
        fg = tuple(int(x) for x in foreground.split(","))
        if len(fg) != 3 or any(not 0 <= c <= 255 for c in fg):
            raise ValueError
    except ValueError:
        return JSONResponse({"error": "foreground 需为 0-255 范围的 R,G,B 格式"}, status_code=400)
    if width <= 0 or height <= 0:
        return JSONResponse({"error": "width / height 必须大于 0"}, status_code=400)
    if not 0.0 <= alpha <= 1.0:
        return JSONResponse({"error": "alpha 需在 0~1 之间"}, status_code=400)
    if anchor not in ("bottom_right", "top_right", "bottom_left", "top_left", "center"):
        return JSONResponse({"error": "anchor 不受支持"}, status_code=400)
    if not template_id.strip():
        return JSONResponse({"error": "template_id 不能为空"}, status_code=400)

    tpl = make_solid_text_template(
        template_id, label, (width, height), fg, alpha=alpha,
        anchor=anchor, margin=(margin_x, margin_y),
    )
    default_registry.register(tpl)
    return {"ok": True, "template": default_registry.get(template_id) and {
        "id": tpl.id, "label": tpl.label, "size": [width, height],
    }}


async def _build_context(
    file: UploadFile | None,
    rects: str,
    source_url: str | None,
    watermark_type: str,
    template_id: str | None,
    strength: int,
    enhance: bool,
    face: bool,
    authorized: bool,
    prefer_engine: str,
    strict_quality: bool,
) -> tuple[ProcessContext | None, JSONResponse | None]:
    """从请求参数构建处理上下文。"""
    image = None
    if file is not None:
        try:
            raw = await file.read()
            image = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception as e:
            return None, JSONResponse({"error": f"图片解析失败: {e}"}, status_code=400)

    if image is None and not source_url:
        return None, JSONResponse(
            {"error": "需提供图片文件或 source_url 分享链接"}, status_code=400
        )

    rect_list, rect_err = _parse_rects(rects, allow_empty=True)
    if rect_err:
        return None, JSONResponse({"error": rect_err}, status_code=400)

    ctx = ProcessContext(
        image=image,
        source_url=source_url,
        watermark_type=watermark_type,
        template_id=template_id,
        rects=rect_list,
        strength=strength,
        enhance=enhance,
        face=face,
        authorized=authorized,
        prefer_engine=prefer_engine,
    )
    _remember_task(ctx.task_id, {"status": "created", "created_at": time.time()})
    return ctx, None


@router.post("/process")
async def process_fusion(
    file: UploadFile | None = File(None, description="原始图片"),
    rects: str = Form("", description="水印框 JSON（原图坐标）"),
    source_url: str | None = Form(None, description="平台分享链接（引擎A输入）"),
    watermark_type: str = Form("auto", description="auto | template | generic"),
    template_id: str | None = Form(None, description="固定水印模板ID（Alpha引擎）"),
    strength: int = Form(2),
    enhance: bool = Form(True),
    face: bool = Form(False),
    authorized: bool = Form(False, description="是否确认有权处理"),
    prefer_engine: str = Form("auto", description="auto | source | alpha | ai | opencv"),
    strict_quality: bool = Form(False),
):
    """双引擎融合处理：返回修复图片二进制 + 元数据响应头。"""
    ctx, err = await _build_context(
        file, rects, source_url, watermark_type, template_id,
        strength, enhance, face, authorized, prefer_engine, strict_quality,
    )
    if err:
        return err

    _TASKS[ctx.task_id]["status"] = "processing"
    try:
        orch = build_orchestrator(OrchestratorConfig(strict_quality=strict_quality))
        result = orch.process(ctx)
    except Exception as e:  # 兜底：编排器本身异常也要落库并给可操作响应
        _remember_task(ctx.task_id, {
            "status": "failed", "error": f"{type(e).__name__}: {e}",
        })
        return JSONResponse(
            {"task_id": ctx.task_id, "status": "failed",
             "error": f"处理流程异常: {type(e).__name__}: {e}"}, status_code=500
        )

    _remember_task(ctx.task_id, {
        "status": result.status,
        "engine_used": result.engine_used,
        "lossless": result.lossless,
        "elapsed_ms": result.elapsed_ms,
        "trace": result.trace,
        "error": result.error,
    })

    if result.status != "succeeded" or result.image is None:
        return JSONResponse(
            {"task_id": result.task_id, **result.to_dict()}, status_code=422
        )

    return Response(
        content=_encode_png(result.image),
        media_type="image/png",
        headers={
            "X-Task-Id": result.task_id,
            "X-Engine-Used": result.engine_used or "",
            "X-Lossless": str(result.lossless).lower(),
            "X-Elapsed-Ms": str(result.elapsed_ms),
            "X-Trace": json.dumps(result.trace, ensure_ascii=True),  # 头信息须 latin-1 可编码
            "Access-Control-Expose-Headers": (
                "X-Task-Id,X-Engine-Used,X-Lossless,X-Elapsed-Ms,X-Trace"
            ),
        },
    )


@router.post("/process/json")
async def process_fusion_json(
    file: UploadFile | None = File(None),
    rects: str = Form(""),
    source_url: str | None = Form(None),
    watermark_type: str = Form("auto"),
    template_id: str | None = Form(None),
    strength: int = Form(2),
    enhance: bool = Form(True),
    face: bool = Form(False),
    authorized: bool = Form(False),
    prefer_engine: str = Form("auto"),
    strict_quality: bool = Form(False),
):
    """融合处理：仅返回 JSON 元数据（不返回图片），便于测试决策与回退逻辑。"""
    ctx, err = await _build_context(
        file, rects, source_url, watermark_type, template_id,
        strength, enhance, face, authorized, prefer_engine, strict_quality,
    )
    if err:
        return err
    try:
        orch = build_orchestrator(OrchestratorConfig(strict_quality=strict_quality))
        result = orch.process(ctx)
    except Exception as e:
        _remember_task(ctx.task_id, {
            "status": "failed", "error": f"{type(e).__name__}: {e}",
        })
        return JSONResponse(
            {"task_id": ctx.task_id, "status": "failed",
             "error": f"处理流程异常: {type(e).__name__}: {e}"}, status_code=500
        )
    _remember_task(ctx.task_id, {"status": result.status, "error": result.error})
    return result.to_dict()


@router.get("/task/{task_id}")
def get_task(task_id: str):
    """查询任务状态（内存存储，进程重启后清空）。"""
    return _TASKS.get(task_id, {"error": "task not found"})
