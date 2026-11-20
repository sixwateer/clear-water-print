/* 后端版 HTML 与 11:06 定稿 HTML 的修复效果一致性测试
   在隔离沙箱中同时加载两份脚本，对同一输入逐字节比对 lineRemove 与 repair 输出。 */
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const AUTH_HTML = 'C:/Users/16044/Documents/xwechat_files/wxid_61an2vkkekea22_f358/msg/file/2026-11/净像去水印_普通版_双击即用(2).html';
const BACK_HTML = 'D:/去水印/02_HTML版/原始原型_对接后端版.html';

let pass = 0, fail = 0;
function ok(name, cond, msg) {
  if (cond) { console.log('PASS  ' + name); pass++; }
  else { console.log('FAIL  ' + name + (msg ? '  -> ' + msg : '')); fail++; }
}
function mkData(W, H, seed) {
  const d = new Uint8ClampedArray(W * H * 4);
  for (let i = 0; i < d.length; i++) d[i] = (i * 37 + seed * 13 + 11) % 256;
  return d;
}

function load(htmlPath, W, H, seed) {
  const src = fs.readFileSync(htmlPath, 'utf8');
  const code = src.match(/<script>([\s\S]*?)<\/script>/)[1];

  function makeCtx(store) {
    const st = {};
    return new Proxy({}, {
      get(t, p) {
        if (p in st) return st[p];
        if (p === 'getImageData') return (sx, sy, rw, rh) => {
          const d = new Uint8ClampedArray(rw * rh * 4);
          for (let j = 0; j < rh; j++) for (let i = 0; i < rw; i++) {
            const s = ((sy + j) * W + (sx + i)) * 4, q = (j * rw + i) * 4;
            if (store.data) {
              d[q] = store.data[s] || 0; d[q + 1] = store.data[s + 1] || 0;
              d[q + 2] = store.data[s + 2] || 0; d[q + 3] = store.data[s + 3] || 0;
            }
          }
          return { data: d, width: rw, height: rh };
        };
        if (p === 'putImageData') return (img) => { store.data = new Uint8ClampedArray(img.data); };
        if (p === 'drawImage') return (img) => {
          if (img && img._data) store.data = new Uint8ClampedArray(img._data);
        };
        if (p === 'createLinearGradient') return () => ({ addColorStop() {} });
        if (p === 'measureText') return () => ({ width: 20 });
        if (p === 'canvas') return { width: W, height: H };
        return () => {};
      },
      set(t, p, v) { st[p] = v; return true; }
    });
  }

  const stageStore = { data: null };
  const cache = {};
  function el(id) {
    if (cache[id]) return cache[id];
    const store = { data: null };
    const o = {
      id, width: W, height: H, value: 'smart', textContent: '', checked: false,
      disabled: false, style: {}, dataset: {},
      classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
      getContext: () => (id === 'stage' ? makeCtx(stageStore) : makeCtx(store)),
      addEventListener() {}, removeEventListener() {},
      toDataURL: () => (store.data ? JSON.stringify(Array.from(store.data)) : ''),
      getBoundingClientRect: () => ({ left: 0, top: 0, width: W, height: H }),
      scrollIntoView() {}, click() {}, appendChild() {}
    };
    const p = new Proxy(o, { get(t, k) { if (k in t) return t[k]; return () => {}; }, set(t, k, v) { t[k] = v; return true; } });
    cache[id] = p;
    return p;
  }

  function canvas() {
    const store = { data: null };
    const o = {
      width: W, height: H, style: {},
      getContext: () => makeCtx(store),
      toDataURL: () => (store.data ? JSON.stringify(Array.from(store.data)) : ''),
      addEventListener() {}
    };
    return new Proxy(o, { get(t, k) { if (k in t) return t[k]; return () => {}; }, set(t, k, v) { t[k] = v; return true; } });
  }

  const sb = {
    console, performance: { now: () => 0 }, setTimeout, clearTimeout,
    document: {
      getElementById: el, querySelector: el, querySelectorAll: () => [],
      createElement: (tag) => (tag === 'canvas' ? canvas() : el('el_' + Math.random())),
      addEventListener() {}
    },
    window: { addEventListener() {}, scrollTo() {} },
    ImageData: class { constructor(d, w, h) { this.data = d; this.width = w; this.height = h; } },
    Image: class { constructor() { this._data = null; } set src(v) { this._src = v; if (this.onload) this.onload(); } },
    FormData: class { append() {} },
    URL: { createObjectURL: () => 'blob:x' },
    AbortSignal: { timeout: () => ({}) },
    fetch: () => Promise.reject(new Error('offline')),
    JSON, Math, Date, Uint8Array, Uint8ClampedArray, Float32Array, Uint32Array, Array, Object, String, Number, Promise, Error
  };
  vm.createContext(sb);
  vm.runInContext(code + '\n;globalThis.__X={S,lineState,FILL,CONFIG,lineRemove,repair,down,move,up,shapeBox,handlePos,get baseImage(){return baseImage},set baseImage(v){baseImage=v}};', sb);
  sb.__X.S.scale = 1;
  const img = new sb.Image();
  img._data = mkData(W, H, seed);
  img.width = W; img.height = H; img.src = 'data:';
  return { X: sb.__X, img, ctx: makeCtx({ data: mkData(W, H, seed) }), code };
}

function same(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

(function () {
  const W = 80, H = 80;
  const shapes = [
    [{x:25,y:25},{x:55,y:25},{x:55,y:55},{x:25,y:55}],
    [{x:15,y:15},{x:45,y:18},{x:48,y:42},{x:26,y:46},{x:12,y:30}],
    [{x:20,y:30},{x:60,y:28},{x:62,y:38},{x:20,y:40}]
  ];
  const modes = ['smart', 'average', 'texture'];

  // 1) lineRemove 逐字节一致（三形状 × 三模式）
  let idx = 0;
  for (const shape of shapes) for (const mode of modes) {
    const d1 = mkData(W, H, idx), d2 = mkData(W, H, idx);
    const A = load(AUTH_HTML, W, H, idx), B = load(BACK_HTML, W, H, idx);
    const r1 = A.X.lineRemove(d1, W, H, shape, 320, mode, A.ctx);
    const r2 = B.X.lineRemove(d2, W, H, shape, 320, mode, B.ctx);
    const regSame = !!r1 === !!r2 && (!r1 || (r1.x===r2.x && r1.y===r2.y && r1.w===r2.w && r1.h===r2.h && r1.method===r2.method));
    ok('lineRemove 逐字节一致 ' + mode + ' shape#' + shapes.indexOf(shape), same(d1, d2) && regSame,
       'firstDiff=' + (d1.findIndex((v,i)=>v!==d2[i])) + ' method=' + (r1&&r1.method) + '/' + (r2&&r2.method));
    idx++;
  }

  // 2) 完整 repair() 输出一致（矩形 + 线条混合、三模式）
  for (const mode of modes) {
    const A = load(AUTH_HTML, W, H, 5), B = load(BACK_HTML, W, H, 5);
    for (const X of [A.X, B.X]) {
      X.baseImage = (X === A.X ? A.img : B.img);
      X.S.mode = mode; X.S.iter = 2; X.S.sharpen = true;
      X.S.rects = [{x:20,y:20,w:30,h:20}];
      X.lineState.shapes = [[{x:10,y:45},{x:40,y:45},{x:40,y:65},{x:10,y:65}]];
    }
    const out1 = A.X.repair(), out2 = B.X.repair();
    ok('repair 输出一致 ' + mode, out1 === out2, 'len ' + out1.length + '/' + out2.length);
  }

  // 3) 交互模型一致（8 手柄缩放 + 移动，矩形/线条）
  function ev(x, y) { return { preventDefault(){}, clientX:x, clientY:y, touches:null }; }
  for (const kind of ['rect', 'line']) {
    const A = load(AUTH_HTML, W, H, 0), B = load(BACK_HTML, W, H, 0);
    for (const X of [A.X, B.X]) {
      X.baseImage = (X === A.X ? A.img : B.img);
      X.S.rects = kind === 'rect' ? [{x:10,y:10,w:30,h:20}] : [];
      X.lineState.shapes = kind === 'line' ? [[{x:10,y:10},{x:40,y:10},{x:40,y:30},{x:10,y:30}]] : [];
      const box = kind === 'rect' ? X.S.rects[0] : X.shapeBox(X.lineState.shapes[0]);
      const se = X.handlePos(box, 'se');
      X.down(ev(se.x, se.y));
      X.move(ev(60, 50)); X.up(ev(60, 50));
    }
    const r1 = kind === 'rect' ? A.X.S.rects[0] : A.X.shapeBox(A.X.lineState.shapes[0]);
    const r2 = kind === 'rect' ? B.X.S.rects[0] : B.X.shapeBox(B.X.lineState.shapes[0]);
    ok('手柄缩放一致 ' + kind, JSON.stringify(r1) === JSON.stringify(r2), JSON.stringify(r1) + '/' + JSON.stringify(r2));
  }

  console.log('\n共 ' + (pass + fail) + ' 项，PASS ' + pass + '，FAIL ' + fail);
  process.exit(fail ? 1 : 0);
})();
