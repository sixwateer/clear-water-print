"""framework 驱动修复算法回归测试（本次 bug 修复锁定）。

Bug 背景：API 解析出的 framework 原先只写进响应头，未注入 ProcessContext，
导致所有框架都退化到默认 auto→stroke 路径，半透明抗锯齿文字（如"AI生成"）
只检出约 9% 笔画，几乎无法去除。

本测试确认：
1. ProcessContext 承载 framework 字段；
2. OpenCVEngine 按 framework 选算法，三模式输出互不相同；
3. smart 对半透明亮字能显著去除，且框外像素逐字节不变；
4. 兼容：framework=None 时保持旧 auto 行为。
"""

import unittest

import numpy as np
from PIL import Image, ImageDraw

from engines.opencv_engine import OpenCVEngine
from pipeline.context import ProcessContext


def make_semi_transparent_watermark_image(W=320, H=110):
    """金色横向渐变背景 + 半透明白色方块文字，模拟"AI生成"水印。"""
    arr = np.zeros((H, W, 3), dtype=np.uint8)
    for x in range(W):
        t = x / max(1, W - 1)
        arr[:, x] = (int(90 + 110 * t), int(60 + 90 * t), int(30 + 60 * t))
    im = Image.fromarray(arr, "RGB")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    # 半透明白色粗笔画（alpha=170，模拟抗锯齿半透明水印）
    d.rectangle([60, 40, 120, 90], fill=(255, 255, 255, 170))
    d.rectangle([140, 40, 180, 90], fill=(255, 255, 255, 170))
    d.rectangle([200, 40, 300, 90], fill=(255, 255, 255, 170))
    return Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")


class TestFrameworkDrivesAlgorithm(unittest.TestCase):
    RECT = [{"x": 50, "y": 30, "w": 264, "h": 70}]

    def setUp(self):
        self.im = make_semi_transparent_watermark_image()
        self.engine = OpenCVEngine()

    def _bright_count(self, img):
        a = np.asarray(img.convert("RGB")).astype(int)
        spread = a.max(axis=2) - a.min(axis=2)
        return int((((a.mean(axis=2)) > 175) & (spread < 40)).sum())

    def test_context_has_framework(self):
        ctx = ProcessContext(framework="smart")
        self.assertEqual(ctx.framework, "smart")

    def test_three_frameworks_produce_distinct_output(self):
        outs = {}
        for fw in ("smart", "texture", "average"):
            r = self.engine.inpaint(self.im, self.RECT, strength=2,
                                    enhance=False, framework=fw)
            outs[fw] = np.asarray(r.image.convert("RGB")).copy()
            self.assertEqual(r.meta["framework"], fw)
        self.assertFalse(np.array_equal(outs["smart"], outs["texture"]))
        self.assertFalse(np.array_equal(outs["smart"], outs["average"]))
        self.assertFalse(np.array_equal(outs["texture"], outs["average"]))

    def test_smart_removes_semi_transparent_text(self):
        before = self._bright_count(self.im)
        r = self.engine.inpaint(self.im, self.RECT, strength=2,
                                enhance=False, framework="smart")
        after = self._bright_count(r.image)
        # 半透明白块应被大幅去除（至少减少 70%）
        self.assertGreater(before, 1000)
        self.assertLess(after, before * 0.30,
                        f"smart 未有效去除半透明文字: {before} -> {after}")

    def test_outside_box_unchanged_for_all_frameworks(self):
        a0 = np.asarray(self.im.convert("RGB")).astype(int)
        for fw in ("smart", "texture", "average"):
            r = self.engine.inpaint(self.im, self.RECT, strength=2,
                                    enhance=True, framework=fw)
            b = np.asarray(r.image.convert("RGB")).astype(int)
            diff = np.abs(a0 - b).max(axis=2)
            diff[30:100, 50:314] = 0  # 清掉框内
            self.assertEqual(int((diff > 0).sum()), 0,
                             f"{fw} 框架修改了框外像素")

    def test_none_framework_keeps_legacy_auto(self):
        r_auto = self.engine.inpaint(self.im, self.RECT, strength=2,
                                     enhance=False, method="auto")
        r_none = self.engine.inpaint(self.im, self.RECT, strength=2,
                                     enhance=False, framework=None, method="auto")
        np.testing.assert_array_equal(
            np.asarray(r_auto.image), np.asarray(r_none.image)
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
