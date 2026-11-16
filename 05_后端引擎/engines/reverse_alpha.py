"""反向 Alpha 混合（Reverse Alpha Blending）——固定模板水印的像素级无损恢复。

参考 gemini-watermark-remover (MIT, © AllenK / GargantuaX) 的数学精确思路。

原理
====
多数"水印"是半透明图层叠加到原图上：

    observed = α · F + (1 - α) · B

其中：
    B        : 原始背景（我们想恢复的真值）
    F        : 水印前景色（模板给定）
    α        : 每像素不透明度（模板给定，0~1）
    observed : 我们拿到的带水印图

若已知 F 与 α（固定模板），可精确反解：

    B = (observed - α · F) / (1 - α)       当 α < 1
    B = observed                            当 α = 0（无水印区，直接保留）

由于是代数逆运算而非生成式修复，只要模板匹配，结果在数值上可无损还原原始像素，
优于 AI inpainting 的"猜测式"重建。

适用条件
========
1. 水印是 alpha 合成（非烧录进画面内容）。
2. 有对应的固定模板：位置 + 前景色 F + alpha 图样。
3. 8bit 量化会引入 ±1 舍入误差；本实现用 float64 中间计算并四舍五入到最近整数，
   将误差控制在最小。

局限
====
- 若水印被二次压缩 / 缩放 / 调色，模板失配，需重新标定。
- α=1 的完全不透明像素信息已丢失，无法恢复（公式分母为 0）。
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image


@dataclass
class WatermarkTemplate:
    """固定水印模板。

    alpha: HxW float32 数组，取值 0~1，表示水印在该像素的不透明度。
    foreground: RGB 三元组，水印前景色。
    anchor: 模板左上角在图片中的放置方式：
        - "bottom_right": 右下角（小红书/抖音常见）
        - "top_left" / "top_right" / "bottom_left" / "center"
        - (x, y): 显式左上角像素坐标
    offset: 相对 anchor 的偏移 (dx, dy)。
    margin: 距边缘的边距（anchor 为角落时生效）。
    """

    id: str
    label: str
    alpha: np.ndarray
    foreground: tuple[int, int, int]
    anchor: str | tuple[int, int] = "bottom_right"
    offset: tuple[int, int] = (0, 0)
    margin: tuple[int, int] = (24, 24)  # (x, y)
    meta: dict[str, Any] = field(default_factory=dict)

    def placement(self, img_w: int, img_h: int) -> tuple[int, int]:
        """计算模板左上角在图片中的 (x, y)。"""
        aw, ah = self.alpha.shape[1], self.alpha.shape[0]
        dx, dy = self.offset
        mx, my = self.margin
        if isinstance(self.anchor, tuple):
            x, y = self.anchor
        elif self.anchor == "bottom_right":
            x, y = img_w - aw - mx, img_h - ah - my
        elif self.anchor == "bottom_left":
            x, y = mx, img_h - ah - my
        elif self.anchor == "top_right":
            x, y = img_w - aw - mx, my
        elif self.anchor == "top_left":
            x, y = mx, my
        elif self.anchor == "center":
            x, y = (img_w - aw) // 2, (img_h - ah) // 2
        else:
            x, y = img_w - aw - mx, img_h - ah - my
        return x + dx, y + dy


class TemplateRegistry:
    """水印模板注册中心。支持内置示例模板与用户自定义模板。"""

    def __init__(self):
        self._templates: dict[str, WatermarkTemplate] = {}

    def register(self, template: WatermarkTemplate) -> None:
        self._templates[template.id] = template

    def unregister(self, template_id: str) -> None:
        self._templates.pop(template_id, None)

    def get(self, template_id: str) -> WatermarkTemplate | None:
        return self._templates.get(template_id)

    def list(self) -> list[dict]:
        return [
            {"id": t.id, "label": t.label, "anchor": str(t.anchor),
             "size": [t.alpha.shape[1], t.alpha.shape[0]], "meta": t.meta}
            for t in self._templates.values()
        ]

    def match(self, image: Image.Image, template_id: str | None = None,
              threshold: float = 0.35) -> tuple[WatermarkTemplate, float] | None:
        """在图片上匹配模板，返回 (模板, 匹配置信度)。

        当前实现：对指定模板（或全部）在 anchor 位置做颜色一致性评分。
        更严格的模板匹配可引入归一化互相关（NCC）——预留扩展点。
        """
        # 显式指定 template_id 时只检查该模板；否则遍历全部
        if template_id:
            t = self.get(template_id)
            candidates = [t] if t else []
            # 用户显式声明模板时，视为强意图，降低匹配门槛
            effective_threshold = min(threshold, 0.05)
        else:
            candidates = list(self._templates.values())
            effective_threshold = threshold

        arr = np.asarray(image.convert("RGB"), dtype=np.float32)
        h, w = arr.shape[:2]
        best: tuple[WatermarkTemplate, float] | None = None
        for t in candidates:
            aw, ah = t.alpha.shape[1], t.alpha.shape[0]
            if aw > w or ah > h:
                continue
            x, y = t.placement(w, h)
            x = max(0, min(x, w - aw)); y = max(0, min(y, h - ah))
            region = arr[y:y + ah, x:x + aw]
            fg = np.array(t.foreground, dtype=np.float32)
            # 水印像素 = alpha 较大的区域；用 alpha 相对峰值判定，兼容 alpha<0.5 的模板
            peak = float(t.alpha.max())
            strong = t.alpha >= max(peak * 0.6, 1e-3)
            if not strong.any():
                continue
            obs_strong = region[strong]
            fg_strong = np.broadcast_to(fg, obs_strong.shape)
            # 余弦相似度：水印区颜色方向应偏向前景色
            cos = (obs_strong * fg_strong).sum(1) / (
                np.linalg.norm(obs_strong, axis=1) * np.linalg.norm(fg_strong, axis=1) + 1e-6
            )
            score = float(np.clip(cos.mean(), 0, 1))
            if best is None or score > best[1]:
                best = (t, score)
        if best and best[1] >= effective_threshold:
            return best
        return None


def reverse_alpha_blend(image: Image.Image, template: WatermarkTemplate,
                        placement: tuple[int, int] | None = None) -> Image.Image:
    """执行反向 Alpha 混合，返回恢复后的图片。

    B = (observed - α·F) / (1-α)，α=1 的像素保持 observed（信息已丢失，无法恢复）。
    """
    arr = np.asarray(image.convert("RGB"), dtype=np.float64)
    h, w = arr.shape[:2]
    aw, ah = template.alpha.shape[1], template.alpha.shape[0]
    x, y = placement if placement is not None else template.placement(w, h)
    x = max(0, min(x, w - aw)); y = max(0, min(y, h - ah))

    region = arr[y:y + ah, x:x + aw]
    a = template.alpha.astype(np.float64)[..., None]          # HxWx1
    fg = np.array(template.foreground, dtype=np.float64)      # (3,)

    safe = np.where(a < 0.999, 1.0 - a, 1.0)                  # 避免除零
    recovered = (region - a * fg) / safe
    # α 接近 1 的像素无可靠背景，回退为 observed（或可用邻域，此处保守处理）
    recovered = np.where(a >= 0.999, region, recovered)
    recovered = np.clip(np.rint(recovered), 0, 255).astype(np.uint8)

    out = arr.astype(np.uint8).copy()
    out[y:y + ah, x:x + aw] = recovered
    return Image.fromarray(out, mode="RGB")


def make_solid_text_template(template_id: str, label: str, text_box_size: tuple[int, int],
                             foreground: tuple[int, int, int], alpha: float = 0.6,
                             **kwargs) -> WatermarkTemplate:
    """便捷构造：纯色矩形水印模板（用于演示与固定图样水印）。

    text_box_size: (w, h)；alpha 为矩形内恒定不透明度。
    """
    w, h = text_box_size
    a = np.full((h, w), float(alpha), dtype=np.float32)
    return WatermarkTemplate(id=template_id, label=label, alpha=a,
                             foreground=foreground, **kwargs)


# 全局默认注册中心（可被 Orchestrator 注入）
default_registry = TemplateRegistry()
