"""框架切换 + 严格框内约束回归测试（unittest，直接 python 运行）。

覆盖：
1. 提示词解析与小程序 utils/prompt.js 行为一致（含示例提示词跨端比对）
2. framework 取值与回退（prompt 自动选框架、空提示词回退 smart、非法值回退）
3. compose_strict：框外逐像素不变、框内取修复结果、贴边/多框/尺寸不一致边界

运行：
    cd 05_后端引擎
    set PYTHONPATH=%CD%
    python tests\test_framework_strict.py
"""

import re
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import api_v2
from api_v2 import parse_prompt, resolve_framework, compose_strict, parse_polygons, sketch_polygon

ROOT = Path(__file__).resolve().parents[1]
MINI_PROMPT_JS = ROOT.parent / "04_小程序版" / "utils" / "prompt.js"


class TestPromptParsing(unittest.TestCase):
    def test_example_prompt(self):
        text = "我要去掉的是框住的蓝色包（包蓝蓝.png 中人物的包），其余区域依据背景或人物衣物进行修改。"
        info = parse_prompt(text)
        self.assertEqual(info["target"], "蓝色包")
        self.assertEqual(info["framework"], "texture")
        self.assertIn("衣物", info["intent"])

    def test_gradient_and_average(self):
        self.assertEqual(parse_prompt("去掉框住的水印，背景是渐变色")["framework"], "smart")
        # 注意规则顺序：含「纯色」会先命中智能扩散；纯「快速/平均」才走快速填充
        self.assertEqual(parse_prompt("快速填充，取平均色")["framework"], "average")

    def test_empty(self):
        info = parse_prompt("")
        self.assertEqual(info["intent"], "")
        self.assertEqual(info["framework"], "")

    def test_cross_end_consistency_with_miniprogram(self):
        """从小程序 JS 里抽出示例提示词，Python 解析结果必须一致（防规则漂移）。"""
        if not MINI_PROMPT_JS.exists():
            self.skipTest("小程序 prompt.js 不存在")
        src = MINI_PROMPT_JS.read_text(encoding="utf-8")
        m = re.search(r"var EXAMPLE\s*=\s*'([^']+)'", src)
        self.assertIsNotNone(m, "未能从 JS 抽出示例提示词")
        info = parse_prompt(m.group(1))
        self.assertEqual(info["target"], "蓝色包")
        self.assertEqual(info["framework"], "texture")


class TestFrameworkResolution(unittest.TestCase):
    EXAMPLE = "我要去掉的是框住的蓝色包，其余区域依据背景或人物衣物进行修改。"

    def test_prompt_framework_uses_parsed(self):
        actual, info = resolve_framework("prompt", self.EXAMPLE)
        self.assertEqual(actual, "texture")
        self.assertEqual(info["target"], "蓝色包")

    def test_prompt_framework_without_prompt_falls_back(self):
        actual, _ = resolve_framework("prompt", "")
        self.assertEqual(actual, "smart")

    def test_explicit_framework_kept(self):
        actual, _ = resolve_framework("texture", self.EXAMPLE)
        self.assertEqual(actual, "texture")

    def test_invalid_framework_falls_back(self):
        actual, _ = resolve_framework("not-a-framework", "")
        self.assertEqual(actual, "smart")


def make_images(W=64, H=48):
    """原图为横向渐变；修复图整图涂红，便于验证只写回框内。"""
    orig_arr = np.zeros((H, W, 3), dtype=np.uint8)
    for x in range(W):
        orig_arr[:, x, :] = (x * 4 % 256, 120, 180)
    orig = Image.fromarray(orig_arr, "RGB")
    rep = Image.new("RGB", (W, H), (255, 0, 0))
    return orig, rep


def outside_pixels(img, rects):
    a = np.asarray(img).copy()
    mask = np.zeros(a.shape[:2], dtype=bool)
    for r in rects:
        x1, y1 = max(0, int(r["x"])), max(0, int(r["y"]))
        x2, y2 = min(a.shape[1], int(r["x"] + r["w"])), min(a.shape[0], int(r["y"] + r["h"]))
        mask[y1:y2, x1:x2] = True
    return a[~mask]


class TestStrictComposition(unittest.TestCase):
    def test_outside_unchanged(self):
        orig, rep = make_images()
        rects = [{"x": 12, "y": 8, "w": 22, "h": 16}]
        out = compose_strict(orig, rep, rects)
        np.testing.assert_array_equal(outside_pixels(out, rects), outside_pixels(orig, rects))
        # 框内应为修复图的红色
        a = np.asarray(out)
        self.assertTrue(np.all(a[8:24, 12:34] == (255, 0, 0)))

    def test_edge_rect(self):
        orig, rep = make_images()
        rects = [{"x": 0, "y": 0, "w": 16, "h": 12}]
        out = compose_strict(orig, rep, rects)
        np.testing.assert_array_equal(outside_pixels(out, rects), outside_pixels(orig, rects))

    def test_multiple_rects(self):
        orig, rep = make_images()
        rects = [{"x": 2, "y": 2, "w": 8, "h": 8}, {"x": 40, "y": 30, "w": 12, "h": 10}]
        out = compose_strict(orig, rep, rects)
        np.testing.assert_array_equal(outside_pixels(out, rects), outside_pixels(orig, rects))
        a = np.asarray(out)
        self.assertTrue(np.all(a[2:10, 2:10] == (255, 0, 0)))
        self.assertTrue(np.all(a[30:40, 40:52] == (255, 0, 0)))

    def test_no_rects_returns_repaired(self):
        orig, rep = make_images()
        self.assertIs(compose_strict(orig, rep, []), rep)

    def test_size_mismatch_returns_repaired(self):
        orig, _ = make_images()
        rep = Image.new("RGB", (10, 10), (255, 0, 0))
        self.assertIs(compose_strict(orig, rep, [{"x": 1, "y": 1, "w": 2, "h": 2}]), rep)


class TestSketchPolygon(unittest.TestCase):
    """闭合轮廓线稿：输入是点轨迹，输出是黑线白底，轮廓外不变。"""

    def test_parse_polygons_and_auto_close(self):
        polys, err = parse_polygons('[[[10,10],[50,10],[50,50],[10,50]]]')
        self.assertIsNone(err)
        self.assertEqual(len(polys), 1)
        self.assertEqual(polys[0][0], polys[0][-1], "首尾应自动闭合")

    def test_invalid_polygons(self):
        _, err = parse_polygons('not-json')
        self.assertIsNotNone(err)
        _, err = parse_polygons('[[[1,2],[3,4]]]')
        self.assertIsNotNone(err)
        _, err = parse_polygons('[[[1,2],[3,4],[5,6],[x,8]]]')
        self.assertIsNotNone(err)

    def test_sketch_outside_unchanged_and_line_output(self):
        W = H = 100
        arr = np.zeros((H, W, 3), dtype=np.uint8)
        arr[:, :50] = 20    # 左暗
        arr[:, 50:] = 220   # 右亮，x=50 形成竖直强边缘
        img = Image.fromarray(arr, "RGB")
        poly = [[(20, 20), (80, 20), (80, 80), (20, 80), (20, 20)]]
        out = np.asarray(sketch_polygon(img, poly))
        # 轮廓外逐像素不变
        np.testing.assert_array_equal(out[5, 5], arr[5, 5])
        # 轮廓内非边缘为白底
        self.assertTrue(np.all(out[40, 40] == 250))
        # 轮廓内边缘为黑线
        self.assertTrue(np.all(out[40, 50] == 28))


if __name__ == "__main__":
    unittest.main(verbosity=2)
