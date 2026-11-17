# -*- coding: utf-8 -*-
"""
把真实测试图转换成自测脚本可读的原始 RGB 二进制。
产物：_tmp/wood.bin（裸 RGB，W*H*3 字节）+ _tmp/wood.meta.json

用法：python prepare.py
"""
import json
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, '06_素材与示例', '测试输入', 'test_wood_texture_watermark.jpg')
TMP = os.path.join(HERE, '_tmp')

def main():
    if not os.path.exists(SRC):
        print('找不到测试图: ' + SRC)
        return 1
    os.makedirs(TMP, exist_ok=True)
    im = Image.open(SRC).convert('RGB')
    W, H = im.size
    with open(os.path.join(TMP, 'wood.bin'), 'wb') as f:
        f.write(im.tobytes())
    with open(os.path.join(TMP, 'wood.meta.json'), 'w', encoding='utf-8') as f:
        json.dump({'W': W, 'H': H}, f)
    print('已生成 _tmp/wood.bin  %dx%d  %.1fMB' % (W, H, W * H * 3 / 1048576))
    return 0

if __name__ == '__main__':
    sys.exit(main())
