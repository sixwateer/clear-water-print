# -*- coding: utf-8 -*-
"""
把自测输出的 PPM 裁剪图拼成一张人工复核对比图。
- 前 3 个场景（正常框/贴底边/贴右下角）纵向拼接
- 每个场景上为"原图"、下为"修复后"

用法：先 node run.js，再 python compare.py
产物：对比图.png
"""
import os

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(HERE, '_tmp')
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, '06_素材与示例', '测试输入', 'test_wood_texture_watermark.jpg')


def read_ppm(path):
    with open(path, 'rb') as f:
        data = f.read()
    # 解析 P6 头：P6\n<w> <h>\n255\n
    idx = 0
    tokens = []
    while len(tokens) < 4:
        while data[idx:idx + 1].isspace():
            idx += 1
        start = idx
        while not data[idx:idx + 1].isspace():
            idx += 1
        tokens.append(data[start:idx])
    idx += 1  # 跳过分隔空白
    w, h = int(tokens[1]), int(tokens[2])
    arr = np.frombuffer(data[idx:idx + w * h * 3], dtype=np.uint8).reshape(h, w, 3)
    return arr


def main():
    names = ['正常框', '贴底边', '贴右下角']
    panels = []
    for n in names:
        p = os.path.join(TMP, 'out_%s.ppm' % n)
        if not os.path.exists(p):
            print('缺少 %s，请先运行 node run.js' % p)
            return 1
        panels.append(read_ppm(p))

    h, w, _ = panels[0].shape
    orig = np.asarray(Image.open(SRC).convert('RGB'))
    # 从原图裁出同一区域（run.js 的裁剪起点 = 框左上 - 60）
    rects = {'正常框': (1045, 2203), '贴底边': (1030, 2195), '贴右下角': (1045, 2195)}
    rows = []
    for n, panel in zip(names, panels):
        x, y = rects[n]
        oh, ow, _ = panel.shape
        # 与 run.js 的 writePPM 完全一致的裁剪起点钳制
        x0 = max(0, min(orig.shape[1] - ow, x - 60))
        y0 = max(0, min(orig.shape[0] - oh, y - 60))
        crop = orig[y0:y0 + oh, x0:x0 + ow]
        rows.append(crop)
        rows.append(panel)

    out = np.concatenate(rows, axis=0)
    scale = 2
    out = np.asarray(Image.fromarray(out).resize((out.shape[1] * scale, out.shape[0] * scale), Image.LANCZOS))
    dst = os.path.join(HERE, '对比图.png')
    Image.fromarray(out).save(dst)
    print('已生成 %s  (%dx%d)' % (dst, out.shape[1], out.shape[0]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
