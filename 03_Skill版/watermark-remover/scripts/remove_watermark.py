#!/usr/bin/env python3
"""
净像 · 图片去水印处理脚本（Skill 版核心）

自包含、命令行调用，仅依赖 Pillow + NumPy（OpenCV 可选增强）。
对有权处理的自有图片，按给定的水印框执行修复。

用法：
  python remove_watermark.py <输入图> <输出图> [选项]

示例：
  # 用 JSON 框选文件
  python remove_watermark.py in.png out.png --rects '[{"x":650,"y":520,"w":230,"h":60}]'
  # 从文本框读取（每行 x,y,w,h）
  python remove_watermark.py in.png out.png --rects-file boxes.txt --mode smart --iter 3
  # 自动模式：整张图右下角常见水印区
  python remove_watermark.py in.png out.png --auto bottom_right

修复模式：
  smart    拉普拉斯扩散（默认，纯色/渐变背景近乎无痕）
  inpaint  OpenCV TELEA 修复（有 opencv 时，复杂背景更好）
  average  边缘平均色填充（最快）
  texture  纹理平移（重复纹理背景）
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


def laplace_fill(arr, x, y, w, h, iters=320, pad=2):
    """拉普拉斯扩散修复：边界为真实像素，内部从边界均色初值迭代收敛。"""
    H, W, _ = arr.shape
    x, y = max(0, x), max(0, y)
    w, h = min(w, W - x), min(h, H - y)
    if w <= 0 or h <= 0:
        return
    lw, lh = w + pad * 2, h + pad * 2
    region = np.zeros((lh, lw, 3), dtype=np.float64)
    border_sum = np.zeros(3)
    border_n = 0
    for j in range(lh):
        for i in range(lw):
            gx = min(W - 1, max(0, x - pad + i))
            gy = min(H - 1, max(0, y - pad + j))
            inner = pad <= i < lw - pad and pad <= j < lh - pad
            if not inner:
                region[j, i] = arr[gy, gx]
                border_sum += arr[gy, gx]
                border_n += 1
    bg = border_sum / max(border_n, 1)
    region[pad:lh - pad, pad:lw - pad] = bg
    for _ in range(iters):
        region[pad:lh - pad, pad:lw - pad] = (
            region[pad:lh - pad, pad - 1:lw - pad - 1]
            + region[pad:lh - pad, pad + 1:lw - pad + 1]
            + region[pad - 1:lh - pad - 1, pad:lw - pad]
            + region[pad + 1:lh - pad + 1, pad:lw - pad]
        ) * 0.25
    arr[y:y + h, x:x + w] = region[pad:pad + h, pad:pad + w]


def average_fill(arr, x, y, w, h, pad=3):
    """边缘平均色填充。"""
    H, W, _ = arr.shape
    x, y = max(0, x), max(0, y)
    w, h = min(w, W - x), min(h, H - y)
    if w <= 0 or h <= 0:
        return
    px = []
    for i in range(-pad, w + pad):
        for sy in (y - pad, y + h + pad - 1):
            if 0 <= x + i < W and 0 <= sy < H:
                px.append(arr[sy, x + i])
    for j in range(-pad, h + pad):
        for sx in (x - pad, x + w + pad - 1):
            if 0 <= sx < W and 0 <= y + j < H:
                px.append(arr[y + j, sx])
    color = np.mean(px, axis=0) if px else np.zeros(3)
    arr[y:y + h, x:x + w] = color


def texture_fill(arr, x, y, w, h):
    """纹理平移：优先从框上方复制同尺寸区域。"""
    H, W, _ = arr.shape
    x, y = max(0, x), max(0, y)
    w, h = min(w, W - x), min(h, H - y)
    if w <= 0 or h <= 0:
        return
    sy = y - h - 4
    if sy < 0:
        sy = y + h + 4
    sy = max(0, min(H - h, sy))
    arr[y:y + h, x:x + w] = arr[sy:sy + h, x:x + w]


def opencv_inpaint(arr, rects, radius=5):
    """OpenCV TELEA 修复（复杂背景更好），需 opencv-python。"""
    H, W, _ = arr.shape
    mask = np.zeros((H, W), dtype=np.uint8)
    for x, y, w, h in rects:
        x, y = max(0, x), max(0, y)
        w, h = min(w, W - x), min(h, H - y)
        if w > 0 and h > 0:
            mask[y:y + h, x:x + w] = 255
    bgr = cv2.cvtColor(arr.astype(np.uint8), cv2.COLOR_RGB2BGR)
    result = cv2.inpaint(bgr, mask, radius, cv2.INPAINT_TELEA)
    return cv2.cvtColor(result, cv2.COLOR_BGR2RGB)


def parse_rects(raw, image_size):
    """解析框选：JSON 字符串 / 文件路径 / 自动模式。"""
    W, H = image_size
    if raw and raw.startswith("auto:"):
        pos = raw.split(":", 1)[1]
        bw, bh = int(W * 0.28), int(H * 0.12)
        positions = {
            "bottom_right": (W - bw - 20, H - bh - 20),
            "bottom_left": (20, H - bh - 20),
            "top_right": (W - bw - 20, 20),
            "top_left": (20, 20),
        }
        x, y = positions.get(pos, positions["bottom_right"])
        return [(x, y, bw, bh)]
    if not raw:
        return []
    data = None
    if raw.strip().startswith("["):
        data = json.loads(raw)
    else:
        p = Path(raw)
        if p.exists():
            lines = [l.strip() for l in p.read_text(encoding="utf-8").splitlines()
                     if l.strip() and not l.startswith("#")]
            data = []
            for line in lines:
                nums = [int(float(v)) for v in line.replace(",", " ").split()]
                if len(nums) >= 4:
                    data.append({"x": nums[0], "y": nums[1], "w": nums[2], "h": nums[3]})
        else:
            raise ValueError(f"无法解析 rects：{raw}")
    return [(int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"])) for r in data]


def process(in_path, out_path, rects, mode="smart", iters=320, sharpen=False):
    img = Image.open(in_path).convert("RGB")
    if mode == "inpaint":
        if not HAS_CV2:
            raise RuntimeError("inpaint 模式需要 opencv-python，请先安装或改用 smart 模式")
        arr = opencv_inpaint(np.array(img), rects)
    else:
        arr = np.array(img, dtype=np.float64)
        for (x, y, w, h) in rects:
            if mode == "average":
                average_fill(arr, x, y, w, h)
            elif mode == "texture":
                texture_fill(arr, x, y, w, h)
            else:  # smart
                laplace_fill(arr, x, y, w, h, iters=iters)
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    result = Image.fromarray(arr, "RGB")
    if sharpen:
        # 轻度 USM 锐化：原图放大 1.2 倍减去模糊 0.2 倍
        blur = result.filter(ImageFilter.GaussianBlur(1))
        out = (np.array(result, dtype=np.float64) * 1.2
               - np.array(blur, dtype=np.float64) * 0.2)
        result = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    result.save(out_path)
    return result.size


def main():
    ap = argparse.ArgumentParser(description="净像 · 图片去水印（Skill 核心脚本）")
    ap.add_argument("input", help="输入图片路径")
    ap.add_argument("output", help="输出图片路径")
    ap.add_argument("--rects", default="", help='水印框 JSON，如 [{"x":650,"y":520,"w":230,"h":60}]')
    ap.add_argument("--rects-file", default="", help="框选文本框路径（每行 x,y,w,h）")
    ap.add_argument("--auto", default="", help="自动框选：bottom_right/bottom_left/top_right/top_left")
    ap.add_argument("--mode", default="smart", choices=["smart", "inpaint", "average", "texture"])
    ap.add_argument("--iter", type=int, default=320, help="smart 模式迭代次数（越大越精细）")
    ap.add_argument("--sharpen", action="store_true", help="轻度锐化")
    args = ap.parse_args()

    raw = args.rects or args.rects_file
    if args.auto:
        raw = "auto:" + args.auto
    try:
        src = Image.open(args.input)
        rects = parse_rects(raw, src.size)
        if not rects:
            print(json.dumps({"ok": False, "error": "未提供任何水印框，请用 --rects/--rects-file/--auto"},
                             ensure_ascii=False))
            sys.exit(2)
        size = process(args.input, args.output, rects, args.mode, args.iter, args.sharpen)
        print(json.dumps({"ok": True, "output": args.output, "size": size,
                          "rects": rects, "mode": args.mode,
                          "opencv_available": HAS_CV2}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
