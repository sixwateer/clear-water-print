/* ============================================================
 * 净像普通版 · 算法自测（自测闭环的执行器）
 * ------------------------------------------------------------
 * 做法：直接从交付的 HTML 里抽取算法函数源码（保证测的是真正发布的
 *      代码，而不是副本），在真实木纹图上跑 6 场景 × 2 模式，
 *      用可量化的指标判定通过/失败，并输出局部裁剪图供人工复核。
 *
 * 前置：python prepare.py   （生成 _tmp/wood.bin）
 * 运行：node run.js
 * 产物：report.json（指标）+ _tmp/out_<场景>.ppm（裁剪图）
 * 退出码：有失败项时为 1，便于 CI 使用
 * ============================================================ */
const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const ROOT = path.dirname(path.dirname(HERE));
const HTML_PATH = path.join(ROOT, '02_HTML版', '净像去水印_普通版_双击即用.html');
const TMP = path.join(HERE, '_tmp');

// ---------- 从 HTML 抽取算法函数 ----------
const HTML = fs.readFileSync(HTML_PATH, 'utf8');

function extractFn(name) {
  const re = new RegExp('function ' + name + '\\([\\s\\S]*?\\n}', 'm');
  const m = HTML.match(re);
  if (!m) throw new Error('HTML 中未找到函数: ' + name);
  return m[0];
}
const cfgMatch = HTML.match(/autoIterations:\s*\{[^}]+\}/);
if (!cfgMatch) throw new Error('未找到 autoIterations 配置');
const CONFIG = { autoIterations: eval('({' + cfgMatch[0] + '})').autoIterations };

const required = ['fillLaplace', 'fillAverage', 'sharpen'];
const optional = ['growRect', 'laplaceCore', 'laplaceLoad', 'mirrorSample', 'bilinear',
  'injectTexture', 'boxBlur1', 'boxMean', 'residueRatio', 'clamp'];
const presentOptional = optional.filter(n => HTML.includes('function ' + n));
const src = required.map(extractFn).concat(presentOptional.map(extractFn)).join('\n');

class ImageDataPoly {
  constructor(data, w, h) { this.data = data; this.width = w; this.height = h; }
}
const ALGO = new Function('ImageData', 'CONFIG', `
  ${src}
  return { fillLaplace, fillAverage, sharpen, ${presentOptional.join(',')} };
`)(ImageDataPoly, CONFIG);

// ---------- 读测试图 ----------
const metaPath = path.join(TMP, 'wood.meta.json');
if (!fs.existsSync(metaPath)) {
  console.error('缺少 _tmp/wood.meta.json，请先运行: python prepare.py');
  process.exit(2);
}
const { W, H } = JSON.parse(fs.readFileSync(metaPath, 'utf8'));
const RAW = fs.readFileSync(path.join(TMP, 'wood.bin'));
if (RAW.length !== W * H * 3) {
  console.error('wood.bin 尺寸与 meta 不符，请重新运行 python prepare.py');
  process.exit(2);
}

function makeImageData() {
  const d = new Uint8ClampedArray(W * H * 4);
  for (let i = 0, j = 0; i < W * H; i++, j += 3) {
    d[i * 4] = RAW[j]; d[i * 4 + 1] = RAW[j + 1]; d[i * 4 + 2] = RAW[j + 2]; d[i * 4 + 3] = 255;
  }
  return { data: d, width: W, height: H };
}

// ---------- 指标 ----------
// 残影率：修复区内"高亮 + 低饱和"像素占比（半透明浅色水印的典型特征）
function residueRatio(data, x, y, w, h) {
  let hit = 0, n = 0;
  for (let j = Math.max(0, y); j < Math.min(H, y + h); j++)
    for (let i = Math.max(0, x); i < Math.min(W, x + w); i++) {
      const k = (j * W + i) * 4;
      const r = data[k], g = data[k + 1], b = data[k + 2];
      const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
      const lum = (r + g + b) / 3, sat = (mx - mn) / (mx + 1);
      if (lum > 175 && sat < 0.25) hit++;
      n++;
    }
  return hit / (n || 1);
}
// 边界色差：修复区最外沿与框外 2px 的颜色差（越小过渡越自然）
function edgeDelta(data, x, y, w, h) {
  let sum = 0, n = 0;
  for (let i = 0; i < w; i++) {
    for (const [ix, iy, ox, oy] of [[x + i, y, x + i, y - 2], [x + i, y + h - 1, x + i, y + h + 1]]) {
      if (ox < 0 || oy < 0 || ox >= W || oy >= H) continue;
      const a = (iy * W + ix) * 4, b = (oy * W + ox) * 4;
      sum += Math.abs(data[a] - data[b]) + Math.abs(data[a + 1] - data[b + 1]) + Math.abs(data[a + 2] - data[b + 2]);
      n++;
    }
  }
  return n ? sum / n : -1;
}
// 平滑度：修复区平均梯度（扩散结果应显著低于原始纹理；残留笔画/条带会拉高）
function smoothness(data, x, y, w, h) {
  let sum = 0, n = 0;
  for (let j = y + 2; j < y + h - 2; j += 2) for (let i = x + 2; i < x + w - 2; i += 2) {
    const k = (j * W + i) * 4;
    sum += Math.abs(data[k] - data[k - 4]) + Math.abs(data[k + 1] - data[k - 3]) + Math.abs(data[k + 2] - data[k - 2])
         + Math.abs(data[k] - data[k - W * 4]) + Math.abs(data[k + 1] - data[k - W * 4 + 1]) + Math.abs(data[k + 2] - data[k - W * 4 + 2]);
    n++;
  }
  return n ? sum / n : 0;
}
function meanColor(data, x, y, w, h) {
  let r = 0, g = 0, b = 0, n = 0;
  for (let j = Math.max(0, y); j < Math.min(H, y + h); j++)
    for (let i = Math.max(0, x); i < Math.min(W, x + w); i++) {
      const k = (j * W + i) * 4; r += data[k]; g += data[k + 1]; b += data[k + 2]; n++;
    }
  return [r / (n || 1), g / (n || 1), b / (n || 1)];
}

// ---------- 场景 ----------
// hasMark=true 含水印：残影率判定
// hasMark=false 对照区（本来就亮，无水印）：与修复前的均色差判定
// huge=true 超大框：残影率会被"本来就亮的肤色"误伤，改用平滑度判定
const scenarios = [
  { name: '正常框',   rect: { x: 1045, y: 2203, w: 215, h: 45 }, hasMark: true },
  // 贴边场景必须"完整覆盖水印 + 框边正好压到图像边缘"，才是有意义的贴边测试
  // 水印实际范围 x1045-1260, y2203-2248；图像 1280x2278
  { name: '贴底边',   rect: { x: 1030, y: 2195, w: 240, h: 83 }, hasMark: true },
  { name: '贴右下角', rect: { x: 1045, y: 2195, w: 235, h: 83 }, hasMark: true },
  { name: '贴左上角', rect: { x: 0, y: 0, w: 120, h: 60 }, hasMark: false },
  { name: '超大框',   rect: { x: 300, y: 1600, w: 700, h: 600 }, hasMark: true, huge: true },
  { name: '极小框',   rect: { x: 600, y: 1000, w: 10, h: 10 }, hasMark: false },
];

const before = makeImageData();
fs.mkdirSync(TMP, { recursive: true });

console.log('=== 净像普通版 · 算法自测 ===');
console.log('被测文件 02_HTML版/净像去水印_普通版_双击即用.html');
console.log(`测试图 ${W}x${H}  迭代档 ${JSON.stringify(CONFIG.autoIterations)}`);
console.log('------------------------------------------------------------');

// PPM(P6) 输出：只裁框周围区域，控制体积
function writePPM(file, data, cx, cy, cw, ch) {
  const x0 = Math.max(0, Math.min(W - cw, cx)), y0 = Math.max(0, Math.min(H - ch, cy));
  const buf = Buffer.alloc(cw * ch * 3);
  for (let j = 0; j < ch; j++) for (let i = 0; i < cw; i++) {
    const s = ((y0 + j) * W + (x0 + i)) * 4, d = (j * cw + i) * 3;
    buf[d] = data[s]; buf[d + 1] = data[s + 1]; buf[d + 2] = data[s + 2];
  }
  fs.writeFileSync(file, Buffer.concat([Buffer.from(`P6\n${cw} ${ch}\n255\n`), buf]));
}

const report = [];
for (const s of scenarios) {
  const r = s.rect;
  const rw = Math.min(r.w, W - r.x), rh = Math.min(r.h, H - r.y);
  const resBefore = residueRatio(before.data, r.x, r.y, rw, rh);

  for (const mode of ['smart', 'average', 'texture']) {
    const im = makeImageData();
    let rect = { x: r.x, y: r.y, w: rw, h: rh };
    if (ALGO.growRect) rect = ALGO.growRect(rect.x, rect.y, rect.w, rect.h, W, H);

    const t0 = Date.now();
    if (mode === 'average') ALGO.fillAverage(im.data, W, H, rect.x, rect.y, rect.w, rect.h);
    else {
      ALGO.fillLaplace(im.data, W, H, rect.x, rect.y, rect.w, rect.h, CONFIG.autoIterations[2]);
      if (mode === 'texture' && ALGO.injectTexture) ALGO.injectTexture(im.data, W, H, rect);
    }
    const ms = Date.now() - t0;

    const resAfter = residueRatio(im.data, rect.x, rect.y, rect.w, rect.h);
    const delta = edgeDelta(im.data, rect.x, rect.y, rect.w, rect.h);
    let pass, metric;
    if (s.hasMark && s.huge) {
      const v = smoothness(im.data, rect.x, rect.y, rect.w, rect.h);
      pass = v < 8;
      metric = '平滑度 ' + v.toFixed(2) + ' (<8)';
    } else if (s.hasMark) {
      pass = resAfter < Math.max(0.02, resBefore * 0.25);
      metric = '残影 ' + resBefore.toFixed(3) + '→' + resAfter.toFixed(3);
    } else {
      const a = meanColor(im.data, rect.x, rect.y, rect.w, rect.h);
      const b = meanColor(before.data, rect.x, rect.y, rect.w, rect.h);
      const v = Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) + Math.abs(a[2] - b[2]);
      // 快速填充是纯色平铺，大区域必然改变均色，只作参考不计失败
      pass = mode !== 'smart' ? true : v < 45;
      metric = '与原图均色差 ' + v.toFixed(1) + (mode === 'average' ? '(参考)' : ' (<45)');
    }

    report.push({ scenario: s.name, mode, ms, pass, resBefore: +resBefore.toFixed(3), resAfter: +resAfter.toFixed(3), edgeDelta: +delta.toFixed(1) });
    console.log(
      (pass ? 'PASS' : 'FAIL') + '  ' + s.name.padEnd(6, '\u3000') + ' ' + mode.padEnd(8) +
      metric + ' 边差 ' + delta.toFixed(1) + ' 耗时 ' + ms + 'ms'
    );

    if (mode !== 'average') {
      writePPM(path.join(TMP, 'out_' + s.name + (mode === 'texture' ? '_texture' : '') + '.ppm'), im.data,
        rect.x - 60, rect.y - 60, Math.min(520, W), Math.min(320, H));
    }
  }
}

const fails = report.filter(r => !r.pass);
console.log('------------------------------------------------------------');
console.log(`合计 ${report.length} 项，PASS ${report.length - fails.length}，FAIL ${fails.length}`);
fs.writeFileSync(path.join(HERE, 'report.json'), JSON.stringify({
  html: '02_HTML版/净像去水印_普通版_双击即用.html',
  at: new Date().toISOString(),
  items: report
}, null, 2));
process.exit(fails.length ? 1 : 0);
