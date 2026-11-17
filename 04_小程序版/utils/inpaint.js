/**
 * 净像小程序 · 图像修复算法（纯 JS）
 * 在 canvas 的 ImageData 上原地处理，支持 smart / average / texture 三种模式。
 * 所有参数由调用方传入，便于统一配置。
 */

/** 快速平均色填充（贴边时镜像采样，避免采到框内水印色） */
function averageFill(data, W, H, x, y, w, h, pad) {
  pad = pad || 3;
  x = Math.max(0, x); y = Math.max(0, y);
  w = Math.min(w, W - x); h = Math.min(h, H - y);
  if (w <= 0 || h <= 0) return;
  let r = 0, g = 0, b = 0, n = 0;
  const pick = (sx, sy) => {
    // clamp 后若落在框内，镜像到最近的框外
    let gx = Math.max(0, Math.min(W - 1, sx));
    let gy = Math.max(0, Math.min(H - 1, sy));
    if (gx >= x && gx < x + w && gy >= y && gy < y + h) {
      const dl = gx - x + 1, dr = (x + w) - gx, dt = gy - y + 1, db = (y + h) - gy;
      const m = Math.min(dl, dr, dt, db);
      if (m === dl) gx = x - 1;
      else if (m === dr) gx = x + w;
      else if (m === dt) gy = y - 1;
      else gy = y + h;
    }
    if (gx < 0 || gx >= W || gy < 0 || gy >= H) return;
    if (gx >= x && gx < x + w && gy >= y && gy < y + h) return; // 该方向无背景，跳过
    const i = (gy * W + gx) * 4;
    r += data[i]; g += data[i + 1]; b += data[i + 2]; n++;
  };
  for (let i = -pad; i < w + pad; i++) { pick(x + i, y - pad); pick(x + i, y + h + pad - 1); }
  for (let j = -pad; j < h + pad; j++) { pick(x - pad, y + j); pick(x + w + pad - 1, y + j); }
  r /= n || 1; g /= n || 1; b /= n || 1;
  for (let yy = y; yy < y + h; yy++) for (let xx = x; xx < x + w; xx++) {
    const i = (yy * W + xx) * 4;
    data[i] = r; data[i + 1] = g; data[i + 2] = b;
  }
}

/**
 * 拉普拉斯扩散修复（核心）。
 * 小框直接原尺寸求解；大框先降采样到小图扩散、再双线性放大写回——
 * 扩散结果是平滑函数，降采样几乎无损，但速度提升数十倍，且保证迭代
 * 能扩散到框中心（原尺寸大框中心距边界可能超过迭代次数，留下中心残痕）。
 */
function laplaceFill(data, W, H, x, y, w, h, iters, pad) {
  pad = pad || 2;
  x = Math.max(0, x); y = Math.max(0, y);
  w = Math.min(w, W - x); h = Math.min(h, H - y);
  if (w <= 0 || h <= 0) return;
  const MAXDIM = 240; // 超过该边长走多尺度
  const scale = Math.min(1, MAXDIM / Math.max(w, h));
  if (scale >= 1) {
    _laplaceRaw(data, W, H, x, y, w, h, iters, pad);
  } else {
    _laplaceScaled(data, W, H, x, y, w, h, iters, pad, scale);
  }
}

/** 原尺寸拉普拉斯扩散（小框直接用，质量最高） */
function _laplaceRaw(data, W, H, x, y, w, h, iters, pad) {
  const lw = w + pad * 2, lh = h + pad * 2, N = lw * lh;
  const R = new Float32Array(N), G = new Float32Array(N), B = new Float32Array(N);
  const valid = new Uint8Array(N); // 边界采样点是否落在框外的有效背景上
  let br = 0, bg = 0, bb = 0, bn = 0;
  for (let j = 0; j < lh; j++) for (let i = 0; i < lw; i++) {
    const k = j * lw + i;
    const inner = i >= pad && i < lw - pad && j >= pad && j < lh - pad;
    if (!inner) {
      let gx = Math.max(0, Math.min(W - 1, x - pad + i));
      let gy = Math.max(0, Math.min(H - 1, y - pad + j));
      // clamp 会采到框内的水印像素，镜像到最近的框外位置
      if (gx >= x && gx < x + w && gy >= y && gy < y + h) {
        const dl = gx - x + 1, dr = (x + w) - gx, dt = gy - y + 1, db = (y + h) - gy;
        const m = Math.min(dl, dr, dt, db);
        if (m === dl) gx = x - 1;
        else if (m === dr) gx = x + w;
        else if (m === dt) gy = y - 1;
        else gy = y + h;
      }
      // 镜像后若仍落在框内或越出图像（框贴边/贴角），说明该方向没有背景可采样，标记为无效
      if (gx < 0 || gx >= W || gy < 0 || gy >= H || (gx >= x && gx < x + w && gy >= y && gy < y + h)) {
        valid[k] = 0;
      } else {
        const s = (gy * W + gx) * 4;
        R[k] = data[s]; G[k] = data[s + 1]; B[k] = data[s + 2];
        br += data[s]; bg += data[s + 1]; bb += data[s + 2]; bn++;
        valid[k] = 1;
      }
    }
  }
  if (bn === 0) { br = data[0]; bg = data[1]; bb = data[2]; } // 极端：整图皆框，用角落色兜底
  else { br /= bn; bg /= bn; bb /= bn; }
  // 内部点与无效边界点统一初始化为边缘均色，避免无效点以 0（黑色）参与扩散导致修复区发暗
  for (let k = 0; k < N; k++) {
    if (!valid[k]) { R[k] = br; G[k] = bg; B[k] = bb; }
  }
  for (let it = 0; it < iters; it++) {
    for (let j = pad; j < lh - pad; j++) {
      const row = j * lw;
      for (let i = pad; i < lw - pad; i++) {
        const k = row + i;
        R[k] = (R[k - 1] + R[k + 1] + R[k - lw] + R[k + lw]) * 0.25;
        G[k] = (G[k - 1] + G[k + 1] + G[k - lw] + G[k + lw]) * 0.25;
        B[k] = (B[k - 1] + B[k + 1] + B[k - lw] + B[k + lw]) * 0.25;
      }
    }
  }
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
    const k = (j + pad) * lw + (i + pad), d = ((y + j) * W + (x + i)) * 4;
    data[d] = R[k]; data[d + 1] = G[k]; data[d + 2] = B[k];
  }
}

/** 多尺度拉普拉斯扩散（大框）：降采样扩散 + 双线性放大写回 */
function _laplaceScaled(data, W, H, x, y, w, h, iters, pad, scale) {
  const spad = Math.max(2, Math.round(pad * scale));
  const sw = Math.max(2, Math.round(w * scale)), sh = Math.max(2, Math.round(h * scale));
  const slw = sw + spad * 2, slh = sh + spad * 2, N = slw * slh;
  const R = new Float32Array(N), G = new Float32Array(N), B = new Float32Array(N);
  const valid = new Uint8Array(N);
  let br = 0, bg = 0, bb = 0, bn = 0;
  // 小图坐标 (si,sj) 映射到原图全局坐标，构建边界条件（逻辑同 _laplaceRaw）
  for (let sj = 0; sj < slh; sj++) for (let si = 0; si < slw; si++) {
    const k = sj * slw + si;
    const inner = si >= spad && si < slw - spad && sj >= spad && sj < slh - spad;
    if (inner) continue;
    let gx = Math.max(0, Math.min(W - 1, Math.round(x + (si - spad) / scale)));
    let gy = Math.max(0, Math.min(H - 1, Math.round(y + (sj - spad) / scale)));
    if (gx >= x && gx < x + w && gy >= y && gy < y + h) {
      const dl = gx - x + 1, dr = (x + w) - gx, dt = gy - y + 1, db = (y + h) - gy;
      const m = Math.min(dl, dr, dt, db);
      if (m === dl) gx = x - 1;
      else if (m === dr) gx = x + w;
      else if (m === dt) gy = y - 1;
      else gy = y + h;
    }
    if (gx < 0 || gx >= W || gy < 0 || gy >= H || (gx >= x && gx < x + w && gy >= y && gy < y + h)) {
      valid[k] = 0;
    } else {
      const s = (gy * W + gx) * 4;
      R[k] = data[s]; G[k] = data[s + 1]; B[k] = data[s + 2];
      br += data[s]; bg += data[s + 1]; bb += data[s + 2]; bn++;
      valid[k] = 1;
    }
  }
  if (bn === 0) { br = data[0]; bg = data[1]; bb = data[2]; }
  else { br /= bn; bg /= bn; bb /= bn; }
  for (let k = 0; k < N; k++) { if (!valid[k]) { R[k] = br; G[k] = bg; B[k] = bb; } }
  // 迭代次数保证覆盖小图中心到边界的距离
  const needIters = Math.max(iters, Math.ceil(Math.max(slw, slh) / 2));
  for (let it = 0; it < needIters; it++) {
    for (let j = spad; j < slh - spad; j++) {
      const row = j * slw;
      for (let i = spad; i < slw - spad; i++) {
        const k = row + i;
        R[k] = (R[k - 1] + R[k + 1] + R[k - slw] + R[k + slw]) * 0.25;
        G[k] = (G[k - 1] + G[k + 1] + G[k - slw] + G[k + slw]) * 0.25;
        B[k] = (B[k - 1] + B[k + 1] + B[k - slw] + B[k + slw]) * 0.25;
      }
    }
  }
  // 双线性放大写回原图框
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
    const sf = i * scale + spad, tf = j * scale + spad;
    const i0 = Math.floor(sf), j0 = Math.floor(tf);
    const fx = sf - i0, fy = tf - j0;
    const i1 = Math.min(i0 + 1, slw - 1), j1 = Math.min(j0 + 1, slh - 1);
    const k00 = j0 * slw + i0, k10 = j0 * slw + i1, k01 = j1 * slw + i0, k11 = j1 * slw + i1;
    const w00 = (1 - fx) * (1 - fy), w10 = fx * (1 - fy), w01 = (1 - fx) * fy, w11 = fx * fy;
    const d = ((y + j) * W + (x + i)) * 4;
    data[d] = R[k00] * w00 + R[k10] * w10 + R[k01] * w01 + R[k11] * w11;
    data[d + 1] = G[k00] * w00 + G[k10] * w10 + G[k01] * w01 + G[k11] * w11;
    data[d + 2] = B[k00] * w00 + B[k10] * w10 + B[k01] * w01 + B[k11] * w11;
  }
}

/**
 * 对 ImageData 应用修复
 * @param {ImageData} imageData
 * @param {Array} rects 原图像素坐标框 [{x,y,w,h}]
 * @param {String} mode smart/average/texture
 * @param {Number} iters 迭代次数
 */
function repair(imageData, rects, mode, iters) {
  const data = imageData.data, W = imageData.width, H = imageData.height;
  const nIters = iters || 240;
  rects.forEach(function (r) {
    // 自动外扩修复框：水印的抗锯齿边缘与投影阴影通常落在用户框外一圈，
    // 不覆盖会在修复区边界留下白边/残影。外扩量按框尺寸自适应（3~12px）。
    const grow = Math.max(3, Math.min(12, Math.round(Math.min(r.w, r.h) * 0.18)));
    const x1 = Math.max(0, r.x - grow), y1 = Math.max(0, r.y - grow);
    const x2 = Math.min(W, r.x + r.w + grow), y2 = Math.min(H, r.y + r.h + grow);
    const w = x2 - x1, h = y2 - y1;
    if (w <= 0 || h <= 0) return;
    if (mode === 'average') {
      averageFill(data, W, H, x1, y1, w, h, 3);
    } else {
      // texture 与 smart 统一走整框拉普拉斯扩散（等价于传统 inpainting 扩散）：
      // 从边界向内平滑重建，能彻底去除文字、不留残影，纯色/渐变/纹理背景均适用。
      // 老的"纹理平移"在木纹等斜向纹理上会留下明显矩形接缝，已废弃。
      laplaceFill(data, W, H, x1, y1, w, h, nIters, 2);
    }
  });
  return imageData;
}

module.exports = { repair, laplaceFill, averageFill };
