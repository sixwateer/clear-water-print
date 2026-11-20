/**
 * 净像小程序 · 线条去除内核
 * ------------------------------------------------------------------
 * 本模块把权威 HTML（2026-11-20 10:45 定稿版）的 lineRemove 及其依赖
 * 逐字移植为纯 JS（不依赖 DOM / canvas），供小程序 pages/index 调用。
 *
 * 与 HTML 的对应关系（唯一差异已用注释标出，行为等价）：
 *   - HTML 用全局 S.scale 换算画布坐标 → 这里由 opts.scale 传入
 *   - HTML texture 分支用 cx.getImageData(sx,sy,rw,rh) 从原图画布取样
 *     → 这里从 opts.sourceData（处理前的原图副本）按同样坐标取样
 *   其余：坐标取整、最小尺寸、ROI 外扩 28%/min8、射线法 mask、
 *   三模式参数（rad 7~15 / th max(26,p97*0.42) / cov 0.04/0.004 /
 *   宽高比 2.0 / 迭代下限 150 / pad 3 / 纹理偏移 4）全部逐字一致。
 *
 * 权威保证：扩大的 ROI 只用于取干净边界，所有写回（含锐化）严格限制在
 * 多边形 mask 内 —— 线条外像素逐字节不变。
 */
'use strict';

/** 从原图数据按 (sx,sy,rw,rh) 取出一块 RGBA，等价于 cx.getImageData(...).data */
function getRegionData(sourceData, W, H, sx, sy, rw, rh) {
  const out = new Uint8ClampedArray(rw * rh * 4);
  for (let j = 0; j < rh; j++) for (let i = 0; i < rw; i++) {
    const s = ((sy + j) * W + (sx + i)) * 4, t = (j * rw + i) * 4;
    out[t] = sourceData[s]; out[t + 1] = sourceData[s + 1];
    out[t + 2] = sourceData[s + 2]; out[t + 3] = sourceData[s + 3];
  }
  return out;
}

function _histMedian(hist, target) { let acc = 0; for (let i = 0; i < 256; i++) { acc += hist[i]; if (acc >= target) return i; } return 255; }

// 灰度中值滤波：估计局部背景，对叠加的文字不敏感
function _medianBlur(src, w, h, r) {
  const out = new Uint8Array(w * h), col = new Array(w);
  for (let x = 0; x < w; x++) col[x] = new Uint32Array(256);
  const win = new Uint32Array(256), target = ((2 * r + 1) * (2 * r + 1)) >> 1;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) col[x].fill(0);
    for (let dy = -r; dy <= r; dy++) {
      const row = Math.min(h - 1, Math.max(0, y + dy)) * w;
      for (let x = 0; x < w; x++) col[x][src[row + x]]++;
    }
    win.fill(0);
    for (let d = -r; d <= r; d++) { const c = col[Math.min(w - 1, Math.max(0, d))]; for (let i = 0; i < 256; i++) win[i] += c[i]; }
    for (let x = 0; x < w; x++) {
      out[y * w + x] = _histMedian(win, target);
      const oc = Math.min(w - 1, Math.max(0, x - r)), ic = Math.min(w - 1, Math.max(0, x + r + 1));
      if (oc !== ic) { const a = col[oc], b = col[ic]; for (let i = 0; i < 256; i++) win[i] += b[i] - a[i]; }
    }
  }
  return out;
}
function _pct(arr, p) {
  if (!arr.length) return 0;
  const a = Float32Array.from(arr); a.sort();
  return a[Math.min(a.length - 1, Math.round((a.length - 1) * p))];
}
function _morph(src, w, h, op) {
  const out = new Uint8Array(w * h);
  const NB = [[-1, 0], [1, 0], [0, -1], [0, 1], [-1, -1], [1, -1], [-1, 1], [1, 1]];
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const k = y * w + x;
    if (x === 0 || y === 0 || x === w - 1 || y === h - 1) { out[k] = src[k]; continue; }
    if (op === 'dilate') {
      let v = src[k];
      if (!v) for (const [dx, dy] of NB) { if (src[(y + dy) * w + x + dx]) { v = 1; break; } }
      out[k] = v;
    } else {
      let v = src[k];
      if (v) for (const [dx, dy] of NB) { if (!src[(y + dy) * w + x + dx]) { v = 0; break; } }
      out[k] = v;
    }
  }
  return out;
}
function _closeMask(m, w, h) { return _morph(_morph(m, w, h, 'dilate'), w, h, 'erode'); }

// 双线性协调插值：四边作边界，内部平滑过渡（适合平滑/渐变背景）
function _coons(region, w, h) {
  const out = new Float32Array(region.length);
  for (let c = 0; c < 3; c++) for (let j = 0; j < h; j++) {
    const b = h > 1 ? j / (h - 1) : 0;
    for (let i = 0; i < w; i++) {
      const a = w > 1 ? i / (w - 1) : 0;
      const top = region[i * 3 + c], bot = region[((h - 1) * w + i) * 3 + c];
      const lf = region[j * w * 3 + c], rt = region[(j * w + w - 1) * 3 + c];
      const c00 = region[c], c01 = region[(w - 1) * 3 + c];
      const c10 = region[((h - 1) * w) * 3 + c], c11 = region[((h - 1) * w + w - 1) * 3 + c];
      out[(j * w + i) * 3 + c] = (top * (1 - b) + bot * b) + (lf * (1 - a) + rt * a)
        - ((c00 * (1 - a) + c01 * a) * (1 - b) + (c10 * (1 - a) + c11 * a) * b);
    }
  }
  return out;
}
// 迭代扩散：只把 mask 内像素由周围背景填充（适合物体表面的小字）
function _diffuse(region, w, h, mask, iters) {
  let cur = new Float32Array(region);
  const tmp = new Float32Array(region.length);
  for (let it = 0; it < iters; it++) {
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
      const k = j * w + i; if (!mask[k]) continue;
      const u = (j > 0 ? j - 1 : j) * w + i, d = (j < h - 1 ? j + 1 : j) * w + i;
      const l = j * w + (i > 0 ? i - 1 : i), r = j * w + (i < w - 1 ? i + 1 : i);
      for (let c = 0; c < 3; c++) tmp[k * 3 + c] = (cur[u * 3 + c] + cur[d * 3 + c] + cur[l * 3 + c] + cur[r * 3 + c]) * 0.25;
    }
    for (let k = 0; k < w * h; k++) if (mask[k]) { cur[k * 3] = tmp[k * 3]; cur[k * 3 + 1] = tmp[k * 3 + 1]; cur[k * 3 + 2] = tmp[k * 3 + 2]; }
  }
  return cur;
}

/**
 * 线条去除：与 HTML 定稿版 lineRemove 逐字一致。
 * @param {Uint8ClampedArray} data 原图 RGBA（就地修改，仅多边形内）
 * @param {Number} W,H 原图尺寸
 * @param {Array<{x,y}>} shape 线条轨迹（画布/显示坐标）
 * @param {Number} iters 迭代次数
 * @param {String} mode smart/average/texture
 * @param {Object} opts { scale, sourceData, getImageData }
 * @returns {Object|null} {x,y,w,h,mask,method}
 */
function lineRemove(data, W, H, shape, iters, mode, opts) {
  opts = opts || {};
  const scale = opts.scale || 1;
  // 阶段一：画布坐标 -> 原图坐标，取整（与矩形换算一致；HTML 用 S.scale）
  const pts = shape.map(p => ({ x: Math.round(p.x / scale), y: Math.round(p.y / scale) }));
  if (pts.length < 3) return null;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  pts.forEach(p => { minX = Math.min(minX, p.x); minY = Math.min(minY, p.y); maxX = Math.max(maxX, p.x); maxY = Math.max(maxY, p.y); });
  const polyW = maxX - minX, polyH = maxY - minY;
  // 最小尺寸：与矩形创建的 w>6 && h>6 判定对齐
  if (polyW <= 6 || polyH <= 6) return null;
  // 阶段三：ROI 外扩与矩形 smartFill 完全一致，让边界落在干净背景上
  const exp = Math.max(8, Math.round(Math.min(polyW, polyH) * 0.28));
  const x1 = Math.max(0, Math.floor(minX) - exp), y1 = Math.max(0, Math.floor(minY) - exp);
  const x2 = Math.min(W, Math.ceil(maxX) + exp), y2 = Math.min(H, Math.ceil(maxY) + exp);
  const rw = x2 - x1, rh = y2 - y1;
  if (rw < 4 || rh < 4) return null;
  const region = { x: x1, y: y1, w: rw, h: rh };
  // 射线法：判断像素中心是否落在闭合多边形内（相对整图坐标）
  function inPoly(px, py) {
    let inside = false;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const xi = pts[i].x, yi = pts[i].y, xj = pts[j].x, yj = pts[j].y;
      if (((yi > py) !== (yj > py)) && (px < (xj - xi) * (py - yi) / (yj - yi) + xi)) inside = !inside;
    }
    return inside;
  }
  // 多边形 mask（扩大的 ROI 内，仅多边形内部为 1）——写回与锐化都只认它
  const mask = new Uint8Array(rw * rh);
  for (let j = 0; j < rh; j++) for (let i = 0; i < rw; i++) if (inPoly(x1 + i + 0.5, y1 + j + 0.5)) mask[j * rw + i] = 1;
  let cnt = 0; for (let i = 0; i < rw * rh; i++) cnt += mask[i];
  if (cnt < 8) return null;
  // 局部 RGB：来自扩大的 ROI，作为各模式的边界/采样来源
  const rgb = new Float32Array(rw * rh * 3);
  for (let j = 0; j < rh; j++) for (let i = 0; i < rw; i++) {
    const s = ((y1 + j) * W + (x1 + i)) * 4, t = (j * rw + i) * 3;
    rgb[t] = data[s]; rgb[t + 1] = data[s + 1]; rgb[t + 2] = data[s + 2];
  }
  const writeMask = (src) => {
    for (let j = 0; j < rh; j++) for (let i = 0; i < rw; i++) {
      const k = j * rw + i; if (!mask[k]) continue;
      const d = ((y1 + j) * W + (x1 + i)) * 4, t = k * 3;
      data[d] = src[t]; data[d + 1] = src[t + 1]; data[d + 2] = src[t + 2];
    }
  };
  let method = 'skip';
  if (mode === 'average') {
    // 与 fillAverage 一致：口罩外一圈 pad=3 取均色，填入口罩内
    const pad = 3; let r = 0, g = 0, b = 0, n = 0;
    const near = new Uint8Array(rw * rh);
    for (let j = 0; j < rh; j++) for (let i = 0; i < rw; i++) {
      const k = j * rw + i; if (mask[k]) continue;
      let touch = false;
      for (let dy = -pad; dy <= pad && !touch; dy++) for (let dx = -pad; dx <= pad; dx++) {
        const ni = i + dx, nj = j + dy;
        if (ni < 0 || nj < 0 || ni >= rw || nj >= rh) continue;
        if (mask[nj * rw + ni]) { touch = true; break; }
      }
      if (touch) { near[k] = 1; r += rgb[k * 3]; g += rgb[k * 3 + 1]; b += rgb[k * 3 + 2]; n++; }
    }
    r /= n || 1; g /= n || 1; b /= n || 1;
    const flat = new Float32Array(rw * rh * 3);
    for (let k = 0; k < rw * rh; k++) { flat[k * 3] = r; flat[k * 3 + 1] = g; flat[k * 3 + 2] = b; }
    writeMask(flat); method = 'average';
  } else if (mode === 'texture') {
    // 与 fillTexture 一致：从 ROI 上方（或下方）偏移 4px 平移同尺寸纹理，只写口罩内
    let sy = y1 - rh - 4; if (sy < 0) sy = y1 + rh + 4;
    sy = Math.max(0, Math.min(H - rh, sy));
    const sx = Math.max(0, Math.min(W - rw, x1));
    // HTML: const src=cx.getImageData(sx,sy,rw,rh).data;
    const src = opts.getImageData
      ? opts.getImageData(sx, sy, rw, rh).data
      : getRegionData(opts.sourceData || data, W, H, sx, sy, rw, rh);
    const tex = new Float32Array(rw * rh * 3);
    for (let k = 0; k < rw * rh; k++) { tex[k * 3] = src[k * 4]; tex[k * 3 + 1] = src[k * 4 + 1]; tex[k * 3 + 2] = src[k * 4 + 2]; }
    writeMask(tex); method = 'texture';
  } else {
    // 阶段二：smart 复用矩形 smartFill 的全部诊断参数
    const gray = new Uint8Array(rw * rh);
    for (let j = 0; j < rh; j++) for (let i = 0; i < rw; i++) {
      const k = ((y1 + j) * W + (x1 + i)) * 4;
      gray[j * rw + i] = Math.round(0.299 * data[k] + 0.587 * data[k + 1] + 0.114 * data[k + 2]);
    }
    let rad = Math.max(7, Math.min(15, (Math.min(rw, rh) / 6) | 1)); if (rad % 2 === 0) rad++;
    const bg = _medianBlur(gray, rw, rh, rad);
    const pos = [], neg = [];
    for (let i = 0; i < rw * rh; i++) { const d = gray[i] - bg[i]; if (d > 0) pos.push(d); else neg.push(-d); }
    const p97 = _pct(pos, 0.97), n97 = _pct(neg, 0.97);
    let src, th, polarity;
    if (p97 >= n97 && p97 > 12) { src = new Float32Array(rw * rh); for (let i = 0; i < rw * rh; i++) src[i] = gray[i] - bg[i]; th = Math.max(26, p97 * 0.42); polarity = 'light'; }
    else { src = new Float32Array(rw * rh); for (let i = 0; i < rw * rh; i++) src[i] = bg[i] - gray[i]; th = Math.max(26, n97 * 0.42); polarity = 'dark'; }
    let m = new Uint8Array(rw * rh);
    for (let i = 0; i < rw * rh; i++) m[i] = src[i] > th ? 1 : 0;
    m = _closeMask(m, rw, rh);
    let cov = 0; for (let i = 0; i < rw * rh; i++) cov += m[i]; cov /= rw * rh;
    // 掩码外的笔画全部丢弃，保证诊断只作用于多边形内部
    for (let i = 0; i < rw * rh; i++) if (!mask[i]) m[i] = 0;
    // 与矩形一致的分支条件：宽扁浅色水印或几乎无笔画 -> 整框插值；否则笔画级扩散
    if ((polyW / polyH >= 2.0 && polarity === 'light' && cov > 0.04) || cov < 0.004) {
      writeMask(_coons(rgb, rw, rh)); method = 'smooth';
    } else {
      const md = _morph(m, rw, rh, 'dilate');
      for (let i = 0; i < rw * rh; i++) if (!mask[i]) md[i] = 0;
      let mc = 0; for (let i = 0; i < rw * rh; i++) mc += md[i];
      if (mc < rw * rh * 0.004) { writeMask(_coons(rgb, rw, rh)); method = 'smooth'; }
      else {
        const filled = _diffuse(rgb, rw, rh, md, Math.max(iters, 150));
        // 阶段三折中：扩散结果只写回多边形内部，线条外一个字节都不动
        for (let j = 0; j < rh; j++) for (let i = 0; i < rw; i++) {
          const k = j * rw + i; if (!md[k]) continue;
          const d = ((y1 + j) * W + (x1 + i)) * 4, t = k * 3;
          data[d] = filled[t]; data[d + 1] = filled[t + 1]; data[d + 2] = filled[t + 2];
        }
        method = 'stroke';
      }
    }
  }
  // 把多边形 mask 随区域返回，sharpen 据此只增强线条内像素
  region.mask = mask; region.method = method;
  return region;
}

/**
 * 轻度锐化（unsharp mask）：只增强线条 mask 内像素，线条外逐字节不变。
 * 与 HTML 定稿版 sharpen(imgData,W,H,amount,touched) 对带 mask 区域的行为一致。
 */
function sharpenRegions(data, W, H, amount, regions) {
  if (!regions || !regions.length || !amount) return;
  const src = new Uint8ClampedArray(data);
  const allow = new Uint8Array(W * H);
  for (const r of regions) {
    for (let yy = Math.max(1, r.y); yy < Math.min(H - 1, r.y + r.h); yy++)
      for (let xx = Math.max(1, r.x); xx < Math.min(W - 1, r.x + r.w); xx++) {
        if (r.mask && !r.mask[(yy - r.y) * r.w + (xx - r.x)]) continue;
        allow[yy * W + xx] = 1;
      }
  }
  for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) {
    if (!allow[y * W + x]) continue;
    const i = (y * W + x) * 4;
    for (let c = 0; c < 3; c++) {
      const v = src[i + c];
      const n = (src[i - 4 + c] + src[i + 4 + c] + src[i - W * 4 + c] + src[i + W * 4 + c]) * 0.25;
      data[i + c] = v + (v - n) * amount;
    }
  }
}

/**
 * 高层入口：对一张图的所有线条执行去除（顺序与 HTML repair 一致：矩形先、线条后）。
 * @param {ImageData} imageData {width,height,data}
 * @param {Array} shapes 线条轨迹数组（显示坐标）
 * @param {String} mode smart/average/texture
 * @param {Number} iters 迭代次数
 * @param {Object} opts { scale, sourceData, getImageData, sharpen, sharpenAmount }
 */
function repairLines(imageData, shapes, mode, iters, opts) {
  opts = opts || {};
  const W = imageData.width, H = imageData.height, data = imageData.data;
  if (!shapes || !shapes.length) return [];
  const regions = [];
  shapes.forEach(function (shape) {
    const reg = lineRemove(data, W, H, shape, iters, mode, opts);
    if (reg) regions.push(reg);
  });
  if (opts.sharpen !== false && regions.length) {
    sharpenRegions(data, W, H, opts.sharpenAmount == null ? 0.25 : opts.sharpenAmount, regions);
  }
  return regions;
}

module.exports = {
  lineRemove, repairLines, sharpenRegions, getRegionData,
  _medianBlur, _pct, _morph, _closeMask, _coons, _diffuse
};
