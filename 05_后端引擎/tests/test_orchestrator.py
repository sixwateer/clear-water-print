"""融合编排器回归测试（无需 pytest，直接 python 运行）。

覆盖：
1. 授权未确认 → 致命终止
2. 正常路径 → 引擎B AI修复流水线（含降级）
3. 引擎A 失败 → 自动回退
4. 指定优先引擎
5. Alpha 固定模板 → 无损恢复（±1）
6. 全部引擎失败 → AllEnginesFailedError
"""

import numpy as np
from PIL import Image, ImageDraw

from pipeline.context import ProcessContext
from pipeline.orchestrator import OrchestratorConfig
from pipeline.states import EngineKind
from pipeline.exceptions import ParseFailedError, InpaintingError
from engines.fusion import FusionEngine
from engines.reverse_alpha import make_solid_text_template, default_registry
from engine_registry import build_orchestrator

PASS = "PASS"
FAIL = "FAIL"
results = []


def check(name: str, cond: bool, detail: str = ""):
    results.append((name, cond))
    print(f"[{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def make_image():
    img = Image.new("RGB", (300, 200), (130, 180, 220))
    d = ImageDraw.Draw(img)
    d.rectangle([240, 170, 295, 195], fill=(255, 255, 255))
    d.text((250, 177), "WM", fill=(200, 0, 0))
    return img, [{"x": 240, "y": 170, "w": 55, "h": 25}]


def test_unauthorized():
    img, rects = make_image()
    r = build_orchestrator().process(ProcessContext(image=img, authorized=False, rects=rects))
    check("未授权致命终止", r.status == "failed" and r.error["code"] == "unauthorized")


def test_ai_pipeline():
    img, rects = make_image()
    r = build_orchestrator().process(ProcessContext(image=img, authorized=True, rects=rects))
    ok = r.status == "succeeded" and r.engine_used == "ai" and len(r.meta["steps"]) == 3
    check("引擎B三步流水线", ok, f"engine={r.engine_used}, steps={len(r.meta.get('steps', []))}")


def test_fallback_from_source():
    class FailingSource(FusionEngine):
        kind = EngineKind.SOURCE
        name = "source"
        label = "mock"

        @property
        def available(self):
            return True

        def execute(self, ctx):
            raise ParseFailedError("mock parse fail")

    orch = build_orchestrator()
    orch.engines[EngineKind.SOURCE] = FailingSource()
    img, rects = make_image()
    r = orch.process(ProcessContext(image=img, authorized=True, source_url="https://x/p/1", rects=rects))
    failed = [t for t in r.trace if t["event"] == "engine.failed" and t.get("code") == "parse_failed"]
    check("引擎A失败自动回退", r.status == "succeeded" and len(failed) == 1,
          f"final={r.engine_used}")


def test_prefer_engine():
    img, rects = make_image()
    r = build_orchestrator().process(
        ProcessContext(image=img, authorized=True, rects=rects, prefer_engine="opencv")
    )
    check("指定优先引擎", r.engine_used == "opencv")


def test_alpha_lossless():
    base = Image.new("RGB", (200, 120), (90, 150, 210))
    tpl = make_solid_text_template("test_tpl", "test", (40, 15), (255, 255, 255),
                                   alpha=0.5, anchor="bottom_right", margin=(10, 10))
    x, y = tpl.placement(200, 120)
    a = tpl.alpha[..., None]
    fg = np.array(tpl.foreground)
    arr = np.asarray(base, dtype=np.float64).copy()
    arr[y:y + 15, x:x + 40] = a * fg + (1 - a) * arr[y:y + 15, x:x + 40]
    wm = Image.fromarray(np.clip(np.rint(arr), 0, 255).astype(np.uint8), "RGB")
    default_registry.register(tpl)
    r = build_orchestrator().process(
        ProcessContext(image=wm, authorized=True, template_id="test_tpl", prefer_engine="alpha")
    )
    diff = np.abs(np.asarray(r.image, dtype=np.int16) - np.asarray(base, dtype=np.int16))
    check("Alpha无损恢复", r.engine_used == "alpha" and r.lossless and diff.max() <= 1,
          f"maxdiff={diff.max()}")
    default_registry.unregister("test_tpl")


def test_all_failed():
    class Fail(FusionEngine):
        @property
        def available(self):
            return True

        def execute(self, ctx):
            raise InpaintingError("mock fail")

    ai, cv = Fail(), Fail
    ai.kind, ai.name = EngineKind.AI, "ai"
    cvinst = cv()
    cvinst.kind, cvinst.name = EngineKind.OPENCV, "opencv"
    orch = build_orchestrator()
    orch.engines[EngineKind.AI] = ai
    orch.engines[EngineKind.OPENCV] = cvinst
    img, rects = make_image()
    r = orch.process(ProcessContext(image=img, authorized=True, rects=rects))
    check("全部失败上报", r.status == "failed" and r.error["code"] == "all_engines_failed")


if __name__ == "__main__":
    print("=" * 50)
    print("融合编排器回归测试")
    print("=" * 50)
    test_unauthorized()
    test_ai_pipeline()
    test_fallback_from_source()
    test_prefer_engine()
    test_alpha_lossless()
    test_all_failed()
    print("=" * 50)
    passed = sum(1 for _, c in results if c)
    print(f"结果: {passed}/{len(results)} 通过")
    if passed != len(results):
        raise SystemExit(1)
