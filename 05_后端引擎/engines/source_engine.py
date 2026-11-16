"""引擎 A：源头解析（无损原图）。

对自有内容，若提供平台分享链接，调用解析服务（如 parse-video-py 的 FastAPI/MCP
接口）直接取回平台存储的无水印原始资源——画质零损失，是最理想路径。

设计：
- 解析服务地址可配置（环境变量 PARSE_SERVICE_URL 或构造参数），默认 http://127.0.0.1:8001
- 未配置/不可达 → available=False → Orchestrator 回退
- 解析失败（链接无效、平台不支持、超时）→ 抛 ParseFailedError → 回退
- 支持返回图片的 URL 或直接 base64/二进制
"""

import os
import time

import requests
from PIL import Image
from io import BytesIO

from pipeline.context import ProcessContext
from pipeline.exceptions import ParseFailedError
from .fusion import FusionEngine, EngineOutcome
from pipeline.states import EngineKind


class SourceEngine(FusionEngine):
    """源头解析引擎（引擎 A）。"""

    kind = EngineKind.SOURCE
    name = "source"
    label = "引擎A · 源头解析（无损原图）"

    def __init__(self, service_url: str | None = None, timeout: float = 8.0):
        self.service_url = service_url or os.getenv("PARSE_SERVICE_URL", "http://127.0.0.1:8001")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        # 只有配置了分享链接且解析服务可达时才可用
        url = os.getenv("PARSE_SERVICE_URL", self.service_url)
        if not url:
            return False
        try:
            requests.get(f"{url.rstrip('/')}/health", timeout=1.5)
            return True
        except Exception:
            return False

    def execute(self, ctx: ProcessContext) -> EngineOutcome:
        if not ctx.source_url:
            raise ParseFailedError("引擎A需要分享链接（source_url），当前输入为空")
        if not self.available:
            raise ParseFailedError(
                "源头解析服务不可用（未启动或地址错误）",
                hint="设置环境变量 PARSE_SERVICE_URL 指向 parse-video-py 服务",
            )

        t0 = time.perf_counter()
        try:
            resp = requests.post(
                f"{self.service_url.rstrip('/')}/parse",
                json={"url": ctx.source_url},
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                raise ParseFailedError(f"解析服务返回 {resp.status_code}", cause=None)
            data = resp.json()
            image_url = data.get("image_url") or data.get("no_watermark_url")
            if not image_url:
                raise ParseFailedError("解析结果中无图片地址")
            img_resp = requests.get(image_url, timeout=self.timeout)
            image = Image.open(BytesIO(img_resp.content)).convert("RGB")
        except ParseFailedError:
            raise
        except Exception as e:
            raise ParseFailedError(f"源头解析失败: {e}", cause=e)

        return EngineOutcome(
            image=image,
            engine=self.name,
            lossless=True,  # 源头取原图，画质零损失
            elapsed_ms=round((time.perf_counter() - t0) * 1000, 1),
            meta={"source_url": ctx.source_url, "image_url": image_url,
                  "note": "直接取回平台无水印原图"},
        )
