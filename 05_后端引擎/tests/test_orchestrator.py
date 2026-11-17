"""融合编排器回归测试（unittest，直接 python 运行，无需 pytest）。

测试类 ``TestFusionOrchestrator`` 覆盖：
1. 授权未确认 → 致命终止
2. 正常路径 → 引擎B AI修复流水线（含降级）
3. 引擎A 失败 → 自动回退
4. 指定优先引擎
5. Alpha 固定模板 → 无损恢复（±1）
6. 全部引擎失败 → AllEnginesFailedError
7. 真实木纹水印图 → 笔画级/纹理融合修复，纹理得到保留
8. 智能识别 → 纯色 / 渐变 / 纹理 三类内容判定

测试素材位于 06_素材与示例/测试输入/，通过路径引用，不在代码中硬编码水印文字。
"""

import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from pipeline.context import ProcessContext
from pipeline.orchestrator import OrchestratorConfig
from pipeline.states import EngineKind
from pipeline.exceptions import ParseFailedError, InpaintingError
from engines.fusion import FusionEngine
from engines.opencv_engine import OpenCVEngine
from engines.reverse_alpha import make_solid_text_template, default_registry
from engine_registry import build_orchestrator

# 测试素材根目录（相对本文件定位，便于整体迁移）
ASSETS = Path(__file__).resolve().parents[2] / "06_素材与示例" / "测试输入"
WOOD_IMAGE = ASSETS / "test_wood_texture_watermark.jpg"


def make_image():
    img = Image.new("RGB", (300, 200), (130, 180, 220))
    d = ImageDraw.Draw(img)
    d.rectangle([240, 170, 295, 195], fill=(255, 255, 255))
    d.text((250, 177), "WM", fill=(200, 0, 0))
    return img, [{"x": 240, "y": 170, "w": 55, "h": 25}]


class TestFusionOrchestrator(unittest.TestCase):
    """双引擎融合编排器回归测试。"""

    def test_unauthorized(self):
        img, rects = make_image()
        r = build_orchestrator().process(
            ProcessContext(image=img, authorized=False, rects=rects)
        )
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.error["code"], "unauthorized")

    def test_ai_pipeline(self):
        img, rects = make_image()
        r = build_orchestrator().process(
            ProcessContext(image=img, authorized=True, rects=rects)
        )
        ok = r.status == "succeeded" and r.engine_used == "ai" and len(r.meta["steps"]) == 3
        self.assertTrue(ok, f"engine={r.engine_used}, steps={len(r.meta.get('steps', []))}")

    def test_fallback_from_source(self):
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
        r = orch.process(ProcessContext(
            image=img, authorized=True, source_url="https://x/p/1", rects=rects
        ))
        failed = [t for t in r.trace
                  if t["event"] == "engine.failed" and t.get("code") == "parse_failed"]
        self.assertTrue(r.status == "succeeded" and len(failed) == 1, f"final={r.engine_used}")

    def test_prefer_engine(self):
        img, rects = make_image()
        r = build_orchestrator().process(
            ProcessContext(image=img, authorized=True, rects=rects, prefer_engine="opencv")
        )
        self.assertEqual(r.engine_used, "opencv")

    def test_alpha_lossless(self):
        base = Image.new("RGB", (200, 120), (90, 150, 210))
        tpl = make_solid_text_template(
            "test_tpl", "test", (40, 15), (255, 255, 255),
            alpha=0.5, anchor="bottom_right", margin=(10, 10),
        )
        x, y = tpl.placement(200, 120)
        a = tpl.alpha[..., None]
        fg = np.array(tpl.foreground)
        arr = np.asarray(base, dtype=np.float64).copy()
        arr[y:y + 15, x:x + 40] = a * fg + (1 - a) * arr[y:y + 15, x:x + 40]
        wm = Image.fromarray(np.clip(np.rint(arr), 0, 255).astype(np.uint8), "RGB")
        default_registry.register(tpl)
        try:
            r = build_orchestrator().process(
                ProcessContext(image=wm, authorized=True, template_id="test_tpl", prefer_engine="alpha")
            )
            diff = np.abs(np.asarray(r.image, dtype=np.int16) - np.asarray(base, dtype=np.int16))
            self.assertTrue(r.engine_used == "alpha" and r.lossless and diff.max() <= 1,
                            f"maxdiff={diff.max()}")
        finally:
            default_registry.unregister("test_tpl")

    def test_all_failed(self):
        class Fail(FusionEngine):
            @property
            def available(self):
                return True

            def execute(self, ctx):
                raise InpaintingError("mock fail")

        ai = Fail()
        ai.kind, ai.name = EngineKind.AI, "ai"
        cvinst = Fail()
        cvinst.kind, cvinst.name = EngineKind.OPENCV, "opencv"
        orch = build_orchestrator()
        orch.engines[EngineKind.AI] = ai
        orch.engines[EngineKind.OPENCV] = cvinst
        img, rects = make_image()
        r = orch.process(ProcessContext(image=img, authorized=True, rects=rects))
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.error["code"], "all_engines_failed")


class TestContentDetection(unittest.TestCase):
    """智能识别（内容类型判定）测试，供"智能识别"选项使用。"""

    def setUp(self):
        self.eng = OpenCVEngine()

    def test_solid(self):
        img = Image.new("RGB", (300, 200), (130, 180, 220))
        d = self.eng.detect_content(img, {"x": 120, "y": 80, "w": 60, "h": 30})
        self.assertEqual(d["type"], "solid", d)
        self.assertEqual(d["suggest_method"], "telea")

    def test_gradient(self):
        img = Image.new("RGB", (300, 200))
        px = img.load()
        for y in range(200):
            for x in range(300):
                px[x, y] = (int(x / 300 * 255), int(x / 300 * 200), int(y / 200 * 120))
        d = self.eng.detect_content(img, {"x": 120, "y": 80, "w": 60, "h": 30})
        self.assertEqual(d["suggest_method"], "telea", d)

    def test_wood_texture(self):
        if not WOOD_IMAGE.exists():
            self.skipTest(f"测试素材缺失: {WOOD_IMAGE}")
        img = Image.open(WOOD_IMAGE).convert("RGB")
        d = self.eng.detect_content(img, {"x": 1054, "y": 2205, "w": 200, "h": 52})
        self.assertEqual(d["suggest_method"], "texture", d)
        self.assertIn(d["type"], ("texture", "photo"))


class TestTexturePreservation(unittest.TestCase):
    """真实木纹水印图的修复质量测试（纹理自然融合、无平直色块）。"""

    def setUp(self):
        if not WOOD_IMAGE.exists():
            self.skipTest(f"测试素材缺失: {WOOD_IMAGE}")
        self.img = Image.open(WOOD_IMAGE).convert("RGB")
        self.rect = {"x": 1054, "y": 2205, "w": 200, "h": 52}

    def test_text_removed_and_texture_kept(self):
        eng = OpenCVEngine()
        r = eng.inpaint(self.img, [self.rect], strength=2, enhance=True, method="auto")
        self.assertEqual(r.meta["actual_method"], "texture")
        arr = np.asarray(r.image).astype(np.float64)
        fix = arr[2211:2249, 1060:1247]
        local_std = fix.std(axis=(0, 1)).mean()
        self.assertGreater(local_std, 18.0, f"修复区过于平滑，纹理被破坏: {local_std:.1f}")
        self.assertIn(r.meta.get("texture_strategy"), ("stroke", "patch", "stroke+patch", "coons"))

    def test_solid_background_smooth(self):
        """纯色背景仍走 Telea，不留纹理块。"""
        eng = OpenCVEngine()
        solid = Image.new("RGB", (300, 200), (130, 180, 220))
        r = eng.inpaint(solid, [{"x": 120, "y": 80, "w": 60, "h": 30}], method="auto")
        self.assertEqual(r.meta["actual_method"], "telea")
        arr = np.asarray(r.image).astype(np.float64)
        # 修复区应接近原纯色 (130,180,220)，误差 < 3
        self.assertLess(float(np.abs(arr[85:105, 125:175] - [130, 180, 220]).mean()), 3.0)


def _run():
    """兼容旧式 `python tests/test_orchestrator.py` 直接运行。"""
    print("=" * 56)
    print("融合编排器 + 智能识别 + 纹理融合 回归测试")
    print("=" * 56)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (TestFusionOrchestrator, TestContentDetection, TestTexturePreservation):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("=" * 56)
    total = result.testsRun
    ok = total - len(result.failures) - len(result.errors)
    print(f"结果: {ok}/{total} 通过")
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    _run()
