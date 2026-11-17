/**
 * 普通版 naturalFill 在新图上的真实像素测试
 * node test_natural_fill.js
 */
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '../..');
const HTML = path.join(ROOT, '02_HTML版/净像去水印_普通版_双击即用.html');
const PIX = path.join(__dirname, '_tmp/blue_pixels.json');

const html = fs.readFileSync(HTML, 'utf8');
const code = html.match(/<script>([\s\S]*?)<\/script>/)[1]
  + '\n;globalThis.__naturalFill=naturalFill;';
// 最小 DOM mock（只让脚本能加载，测试直接用像素数组）
function el() {
  return {
    style: {}, dataset: {}, value: '', textContent: '', innerHTML: '', checked: false,
    width: 720, height: 400,
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, getContext() { return new Proxy({}, { get: () => () => {} }); },
    getBoundingClientRect() { return { left: 0, top: 0, width: 720, height: 400 }; },
    click() {}, scrollIntoView() {}
  };
}
const els = {};
const sandbox = {
  document: {
    getElementById(id) { return els[id] || (els[id] = el()); },
    querySelector() { return null; }, querySelectorAll() { return []; },
    createElement() { return el(); }, addEventListener() {}
  },
  window: { addEventListener() {}, scrollTo() {} },
  console: { log() {}, warn() {}, error() {} },
  setTimeout, clearTimeout, Math, Date, JSON, Object, Array, String, Number, Boolean,
  RegExp, Error, Uint8Array, Uint8ClampedArray, Float32Array, Uint32Array,
  parseInt, parseFloat, isNaN,
  AbortSignal: { timeout() { return {}; } },
  URL: { createObjectURL() { return 'blob:x'; } },
  Image: class {}, FileReader: class {}, FormData: class { append() {} },
  fetch: async () => ({ ok: true, json: async () => ({}), blob: async () => ({}) })
};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);

const pic = JSON.parse(fs.readFileSync(PIX, 'utf8'));
const W = pic.w, H = pic.h;
const before = Uint8ClampedArray.from(pic.data);

let pass = 0, fail = 0;
function test(name, box) {
  const data = Uint8ClampedArray.from(before);
  const [x, y, w, h] = box;
  sandbox.__naturalFill(data, W, H, x, y, w, h, 200);

  // 框外逐字节不变
  let outsideOK = true;
  for (let yy = 0; yy < H; yy += 7) for (let xx = 0; xx < W; xx += 7) {
    if (xx >= x && xx < x + w && yy >= y && yy < y + h) continue;
    const k = (yy * W + xx) * 4;
    for (let c = 0; c < 3; c++) if (data[k + c] !== before[k + c]) { outsideOK = false; break; }
    if (!outsideOK) break;
  }
  // 框内有变化
  let changed = 0, total = 0;
  for (let yy = y; yy < y + h; yy += 2) for (let xx = x; xx < x + w; xx += 2) {
    const k = (yy * W + xx) * 4; total++;
    if (Math.abs(data[k] - before[k]) + Math.abs(data[k + 1] - before[k + 1]) + Math.abs(data[k + 2] - before[k + 2]) > 12) changed++;
  }
  const ratio = changed / Math.max(1, total);
  // 笔画级修复只改笔画像素（可能覆盖框内大部分），整框替换接近 100%。
  // 关键断言是"框外不变 + 框内确实被处理"，而非具体比例。
  const ok = outsideOK && ratio > 0.04;
  console.log((ok ? 'PASS  ' : 'FAIL  ') + name
    + '  框外不变=' + outsideOK + ' 框内变化率=' + (ratio * 100).toFixed(1) + '%');
  ok ? pass++ : fail++;
  return data;
}

const cases = [
  ['左上招牌文字', [90, 8, 160, 82]],
  ['鲸鱼礼物盒 JJ', [355, 310, 135, 85]],
  ['左下 JJ 立牌', [185, 425, 95, 105]],
  ['柜台圆形 JJ', [475, 490, 95, 69]],
  ['帆布袋 JJ（纹理背景）', [740, 420, 130, 125]],
  ['帽子标志', [260, 95, 95, 65]]
];
const results = cases.map(([n, b]) => ({ n, b, data: test(n, b) }));

// 保存合成结果供肉眼检查
const out = Uint8ClampedArray.from(before);
for (const r of results) {
  const [x, y, w, h] = r.b;
  for (let yy = y; yy < y + h; yy++) for (let xx = x; xx < x + w; xx++) {
    const k = (yy * W + xx) * 4;
    out[k] = r.data[k]; out[k + 1] = r.data[k + 1]; out[k + 2] = r.data[k + 2];
  }
}
fs.writeFileSync(path.join(__dirname, '_tmp/nf_result.json'), JSON.stringify({ w: W, h: H, data: Array.from(out) }));
console.log('\n合计 ' + (pass + fail) + ' 项，PASS ' + pass + '，FAIL ' + fail);
process.exit(fail ? 1 : 0);
