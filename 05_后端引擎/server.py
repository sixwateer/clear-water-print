"""净像 · 去水印后端服务（FastAPI）— 服务入口 / 唯一启动文件

=====================================================================
一、这个文件时做什么的（功能入口）
=====================================================================
- 本文件是后端服务的唯一入口：``python server.py`` 即启动。
- 它做三件事：①装配引擎 ②定义 v1 兼容接口 ③挂载 v2 融合路由。
- 业务算法不在此文件里，改动请去对应模块（见下方"修改点索引"）。

=====================================================================
二、修改点索引（想改什么，去哪里）
=====================================================================
- 换端口 / 监听地址 ............ 文件末尾 ``uvicorn.run(...)``
- 改默认引擎、引擎开关 ......... 本文件 ``ENGINES`` 装配区 / ``DEFAULT_ENGINE``
- 改 v1 修复接口参数 ........... 本文件 ``inpaint()`` 函数签名
- 改 v2 融合接口 / 智能识别 .... ``api_v2.py``（含 /detect、/engines 的通俗说明）
- 改引擎选择 / 回退逻辑 ........ ``pipeline/orchestrator.py``
- 改纹理融合 / 智能识别算法 .... ``engines/opencv_engine.py``
- 注册 / 替换引擎 .............. ``engine_registry.py``
- 依赖清单 ..................... ``requirements.txt``

=====================================================================
三、接口一览
=====================================================================
- v1（兼容保留）：``POST /api/inpaint`` 图片 + 框选坐标 -> 修复图。
- v2（推荐，融合）：由 ``api_v2.py`` 提供：
    ``POST /api/v2/process``      修复并返回 PNG + 元数据响应头
    ``POST /api/v2/process/json`` 仅返回决策元数据（调试用）
    ``POST /api/v2/detect``       智能识别框选区域内容类型并推荐方式
    ``GET  /api/v2/engines``      引擎状态、回退顺序、通俗名称说明
    ``GET/POST /api/v2/templates`` 固定水印模板管理
- 健康检查 ``GET /api/health``；接口文档 ``/docs``。

=====================================================================
四、启动与注意事项
=====================================================================
- Windows 用户可直接双击 ``start.bat``（自动装依赖并启动）。
- 首次启动若未装 LaMA 依赖，会自动降级到 OpenCV 引擎，闭环仍可用。
- 本服务仅供本机（127.0.0.1）使用；如需局域网/公网访问，请自行加鉴权。
- CORS 当前放行所有来源（原型阶段），生产环境务必收紧 allow_origins。
"""

import io
import json
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from PIL import Image

from engines import OpenCVEngine
from engines.lama_engine import LamaEngine
from api_v2 import router as v2_router

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="净像 Watermark Studio API", version="2.0.0")

# 挂载 v2 融合接口（旧 v1 接口保持不变）
app.include_router(v2_router)

# 允许前端本地页面 / 任意来源调用（原型阶段）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# 【修改点】引擎装配区（v1 用）：LaMA 优先，OpenCV 兜底。
# 想增删 v1 可选引擎，在这里注册即可；v2 引擎在 engine_registry.py 装配。
# 注意：只能注册同名唯一的引擎，name 即前端 engine 参数使用的值。
# ---------------------------------------------------------------------------
ENGINES: dict[str, object] = {}
opencv = OpenCVEngine()
lama = LamaEngine()
ENGINES[opencv.name] = opencv
if lama.available:  # 依赖齐全才注册，否则前端下拉里不会出现 LaMA
    ENGINES[lama.name] = lama

# 默认引擎：有 LaMA 就用高质量，否则用零依赖的 OpenCV，保证开箱即用
DEFAULT_ENGINE = "lama" if lama.available else "opencv"


def _engine_list() -> list[dict]:
    items = [
        {"name": opencv.name, "label": opencv.label, "available": True,
         "requires_model": False, "default": DEFAULT_ENGINE == opencv.name},
        {"name": lama.name, "label": lama.label, "available": lama.available,
         "requires_model": True, "default": DEFAULT_ENGINE == lama.name,
         "hint": None if lama.available else "安装 torch + simple-lama-inpainting 后启用"},
    ]
    return items


@app.get("/")
def root():
    return {
        "service": "净像 Watermark Studio API",
        "version": "1.0.0",
        "default_engine": DEFAULT_ENGINE,
        "docs": "/docs",
    }


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "default_engine": DEFAULT_ENGINE,
        "engines": _engine_list(),
        "timestamp": time.time(),
    }


@app.get("/api/engines")
def engines():
    return {"engines": _engine_list(), "default": DEFAULT_ENGINE}


@app.post("/api/inpaint")
async def inpaint(
    file: UploadFile = File(..., description="原始图片"),
    rects: str = Form("", description="水印框 JSON，基于原图像素坐标"),
    engine: str = Form("auto", description="引擎名：auto/lama/opencv"),
    strength: int = Form(2, description="修复强度 1-3"),
    enhance: bool = Form(True, description="画质增强"),
    face: bool = Form(False, description="人脸保真（预留）"),
):
    """核心接口：对图片框选区域执行去水印修复。"""
    try:
        raw = await file.read()
        image = Image.open(io.BytesIO(raw)).convert("RGB")

        try:
            rect_list = json.loads(rects) if rects.strip() else []
        except json.JSONDecodeError:
            return JSONResponse({"error": "rects 不是合法 JSON"}, status_code=400)

        if not rect_list:
            return JSONResponse({"error": "未提供水印框 rects"}, status_code=400)

        # 选择引擎
        if engine == "auto" or engine not in ENGINES:
            chosen = DEFAULT_ENGINE
        else:
            chosen = engine

        eng = ENGINES[chosen]
        result = eng.inpaint(
            image=image,
            rects=rect_list,
            strength=strength,
            enhance=enhance,
            face=face,
        )

        # 编码为 PNG
        buf = io.BytesIO()
        result.image.save(buf, format="PNG")
        data = buf.getvalue()

        return Response(
            content=data,
            media_type="image/png",
            headers={
                "X-Engine": result.engine,
                "X-Elapsed-Ms": str(result.elapsed_ms),
                "X-Image-W": str(result.image.width),
                "X-Image-H": str(result.image.height),
                "Access-Control-Expose-Headers": "X-Engine,X-Elapsed-Ms,X-Image-W,X-Image-H",
            },
        )
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"处理失败: {type(e).__name__}: {e}"}, status_code=500)


if __name__ == "__main__":
    # 【功能入口】启动打印引擎自检信息，便于确认依赖是否就绪。
    import uvicorn

    print("\n" + "=" * 58)
    print("  净像 Watermark Studio API 启动中")
    print("=" * 58)
    print(f"  默认引擎: {DEFAULT_ENGINE}")
    print("  可用引擎（✅就绪 / ⚠️未就绪会自动降级）:")
    for e in _engine_list():
        flag = "✅" if e["available"] else "⚠️ "
        print(f"    {flag} {e['label']}")
    print("  本地首页: http://127.0.0.1:8000/")
    print("  接口文档: http://127.0.0.1:8000/docs")
    print("  健康检查: http://127.0.0.1:8000/api/health")
    print("  停止服务: 在本窗口按 Ctrl+C 或直接关闭窗口")
    print("=" * 58 + "\n")
    # 【修改点】host/port 改这里；如需外部访问改 host 为 0.0.0.0 并务必加鉴权
    uvicorn.run(app, host="127.0.0.1", port=8000)
