/**
 * 小程序「线条去除」与权威 HTML 一致性 / 交互回归测试
 *   node tests/test_line_inpaint.js
 *
 * 权威基准：当前 HTML 定稿版（用户指定的 11:06 版本，MD5 6e65579c...）
 * 覆盖：
 *   1) 小程序 lineInpaint.lineRemove 与 HTML lineRemove 逐像素一致（3 形状 × 3 模式 × 2 迭代）
 *   2) 线条外像素逐字节不变（含锐化），线条内确实被修复，三模式输出不同
 *   3) ROI 外扩 / 最小尺寸 / 退化图形等边界
 *   4) 页面交互：工具切换、画线条、线随框缩放、整体移动、撤销、清除、下一页
 */
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const LI = require('../utils/lineInpaint.js');

const HTML = 'C:/Users/16044/Documents/xwechat_files/wxid_61an2vkkekea22_f358/msg/file/2026-11/净像去水印_普通版_双击即用(2).html';

let pass = 0, fail = 0;
function check(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '  ->  ' + e.message); fail++; }
}
function mkData(W, H, seed) {
  const d = new Uint8ClampedArray(W * H * 4);
  for (let i = 0; i < d.length; i++) d[i] = (i * 37 + seed * 13 + 11) % 256;
  return d;
}
function polyIn(p, po) {
  let v = false;
  for (let i = 0, j = po.length - 1; i < po.length; j = i++) {
    const a = po[i], b = po[j];
    if (((a.y > p.y) !== (b.y > p.y)) && (p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x)) v = !v;
  }
  return v;
}

// ---------- HTML 沙箱（仅在权威文件存在时做一致性比对）----------
const noop = function () {};
function ctxMock(orig, W, H) {
  return new Proxy({}, {
    get(t, p) {
      if (p in t) return t[p];
      if (p === 'getImageData') return (sx, sy, rw, rh) => {
        const d = new Uint8ClampedArray(rw * rh * 4);
        for (let j = 0; j < rh; j++) for (let i = 0; i < rw; i++) {
          const s = ((sy + j) * W + (sx + i)) * 4, q = (j * rw + i) * 4;
          d[q] = orig[s]; d[q + 1] = orig[s + 1]; d[q + 2] = orig[s + 2]; d[q + 3] = orig[s + 3];
        }
        return { data: d };
      };
      if (p === 'createLinearGradient') return () => ({ addColorStop: noop });
      if (p === 'measureText') return () => ({ width: 20 });
      if (p === 'canvas') return { width: W, height: H };
      return noop;
    },
    set(t, p, v) { t[p] = v; return true; }
  });
}
function htmlSandbox() {
  if (!fs.existsSync(HTML)) return null;
  const src = fs.readFileSync(HTML, 'utf8');
  const m = src.match(/<script>([\s\S]*?)<\/script>/);
  if (!m || !/function lineRemove/.test(m[1])) return null;
  function el() {
    const o = {
      width: 760, height: 500, value: '', textContent: '', disabled: false, checked: false,
      style: {}, dataset: {},
      classList: { add: noop, remove: noop, toggle: noop, contains: () => false },
      getContext: () => ctxMock(new Uint8ClampedArray(760 * 500 * 4), 760, 500),
      addEventListener: noop, toDataURL: () => 'data:,',
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 760, height: 500 })
    };
    return new Proxy(o, { get(t, p) { if (p in t) return t[p]; return noop; }, set(t, p, v) { t[p] = v; return true; } });
  }
  const sb = {
    document: { getElementById: el, querySelector: el, querySelectorAll: () => [], createElement: el, addEventListener: noop },
    window: { addEventListener: noop, scrollTo: noop }, performance: { now: () => 0 },
    ImageData: class { constructor(d, w, h) { this.data = d; this.width = w; this.height = h; } },
    Image: class { set src(v) { if (this.onload) this.onload(); } },
    setTimeout: setTimeout, console
  };
  vm.createContext(sb);
  vm.runInContext(m[1] + '\n;globalThis.__S=S;globalThis.__LR=lineRemove;', sb);
  sb.__S.scale = 1;
  return sb;
}

const SHAPES = [
  [{ x: 25, y: 25 }, { x: 55, y: 25 }, { x: 55, y: 55 }, { x: 25, y: 55 }],
  [{ x: 15, y: 15 }, { x: 45, y: 18 }, { x: 48, y: 42 }, { x: 26, y: 46 }, { x: 12, y: 30 }],
  [{ x: 20, y: 30 }, { x: 60, y: 28 }, { x: 62, y: 38 }, { x: 20, y: 40 }]
];
const MODES = ['smart', 'average', 'texture'];
const W = 80, H = 80;

// ---------- 1) 与 HTML 逐像素一致 ----------
const sb = htmlSandbox();
if (!sb) {
  console.log('SKIP  与 HTML 逐像素一致（权威文件不可用）');
} else {
  let n = 0;
  for (const shape of SHAPES) for (const mode of MODES) for (const iters of [1, 320]) {
    const tag = mode + ' shape#' + SHAPES.indexOf(shape) + ' iters=' + iters;
    check('与 HTML 逐像素一致 ' + tag, function () {
      const orig = mkData(W, H, n++);
      const a = new Uint8ClampedArray(orig), b = new Uint8ClampedArray(orig);
      const ra = sb.__LR(a, W, H, shape, iters, mode, ctxMock(orig, W, H));
      const rb = LI.lineRemove(b, W, H, shape, iters, mode, { scale: 1, sourceData: orig });
      for (let i = 0; i < a.length; i++) assert.strictEqual(a[i], b[i], '第 ' + i + ' 字节不同');
      assert.ok(!!ra === !!rb);
      if (ra) {
        assert.strictEqual(ra.x, rb.x); assert.strictEqual(ra.y, rb.y);
        assert.strictEqual(ra.w, rb.w); assert.strictEqual(ra.h, rb.h);
        assert.strictEqual(ra.method, rb.method);
      }
    });
  }
}

// ---------- 2) 像素安全与模式差异 ----------
for (const mode of MODES) {
  check('线条外像素逐字节不变（' + mode + '，含锐化）', function () {
    const orig = mkData(W, H, 3), data = new Uint8ClampedArray(orig);
    const shape = SHAPES[1];
    const img = { width: W, height: H, data: data };
    const regs = LI.repairLines(img, [shape], mode, 320, { scale: 1, sourceData: orig, sharpenAmount: 0.25 });
    assert.ok(regs.length === 1);
    let outsideSame = true, insideChanged = 0;
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const i = (y * W + x) * 4;
      const inside = polyIn({ x: x + 0.5, y: y + 0.5 }, shape);
      const same = data[i] === orig[i] && data[i + 1] === orig[i + 1] && data[i + 2] === orig[i + 2];
      if (!inside && !same) outsideSame = false;
      if (inside && !same) insideChanged++;
    }
    assert.ok(outsideSame, '线条外不应有任何字节变化');
    assert.ok(insideChanged > 0, '线条内应被修复');
  });
}
check('三模式输出确实不同', function () {
  const outs = {};
  for (const mode of MODES) {
    const orig = mkData(W, H, 7), data = new Uint8ClampedArray(orig);
    LI.repairLines({ width: W, height: H, data: data }, [SHAPES[0]], mode, 320,
      { scale: 1, sourceData: orig, sharpen: false });
    outs[mode] = data;
  }
  let diff12 = 0, diff13 = 0;
  for (let i = 0; i < outs.smart.length; i++) {
    if (outs.smart[i] !== outs.average[i]) diff12++;
    if (outs.smart[i] !== outs.texture[i]) diff13++;
  }
  assert.ok(diff12 > 0 && diff13 > 0, '模式切换应改变输出');
});

// ---------- 3) 边界 ----------
check('最小尺寸：过小线条被拒绝', function () {
  const d = mkData(W, H, 1);
  assert.strictEqual(LI.lineRemove(d, W, H,
    [{ x: 10, y: 10 }, { x: 15, y: 10 }, { x: 15, y: 15 }], 320, 'smart', { scale: 1 }), null);
});
check('ROI 外扩 28%/min8 与矩形一致', function () {
  const d = mkData(W, H, 2);
  const reg = LI.lineRemove(d, W, H, SHAPES[0], 320, 'smart', { scale: 1 });
  // 30px 边 → exp=max(8, round(30*0.28)=8)=8 → 25-8=17, 55+8=63
  assert.strictEqual(reg.x, 17); assert.strictEqual(reg.y, 17);
  assert.strictEqual(reg.w, 46); assert.strictEqual(reg.h, 46);
});
check('贴边多边形不越界', function () {
  const d = mkData(W, H, 4);
  const reg = LI.lineRemove(d, W, H,
    [{ x: 0, y: 0 }, { x: 40, y: 0 }, { x: 40, y: 40 }, { x: 0, y: 40 }], 320, 'smart', { scale: 1 });
  assert.ok(reg && reg.x >= 0 && reg.y >= 0 && reg.x + reg.w <= W && reg.y + reg.h <= H);
});

// ---------- 4) 页面交互 ----------
function loadPage(wxMock, appMock) {
  let cfg = null;
  global.Page = function (c) { cfg = c; };
  global.getApp = function () { return appMock; };
  global.wx = wxMock;
  delete require.cache[require.resolve('../pages/index/index.js')];
  require('../pages/index/index.js');
  const c = Object.assign({}, cfg);
  c.data = JSON.parse(JSON.stringify(cfg.data));
  c.setData = function (o, cb) { Object.assign(this.data, o); if (typeof cb === 'function') cb(); };
  c.onLoad();
  return c;
}
function baseWx() {
  return {
    showToast: noop, showLoading: noop, hideLoading: noop,
    createSelectorQuery: function () {
      return { in: function () { return this; }, select: function () { return this; },
        fields: function () { return this; }, exec: function () {} };
    }
  };
}
const appMock = { globalData: { compliance: '', algo: { smartIterations: 40 }, version: '1.1.0' } };

check('页面：工具切换与状态隔离', function () {
  const c = loadPage(baseWx(), appMock);
  c.data.hasImage = true; c.data.displayW = 200; c.data.displayH = 200;
  c.setTool({ currentTarget: { dataset: { key: 'line' } } });
  assert.strictEqual(c.data.tool, 'line');
  assert.ok(/线条/.test(c.data.toolHint));
  c.setTool({ currentTarget: { dataset: { key: 'rect' } } });
  assert.strictEqual(c.data.tool, 'rect');
});
check('页面：画线条（≥3 点成环并选中）', function () {
  const c = loadPage(baseWx(), appMock);
  c.data.hasImage = true; c.data.displayW = 200; c.data.displayH = 200; c._rect = { left: 0, top: 0 };
  c.data.tool = 'line';
  c.onTouchStart({ touches: [{ x: 40, y: 40 }] });
  assert.strictEqual(c._action, 'drawLine');
  c.onTouchMove({ touches: [{ x: 100, y: 42 }] });
  c.onTouchMove({ touches: [{ x: 100, y: 100 }] });
  c.onTouchMove({ touches: [{ x: 40, y: 100 }] });
  c.onTouchEnd({ changedTouches: [{ x: 40, y: 100 }] });
  assert.strictEqual(c.data.shapes.length, 1);
  assert.ok(c.data.shapes[0].length >= 3);
  assert.strictEqual(c.data.sel.kind, 'line');
});
check('页面：线随框缩放（手柄等比映射）', function () {
  const c = loadPage(baseWx(), appMock);
  c.data.hasImage = true; c.data.displayW = 760; c.data.displayH = 500; c._rect = { left: 0, top: 0 };
  c.data.tool = 'line';
  c.data.shapes = [[{ x: 300, y: 200 }, { x: 400, y: 200 }, { x: 400, y: 300 }, { x: 300, y: 300 }]];
  c.data.sel = { kind: 'line', index: 0 };
  c.onTouchStart({ touches: [{ x: 400, y: 300 }] });   // se 手柄
  assert.strictEqual(c._action, 'resizeLine');
  c.onTouchMove({ touches: [{ x: 500, y: 400 }] });
  c.onTouchEnd({ changedTouches: [{ x: 500, y: 400 }] });
  const b = c._shapeBox(c.data.shapes[0]);
  assert.ok(Math.abs(b.w - 200) < 0.01, '宽度应放大到 200，实际 ' + b.w);
  assert.ok(Math.abs(b.h - 200) < 0.01, '高度应放大到 200，实际 ' + b.h);
  assert.ok(Math.abs(b.x - 300) < 0.01 && Math.abs(b.y - 200) < 0.01, '左上角应固定');
});
check('页面：线条整体移动（点同步）', function () {
  const c = loadPage(baseWx(), appMock);
  c.data.hasImage = true; c.data.displayW = 760; c.data.displayH = 500; c._rect = { left: 0, top: 0 };
  c.data.tool = 'line';
  c.data.shapes = [[{ x: 300, y: 200 }, { x: 400, y: 200 }, { x: 400, y: 300 }, { x: 300, y: 300 }]];
  c.data.sel = { kind: 'line', index: 0 };
  c.onTouchStart({ touches: [{ x: 350, y: 250 }] });
  assert.strictEqual(c._action, 'moveLine');
  c.onTouchMove({ touches: [{ x: 370, y: 290 }] });
  c.onTouchEnd({ changedTouches: [{ x: 370, y: 290 }] });
  const b = c._shapeBox(c.data.shapes[0]);
  assert.ok(Math.abs(b.x - 320) < 0.01 && Math.abs(b.y - 240) < 0.01);
});
check('页面：撤销 / 清除 / 下一页', function () {
  const c = loadPage(baseWx(), appMock);
  c.data.hasImage = true; c.data.displayW = 200; c.data.displayH = 200;
  c.data.shapes = [[{ x: 10, y: 10 }, { x: 50, y: 10 }, { x: 50, y: 50 }]];
  c.data.sel = { kind: 'line', index: 0 };
  c.undoMark();
  assert.strictEqual(c.data.shapes.length, 0);
  assert.strictEqual(c.data.sel, null);
  c.data.box = { x: 10, y: 10, w: 30, h: 30 };
  c.clearBox();
  assert.strictEqual(c.data.box, null);
  assert.strictEqual(c.data.shapes.length, 0);
  c.nextPage();
  assert.strictEqual(c.data.hasImage, false);
});
check('页面：仅画线条也能进入修复流程', function () {
  const c = loadPage(baseWx(), appMock);
  c.data.box = null;
  c.data.shapes = [[{ x: 10, y: 10 }, { x: 50, y: 10 }, { x: 50, y: 50 }]];
  let processed = false;
  global.wx.createOffscreenCanvas = function () {
    return {
      width: 100, height: 100,
      getContext: function () {
        return {
          drawImage: noop,
          getImageData: function () { const d = new Uint8ClampedArray(100 * 100 * 4); for (let i = 0; i < d.length; i++) d[i] = (i * 17) % 256; return { data: d, width: 100, height: 100 }; },
          putImageData: noop
        };
      },
      createImage: function () { const o = {}; Object.defineProperty(o, 'src', { set(v) { if (o.onload) o.onload(); } }); return o; }
    };
  };
  global.wx.canvasToTempFilePath = function (o) { o.success({ tempFilePath: '/tmp/out.png' }); };
  c.data.authorized = true;
  c._originW = 100; c._originH = 100; c._scale = 1;
  c._t0 = Date.now();
  c.process();
  processed = c.data.processed;
  assert.ok(processed, '只有线条时也应完成修复');
  assert.ok(/线条/.test(c.data.elapsedText), c.data.elapsedText);
});

console.log('\n合计 ' + (pass + fail) + ' 项，PASS ' + pass + '，FAIL ' + fail);
process.exit(fail ? 1 : 0);
