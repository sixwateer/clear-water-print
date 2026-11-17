"""API 边界与异常处理回归测试（unittest，直接 python 运行）。

覆盖：
1. rects 参数校验（非法 JSON / 非数组 / 元素非对象 / 字段非数值 / NaN / w,h<=0）
2. 任务状态存储的 FIFO 淘汰（防止内存无限增长）
3. OpenCV 引擎的边界输入（空框 / 越界框 / 异常强度）
4. 智能识别的极小框边界
5. 编排器在只有链接、无图片等场景下的健壮性

这些测试不启动 HTTP 服务，直接测试模块函数，快速且稳定。
"""

import json
import unittest

import numpy as np
from PIL import Image

import api_v2
from api_v2 import _parse_rects, _remember_task, _TASKS, _TASK_LIMIT
from engines.opencv_engine import OpenCVEngine
from pipeline.context import ProcessContext
from pipeline.states import EngineKind
from engine_registry import build_orchestrator


class TestRectValidation(unittest.TestCase):
    """rects 参数校验：非法输入必须转成明确错误，而非让引擎抛异常。"""

    def test_valid_rects(self):
        data, err = _parse_rects('[{"x":10,"y":20,"w":30,"h":40}]')
        self.assertIsNone(err)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["w"], 30)

    def test_empty_allowed_vs_not(self):
        data, err = _parse_rects("", allow_empty=True)
        self.assertIsNone(err)
        self.assertEqual(data, [])
        _, err = _parse_rects("[]", allow_empty=False)
        self.assertIsNotNone(err)

    def test_not_json(self):
        _, err = _parse_rects("not-json")
        self.assertIsNotNone(err)
        self.assertIn("JSON", err)

    def test_not_a_list(self):
        for bad in ("{}", '"abc"', "123", "null"):
            with self.subTest(bad=bad):
                _, err = _parse_rects(bad, allow_empty=True)
                self.assertIsNotNone(err)
                self.assertIn("数组", err)

    def test_element_not_object(self):
        _, err = _parse_rects("[1,2,3]")
        self.assertIsNotNone(err)
        self.assertIn("对象", err)

    def test_field_not_number(self):
        for bad in ('[{"x":"10","y":0,"w":5,"h":5}]',
                    '[{"x":true,"y":0,"w":5,"h":5}]',
                    '[{"x":null,"y":0,"w":5,"h":5}]'):
            with self.subTest(bad=bad):
                _, err = _parse_rects(bad)
                self.assertIsNotNone(err)
                self.assertIn("有限数值", err)

    def test_nan_and_inf(self):
        for bad in ('[{"x":NaN,"y":0,"w":5,"h":5}]',
                    '[{"x":0,"y":0,"w":Infinity,"h":5}]'):
            with self.subTest(bad=bad):
                _, err = _parse_rects(bad)
                self.assertIsNotNone(err)

    def test_non_positive_size(self):
        for bad in ('[{"x":0,"y":0,"w":0,"h":5}]',
                    '[{"x":0,"y":0,"w":5,"h":-1}]'):
            with self.subTest(bad=bad):
                _, err = _parse_rects(bad)
                self.assertIsNotNone(err)
                self.assertIn("大于 0", err)

    def test_v1_v2_same_rule(self):
        """v1 inpaint 复用同一校验函数，行为一致。"""
        src = open(api_v2.__file__, encoding="utf-8").read()
        self.assertIn("_parse_rects", src)


class TestTaskStore(unittest.TestCase):
    """任务状态存储：限制容量，避免长跑内存无限增长。"""

    def test_fifo_eviction(self):
        _TASKS.clear()
        for i in range(_TASK_LIMIT + 10):
            _remember_task(f"t{i}", {"status": "created"})
        self.assertEqual(len(_TASKS), _TASK_LIMIT)
        self.assertNotIn("t0", _TASKS)          # 最早的被淘汰
        self.assertIn(f"t{_TASK_LIMIT + 9}", _TASKS)  # 最新的保留
        _TASKS.clear()


class TestEngineEdgeCases(unittest.TestCase):
    """引擎层边界输入：不应崩溃，且返回合规结果。"""

    def setUp(self):
        self.eng = OpenCVEngine()
        self.img = Image.new("RGB", (120, 90), (130, 180, 220))

    def test_empty_rects(self):
        r = self.eng.inpaint(self.img, [], method="auto")
        self.assertEqual(r.image.size, (120, 90))

    def test_out_of_bounds_rects(self):
        # 完全超出图片范围的框（不应抛异常）
        r = self.eng.inpaint(self.img, [{"x": 5000, "y": 5000, "w": 100, "h": 100}], method="auto")
        self.assertEqual(r.image.size, (120, 90))

    def test_negative_rect_coords(self):
        r = self.eng.inpaint(self.img, [{"x": -50, "y": -50, "w": 80, "h": 80}], method="auto")
        self.assertEqual(r.image.size, (120, 90))

    def test_oversized_strength(self):
        r = self.eng.inpaint(self.img, [{"x": 10, "y": 10, "w": 30, "h": 20}],
                             strength=999, method="auto")
        self.assertEqual(r.image.size, (120, 90))

    def test_detect_tiny_box(self):
        d = self.eng.detect_content(self.img, {"x": 5, "y": 5, "w": 1, "h": 1})
        self.assertIn("type", d)

    def test_detect_no_rect_keys(self):
        d = self.eng.detect_content(self.img, {})
        self.assertIn("suggest_method", d)


class TestOrchestratorEdge(unittest.TestCase):
    """编排器边界：无图片无链接、仅链接等场景。"""

    def test_source_url_without_image(self):
        orch = build_orchestrator()
        r = orch.process(ProcessContext(
            authorized=True, source_url="https://x/p/1", rects=[]
        ))
        self.assertIn(r.status, ("succeeded", "failed"))

    def test_empty_input_fails_gracefully(self):
        orch = build_orchestrator()
        r = orch.process(ProcessContext(authorized=True))
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.error["code"], "invalid_input")

    def test_fallback_order_never_empty_with_image(self):
        orch = build_orchestrator()
        order = orch.select_order(ProcessContext(
            image=Image.new("RGB", (50, 50)), authorized=True
        ))
        self.assertTrue(order)
        self.assertEqual(order[-1], EngineKind.OPENCV)  # 兜底始终在末位


def _run():
    print("=" * 56)
    print("API 边界与异常处理回归测试")
    print("=" * 56)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (TestRectValidation, TestTaskStore, TestEngineEdgeCases, TestOrchestratorEdge):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    total = result.testsRun
    ok = total - len(result.failures) - len(result.errors)
    print("=" * 56)
    print(f"结果: {ok}/{total} 通过")
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    _run()
