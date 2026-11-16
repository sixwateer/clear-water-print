"""净像 · 去水印后端服务 (FastAPI)

v1（兼容保留）：图片上传 + 框选坐标 -> 修复 -> 返回图片。
v2（新增）：双引擎融合流程
    - 引擎A 源头解析（无损）优先
    - 反向Alpha混合（固定模板无损）
    - 引擎B AI修复流水线（YOLO检测→LaMA/E2FGVI-HQ擦除→Real-ESRGAN修复）
    - OpenCV 兜底，失败自动回退，完整状态轨迹

启动：
    python server.py
文档：
    http://127.0.0.1:8000/docs
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

# 引擎注册表：LaMA 优先，OpenCV 兜底
ENGINES: dict[str, object] = {}
opencv = OpenCVEngine()
lama = LamaEngine()
ENGINES[opencv.name] = opencv
if lama.available:
    ENGINES[lama.name] = lama

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
    import uvicorn

    print("\n" + "=" * 52)
    print("  净像 Watermark Studio API 启动中")
    print("=" * 52)
    print(f"  默认引擎: {DEFAULT_ENGINE}")
    for e in _engine_list():
        flag = "✅" if e["available"] else "⚠️ "
        print(f"  {flag} {e['label']}")
    print("  接口文档: http://127.0.0.1:8000/docs")
    print("=" * 52 + "\n")
    uvicorn.run(app, host="127.0.0.1", port=8000)
