"""线条去除内核测试：与权威 HTML（11:06 定稿版）行为对齐。

运行：cd 05_后端引擎 && python -m unittest tests.test_line_inpaint -v

覆盖：
  * 三模式均只改线条内像素，线条外逐字节不变（含锐化）
  * 三模式输出互不相同、多边形过小被拒绝
  * ROI 外扩 28%/min8、坐标取整、贴边不越界
  * 与 HTML lineRemove 逐像素一致（若 _ref.json 参照数据存在；由 08_自测 生成）
"""

import json
import math
import os
import sys
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engines.line_inpaint import polygon_inpaint  # noqa: E402

W = H = 80
SQUARE = [[(25, 25), (55, 25), (55, 55), (25, 55), (25, 25)]]
PENTA = [[(15, 15), (45, 18), (48, 42), (26, 46), (12, 30), (15, 15)]]


def make_image(seed=0):
    arr = np.zeros((H, W, 4), dtype=np.uint8)
    flat = arr.reshape(-1)
    for i in range(len(flat)):
        flat[i] = (i * 37 + seed * 13 + 11) % 256
    return Image.fromarray(arr[:, :, :3].copy(), "RGB"), arr


def in_poly(px, py, pts):
    inside = False
    n = len(pts)
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


class LineInpaintTests(unittest.TestCase):
    def test_outside_unchanged_all_modes(self):
        for mode in ("smart", "average", "texture"):
            img, orig = make_image(3)
            out = np.array(polygon_inpaint(img, SQUARE, mode=mode, iters=320, sharpen=True))
            poly = SQUARE[0]
            outside_ok = True
            inside_changed = 0
            for y in range(H):
                for x in range(W):
                    same = np.array_equal(out[y, x], orig[y, x, :3])
                    if not in_poly(x + 0.5, y + 0.5, poly) and not same:
                        outside_ok = False
                    if in_poly(x + 0.5, y + 0.5, poly) and not same:
                        inside_changed += 1
            self.assertTrue(outside_ok, f"{mode}: 线条外不应有字节变化")
            self.assertGreater(inside_changed, 0, f"{mode}: 线条内应被修复")

    def test_modes_differ(self):
        outs = {}
        for mode in ("smart", "average", "texture"):
            img, _ = make_image(7)
            outs[mode] = np.array(polygon_inpaint(img, SQUARE, mode=mode, iters=320, sharpen=False))
        self.assertFalse(np.array_equal(outs["smart"], outs["average"]))
        self.assertFalse(np.array_equal(outs["smart"], outs["texture"]))

    def test_too_small_rejected(self):
        img, orig = make_image(1)
        out = np.array(polygon_inpaint(img, [[(10, 10), (15, 10), (15, 15), (10, 10)]],
                                       mode="smart", iters=320, sharpen=False))
        self.assertTrue(np.array_equal(out, orig[:, :, :3]), "过小多边形不应改动任何像素")

    def test_roi_expansion(self):
        # 30px 边 → exp=max(8, round(30*0.28)=8)=8；ROI 应钳在图像内
        img, _ = make_image(2)
        out = np.array(polygon_inpaint(img, SQUARE, mode="average", iters=320, sharpen=False))
        # 只验证线条外（ROI 扩到的 17..63 区域但 mask 外）不变
        orig = np.array(img)
        for x in range(0, 24):
            self.assertTrue(np.array_equal(out[27, x], orig[27, x]))

    def test_edge_polygon_no_oob(self):
        img, _ = make_image(4)
        poly = [[(0, 0), (40, 0), (40, 40), (0, 40), (0, 0)]]
        out = polygon_inpaint(img, poly, mode="smart", iters=320, sharpen=True)
        self.assertEqual(out.size, (W, H))

    def test_html_parity_if_reference_present(self):
        """若存在 08_自测 生成的 HTML 参照数据，逐字节比对。"""
        ref_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "..", "08_自测", "html", "_tmp", "line_ref.json")
        ref_path = os.path.abspath(ref_path)
        if not os.path.exists(ref_path):
            self.skipTest("HTML 参照数据不存在，跳过（由 08_自测 生成）")
        with open(ref_path, encoding="utf-8") as f:
            data = json.load(f)
        W2, H2 = data["W"], data["H"]
        shapes = [SQUARE, PENTA, [[(20, 30), (60, 28), (62, 38), (20, 40), (20, 30)]]]
        modes = ["smart", "average", "texture"]
        n = 0
        for si, shape in enumerate(shapes):
            for mode in modes:
                ref = np.array(data["RESULT"][mode + "#" + str(si)], dtype=np.uint8)
                arr = np.zeros((H2, W2, 4), dtype=np.uint8)
                flat = arr.reshape(-1)
                for i in range(len(flat)):
                    flat[i] = (i * 37 + n * 13 + 11) % 256
                img = Image.fromarray(arr[:, :, :3].copy(), "RGB")
                out = np.array(polygon_inpaint(img, shape, mode=mode, iters=320, sharpen=False))
                diff = sum(1 for y in range(H2) for x in range(W2) for c in range(3)
                           if out[y, x, c] != ref[(y * W2 + x) * 4 + c])
                self.assertEqual(diff, 0, f"{mode} shape#{si} 差异 {diff} 字节")
                n += 1


if __name__ == "__main__":
    unittest.main()
