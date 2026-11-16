/**
 * 净像小程序 · 图像修复算法（纯 JS）
 * 在 canvas 的 ImageData 上原地处理，支持 smart / average / texture 三种模式。
 * 所有参数由调用方传入，便于统一配置。
 */

/** 快速平均色填充 */
function averageFill(data, W, H, x, y, w, h, pad) {
  pad = pad || 3;
  x = Math.max(0, x); y = Math.max(0, y);
  w = Math.min(w, W - x); h = Math.min(h, H - y);
  if (w <= 0 || h <= 0) return;
  let r = 0, g = 0, b = 0, n = 0;
  const pick = (sx, sy) => {
    if (sx < 0 || sy < 0 || sx >= W || sy >= H) return;
    const i = (sy * W + sx) * 4;
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

/** 拉普拉斯扩散修复（核心，纯色/渐变背景近乎无痕） */
function laplaceFill(data, W, H, x, y, w, h, iters, pad) {
  pad = pad || 2;
  x = Math.max(0, x); y = Math.max(0, y);
  w = Math.min(w, W - x); h = Math.min(h, H - y);
  if (w <= 0 || h <= 0) return;
  const lw = w + pad * 2, lh = h + pad * 2, N = lw * lh;
  const R = new Float32Array(N), G = new Float32Array(N), B = new Float32Array(N);
  let br = 0, bg = 0, bb = 0, bn = 0;
  for (let j = 0; j < lh; j++) for (let i = 0; i < lw; i++) {
    let gx = Math.max(0, Math.min(W - 1, x - pad + i));
    let gy = Math.max(0, Math.min(H - 1, y - pad + j));
    const k = j * lw + i;
    const inner = i >= pad && i < lw - pad && j >= pad && j < lh - pad;
    if (!inner) {
      // 框贴图片边缘时 clamp 会采到框内的水印像素，镜像到最近的框外位置
      if (gx >= x && gx < x + w && gy >= y && gy < y + h) {
        const dl = gx - x + 1, dr = (x + w) - gx, dt = gy - y + 1, db = (y + h) - gy;
        const m = Math.min(dl, dr, dt, db);
        if (m === dl) gx = Math.max(0, x - 1);
        else if (m === dr) gx = Math.min(W - 1, x + w);
        else if (m === dt) gy = Math.max(0, y - 1);
        else gy = Math.min(H - 1, y + h);
      }
      const s = (gy * W + gx) * 4;
      R[k] = data[s]; G[k] = data[s + 1]; B[k] = data[s + 2];
      br += data[s]; bg += data[s + 1]; bb += data[s + 2]; bn++;
    }
  }
  br /= bn || 1; bg /= bn || 1; bb /= bn || 1;
  for (let j = pad; j < lh - pad; j++) for (let i = pad; i < lw - pad; i++) {
    const k = j * lw + i; R[k] = br; G[k] = bg; B[k] = bb;
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

/** 纹理平移 */
function textureFill(data, W, H, x, y, w, h) {
  x = Math.max(0, x); y = Math.max(0, y);
  w = Math.min(w, W - x); h = Math.min(h, H - y);
  if (w <= 0 || h <= 0) return;
  let sy = y - h - 4;
  if (sy < 0) sy = y + h + 4;
  sy = Math.max(0, Math.min(H - h, sy));
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
    const s = (j * w + i) * 4, d = ((y + j) * W + (x + i)) * 4;
    for (let c = 0; c < 3; c++) data[d + c] = data[((sy + j) * W + (x + i)) * 4 + c];
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
  rects.forEach(function (r) {
    if (mode === 'average') averageFill(data, W, H, r.x, r.y, r.w, r.h, 3);
    else if (mode === 'texture') textureFill(data, W, H, r.x, r.y, r.w, r.h);
    else laplaceFill(data, W, H, r.x, r.y, r.w, r.h, iters || 240, 2);
  });
  return imageData;
}

module.exports = { repair, laplaceFill, averageFill, textureFill };
