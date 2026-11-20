"""线条去除内核（Python / numpy）——与权威 HTML（11:06 定稿版 MD5 6e65579c）逐项对齐。

设计目标
--------
把 HTML 的 lineRemove + smartFill 诊断参数原样移植到后端，保证同一张图、
同一个多边形，在 HTML 前端与后端 API 得到一致的去除效果：

* 坐标：顶点 round 取整并钳到图像范围（画布坐标由调用方除以 scale 后传入）。
* ROI 外扩：max(8, round(min(w, h) * 0.28))，与矩形 smartFill 完全一致。
* mask：射线法判定像素中心是否落在闭合多边形内；只有 mask 内会被写回，
        线条外像素逐字节不变（含锐化）。
* 三模式：
    - average：mask 外 pad=3 环取均色填入
    - texture：从 ROI 上方（越界则下方）偏移 4px 平移纹理
    - smart：rad 7~15 中值背景估计、残差 P97 判极性、th=max(26,p97*0.42)、
             _closeMask、cov 0.04/0.004、宽高比 2.0，
             整框 Coons 或膨胀 mask 后迭代扩散（迭代下限 150）
* 锐化：unsharp mask，仅增强 mask 内像素（amount=0.25）。

本模块只依赖 numpy（基础依赖已包含）；不修改合规/授权/API 结构。
"""

from __future__ import annotations

import math
import numpy as np

# 与 HTML FILL 常量 / smartFill 参数一一对应
EXP_MIN = 8
EXP_RATIO = 0.28
MIN_SIDE = 6
MIN_MASK_PX = 8
RAD_MIN, RAD_MAX = 7, 15
P97 = 0.97
TH_MIN, TH_RATIO = 26, 0.42
COV_HIGH, COV_LOW = 0.04, 0.004
ASPECT = 2.0
ITER_FLOOR = 150
PAD = 3
TEX_OFFSET = 4
SHARPEN_AMOUNT = 0.25


def _hist_median(hist: np.ndarray, target: int) -> int:
    acc = 0
    for i in range(256):
        acc += int(hist[i])
        if acc >= target:
            return i
    return 255


def _median_blur(src: np.ndarray, w: int, h: int, r: int) -> np.ndarray:
    """精确复刻 HTML _medianBlur：列直方图 + 窗口滑动 + 直方图中值。"""
    out = np.empty((h, w), dtype=np.uint8)
    target = ((2 * r + 1) * (2 * r + 1)) >> 1
    flat = src.ravel()  # HTML 传入的是一维 gray[y*w+x]
    for y in range(h):
        # band[x] = 该列在 y-r..y+r（行 clamp）上的像素集合
        band_rows = [np.clip(y + dy, 0, h - 1) * w for dy in range(-r, r + 1)]
        col = [np.bincount(flat[[row + x for row in band_rows]], minlength=256).astype(np.int64)
               for x in range(w)]
        win = np.zeros(256, dtype=np.int64)
        for d in range(-r, r + 1):
            win += col[min(w - 1, max(0, d))]
        for x in range(w):
            out[y, x] = _hist_median(win, target)
            oc = min(w - 1, max(0, x - r))
            ic = min(w - 1, max(0, x + r + 1))
            if oc != ic:
                win += col[ic] - col[oc]
    return out.ravel()


def _js_round(x: float) -> int:
    """JS Math.round 语义：四舍五入（half-up），与 Python 的银行家舍入不同。"""
    return int(math.floor(x + 0.5))


def _pct(arr: np.ndarray, p: float) -> float:
    if arr.size == 0:
        return 0.0
    a = np.sort(np.asarray(arr, dtype=np.float32).ravel())
    return float(a[min(a.size - 1, _js_round((a.size - 1) * p))])


def _morph(m: np.ndarray, w: int, h: int, op: str) -> np.ndarray:
    """8 邻域膨胀/腐蚀；边界像素保持原值（与 HTML _morph 一致）。"""
    out = m.copy()
    nb = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)]
    for yy in range(1, h - 1):
        for xx in range(1, w - 1):
            k = yy * w + xx
            if op == "dilate":
                if not out[k]:
                    for dx, dy in nb:
                        if m[(yy + dy) * w + xx + dx]:
                            out[k] = 1
                            break
            else:
                if out[k]:
                    for dx, dy in nb:
                        if not m[(yy + dy) * w + xx + dx]:
                            out[k] = 0
                            break
    return out


def _close_mask(m: np.ndarray, w: int, h: int) -> np.ndarray:
    return _morph(_morph(m, w, h, "dilate"), w, h, "erode")


def _coons(region: np.ndarray, w: int, h: int) -> np.ndarray:
    """双线性协调插值：region 形状 (w*h, 3)，与 HTML _coons 同索引。"""
    out = np.empty_like(region)
    for c in range(3):
        for j in range(h):
            b = j / (h - 1) if h > 1 else 0.0
            for i in range(w):
                a = i / (w - 1) if w > 1 else 0.0
                top = region[i * 3 + c]
                bot = region[((h - 1) * w + i) * 3 + c]
                lf = region[j * w * 3 + c]
                rt = region[(j * w + w - 1) * 3 + c]
                c00 = region[c]
                c01 = region[(w - 1) * 3 + c]
                c10 = region[((h - 1) * w) * 3 + c]
                c11 = region[((h - 1) * w + w - 1) * 3 + c]
                out[(j * w + i) * 3 + c] = (
                    (top * (1 - b) + bot * b)
                    + (lf * (1 - a) + rt * a)
                    - ((c00 * (1 - a) + c01 * a) * (1 - b) + (c10 * (1 - a) + c11 * a) * b)
                )
    return out


def _diffuse(region: np.ndarray, w: int, h: int, mask: np.ndarray, iters: int) -> np.ndarray:
    cur = np.array(region, dtype=np.float32, copy=True)
    tmp = np.empty_like(cur)
    for _ in range(iters):
        for j in range(h):
            for i in range(w):
                k = j * w + i
                if not mask[k]:
                    continue
                u = (j - 1 if j > 0 else j) * w + i
                d = (j + 1 if j < h - 1 else j) * w + i
                l = j * w + (i - 1 if i > 0 else i)
                r = j * w + (i + 1 if i < w - 1 else i)
                for c in range(3):
                    tmp[k * 3 + c] = (cur[u * 3 + c] + cur[d * 3 + c] + cur[l * 3 + c] + cur[r * 3 + c]) * 0.25
        idx = np.flatnonzero(mask)
        if idx.size:
            cur[idx * 3] = tmp[idx * 3]
            cur[idx * 3 + 1] = tmp[idx * 3 + 1]
            cur[idx * 3 + 2] = tmp[idx * 3 + 2]
    return cur


def _in_poly(px: float, py: float, pts: list[tuple[float, float]]) -> bool:
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


def _write_mask(dst: np.ndarray, src: np.ndarray, W: int, x1: int, y1: int, rw: int, rh: int, mask: np.ndarray,
                write_all: bool = False) -> None:
    for j in range(rh):
        for i in range(rw):
            k = j * rw + i
            if not write_all and not mask[k]:
                continue
            d = ((y1 + j) * W + (x1 + i)) * 4
            # HTML 写入 Uint8ClampedArray：先 round-to-nearest，再 clamp 到 [0,255]
            # （numpy 的 uint8 赋值会溢出回绕，必须先 np.clip）
            dst[d] = np.clip(np.rint(src[k * 3]), 0, 255)
            dst[d + 1] = np.clip(np.rint(src[k * 3 + 1]), 0, 255)
            dst[d + 2] = np.clip(np.rint(src[k * 3 + 2]), 0, 255)


def _coons_full(rgb: np.ndarray, rw: int, rh: int) -> np.ndarray:
    """整框 Coons（矩形 smartFill 用，写回整个 ROI）。"""
    return _coons(rgb, rw, rh)


def polygon_inpaint(image: Image.Image, polygons: list[list[tuple[float, float]]],
                    mode: str = "smart", iters: int = 320, sharpen: bool = True) -> Image.Image:
    """闭合线条内去除目标，对齐 HTML lineRemove：只改 mask 内，线条外逐字节不变。

    参数
    ----
    image : PIL.Image 原图（RGB/RGBA 均可；输出统一 RGB）
    polygons : 闭合轮廓点列表（原图像素坐标），由 parse_polygons 解析并自动闭合
    mode : smart / average / texture，与 HTML S.mode 对应
    iters : 迭代次数（HTML CONFIG.autoIterations[S.iter]，默认 320）
    sharpen : 是否做轻度锐化（HTML S.sharpen，默认开）
    """
    from PIL import Image as _Image  # 局部导入，避免与 api_v2 的同名导入冲突

    if not polygons:
        return image
    src = np.asarray(image.convert("RGBA")).copy()
    H, W = src.shape[:2]
    flat = src.reshape(-1)
    # 全图 allow 掩码：记录所有多边形 mask，锐化只增强这些像素（与 HTML sharpen 一致）
    allow = np.zeros(H * W, dtype=np.uint8)

    for pts_raw in polygons:
        # HTML lineRemove 收到的是未显式闭合的原始轨迹；射线法内部用 j=n-1 闭合。
        # API 的 parse_polygons 会自动补一个闭合点，这里去掉末尾与首点重复的退化边，
        # 否则多出的零长边会干扰奇偶判定（边界像素 mask 不一致）。
        pts = list(pts_raw)
        if len(pts) >= 2 and pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) < 3:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        poly_w, poly_h = max_x - min_x, max_y - min_y
        if poly_w <= MIN_SIDE or poly_h <= MIN_SIDE:
            continue
        exp = max(EXP_MIN, _js_round(min(poly_w, poly_h) * EXP_RATIO))
        x1 = max(0, math.floor(min_x) - exp)
        y1 = max(0, math.floor(min_y) - exp)
        x2 = min(W, math.ceil(max_x) + exp)
        y2 = min(H, math.ceil(max_y) + exp)
        rw, rh = x2 - x1, y2 - y1
        if rw < 4 or rh < 4:
            continue
        # 射线法 mask（相对整图坐标，像素中心 +0.5）
        mask = np.zeros(rw * rh, dtype=np.uint8)
        for j in range(rh):
            for i in range(rw):
                if _in_poly(x1 + i + 0.5, y1 + j + 0.5, pts):
                    mask[j * rw + i] = 1
        if int(mask.sum()) < MIN_MASK_PX:
            continue
        # 合并进全图 allow（相对 ROI 坐标 → 整图坐标）
        for j in range(rh):
            row = j * rw
            for i in range(rw):
                if mask[row + i]:
                    allow[(y1 + j) * W + (x1 + i)] = 1
        # 局部 RGB（来自扩大的 ROI）
        rgb = np.empty(rw * rh * 3, dtype=np.float32)
        for j in range(rh):
            for i in range(rw):
                s = ((y1 + j) * W + (x1 + i)) * 4
                t = (j * rw + i) * 3
                rgb[t] = flat[s]
                rgb[t + 1] = flat[s + 1]
                rgb[t + 2] = flat[s + 2]

        method = "skip"
        if mode == "average":
            near = np.zeros(rw * rh, dtype=np.uint8)
            r = g = b = 0.0
            n = 0
            for j in range(rh):
                for i in range(rw):
                    k = j * rw + i
                    if mask[k]:
                        continue
                    touch = False
                    for dy in range(-PAD, PAD + 1):
                        if touch:
                            break
                        for dx in range(-PAD, PAD + 1):
                            ni, nj = i + dx, j + dy
                            if ni < 0 or nj < 0 or ni >= rw or nj >= rh:
                                continue
                            if mask[nj * rw + ni]:
                                touch = True
                                break
                    if touch:
                        near[k] = 1
                        r += rgb[k * 3]
                        g += rgb[k * 3 + 1]
                        b += rgb[k * 3 + 2]
                        n += 1
            r /= n or 1
            g /= n or 1
            b /= n or 1
            filled = np.empty(rw * rh * 3, dtype=np.float32)
            filled[0::3] = r
            filled[1::3] = g
            filled[2::3] = b
            _write_mask(flat, filled, W, x1, y1, rw, rh, mask)
            method = "average"
        elif mode == "texture":
            sy = y1 - rh - TEX_OFFSET
            if sy < 0:
                sy = y1 + rh + TEX_OFFSET
            sy = max(0, min(H - rh, sy))
            sx = max(0, min(W - rw, x1))
            # 从原图（未被本轮修改）取纹理块
            block = np.asarray(image.convert("RGBA"))[sy:sy + rh, sx:sx + rw]
            tex = np.empty(rw * rh * 3, dtype=np.float32)
            for j in range(rh):
                for i in range(rw):
                    t = (j * rw + i) * 3
                    tex[t] = block[j, i, 0]
                    tex[t + 1] = block[j, i, 1]
                    tex[t + 2] = block[j, i, 2]
            _write_mask(flat, tex, W, x1, y1, rw, rh, mask)
            method = "texture"
        else:
            # smart：复用矩形 smartFill 的全部诊断参数
            gray = np.empty(rw * rh, dtype=np.uint8)
            for j in range(rh):
                for i in range(rw):
                    s = ((y1 + j) * W + (x1 + i)) * 4
                    gray[j * rw + i] = _js_round(0.299 * flat[s] + 0.587 * flat[s + 1] + 0.114 * flat[s + 2])
            rad = max(RAD_MIN, min(RAD_MAX, int((min(rw, rh) / 6)) | 1))
            if rad % 2 == 0:
                rad += 1
            bg = _median_blur(gray, rw, rh, rad)
            diff = gray.astype(np.float32) - bg.astype(np.float32)
            pos = diff[diff > 0]
            neg = -diff[diff < 0]
            p97 = _pct(pos, P97)
            n97 = _pct(neg, P97)
            if p97 >= n97 and p97 > 12:
                residual = diff
                th = max(TH_MIN, p97 * TH_RATIO)
                polarity = "light"
            else:
                residual = -diff
                th = max(TH_MIN, n97 * TH_RATIO)
                polarity = "dark"
            m = np.zeros(rw * rh, dtype=np.uint8)
            m[residual > th] = 1
            m = _close_mask(m, rw, rh)
            cov = float(m.sum()) / (rw * rh)
            # mask 外的笔画全部丢弃，诊断只作用于线条内
            m[mask == 0] = 0
            if (poly_w / poly_h >= ASPECT and polarity == "light" and cov > COV_HIGH) or cov < COV_LOW:
                _write_mask(flat, _coons(rgb, rw, rh), W, x1, y1, rw, rh, mask)
                method = "smooth"
            else:
                md = _morph(m, rw, rh, "dilate")
                md[mask == 0] = 0
                mc = int(md.sum())
                if mc < rw * rh * COV_LOW:
                    _write_mask(flat, _coons(rgb, rw, rh), W, x1, y1, rw, rh, mask)
                    method = "smooth"
                else:
                    filled = _diffuse(rgb, rw, rh, md, max(iters, ITER_FLOOR))
                    _write_mask(flat, filled, W, x1, y1, rw, rh, mask)
                    method = "stroke"

    out = src.reshape(H, W, 4)
    if sharpen:
        out = _sharpen_mask(out, H, W, SHARPEN_AMOUNT, allow)
    return _Image.fromarray(np.ascontiguousarray(out[:, :, :3]), "RGB")


def _sharpen_mask(data: np.ndarray, H: int, W: int, amount: float, allow: np.ndarray) -> np.ndarray:
    """轻度锐化：只增强 allow 内像素（与 HTML sharpen 的 mask 限制一致）。"""
    if amount <= 0:
        return data
    src = data.astype(np.float32)
    out = src.copy()
    up = np.concatenate([src[0:1], src[:-1]], axis=0)
    down = np.concatenate([src[1:], src[-1:]], axis=0)
    left = np.concatenate([src[:, 0:1], src[:, :-1]], axis=1)
    right = np.concatenate([src[:, 1:], src[:, -1:]], axis=1)
    n = (up + down + left + right) * 0.25
    delta = (src - n) * amount
    # 只在 allow 内、且非最外圈（HTML 循环 y=1..H-2, x=1..W-2）应用
    yy, xx = np.nonzero(allow.reshape(H, W))
    keep = (yy > 0) & (yy < H - 1) & (xx > 0) & (xx < W - 1)
    yy, xx = yy[keep], xx[keep]
    out[yy, xx, :3] = src[yy, xx, :3] + delta[yy, xx, :3]
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)
