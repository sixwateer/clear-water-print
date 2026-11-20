/**
 * 后端对接版 HTML 回归测试（Node 直接运行）
 *   node 08_自测/html/test_backend_page.js
 *
 * 状态模型已与 11:06 定稿统一：修复状态在 S / lineState，
 * 后端对接状态独立在 B。测试针对页面里的真代码。
 */
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '../..');
const HTML = path.join(ROOT, '02_HTML版/原始原型_对接后端版.html');
const MINI_JS = path.join(ROOT, '04_小程序版/utils/prompt.js');

let pass = 0, fail = 0;
const tests = [];
function check(name, fn) { tests.push([name, fn]); }

const html = fs.readFileSync(HTML, 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
assert.ok(m, '未找到页面脚本');
const code = m[1] + '\n;globalThis.__S=S;globalThis.__B=B;globalThis.__LS=lineState;globalThis.__FW=FRAMEWORKS;globalThis.__CFG=CONFIG;globalThis.__setBase=function(v){baseImage=v};';
new Function(code); // 语法检查

function makeEl(id) {
  const ctxMock = new Proxy({}, { get: (t, k) => (k === 'measureText' ? function () { return { width: 40 }; } : (k in t ? t[k] : () => {})) });
  return {
    id, style: {}, dataset: {}, value: 'smart', textContent: '', innerHTML: '',
    width: 720, height: 480,
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, getContext() { return ctxMock; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 720, height: 480 }; },
    click() { this._clicked = (this._clicked || 0) + 1; },
    scrollIntoView() {}, checked: false
  };
}

const els = {};
const captured = {};
function buildContext() {
  Object.keys(els).forEach(function (k) { delete els[k]; });
  const document = {
    getElementById(id) { return els[id] || (els[id] = makeEl(id)); },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    createElement() { return makeEl('tmp'); }
  };
  const sandbox = {
    document,
    window: { addEventListener() {}, scrollTo() {} },
    console: { log() {}, warn() {}, error() {} },
    setTimeout, clearTimeout, Math, Date, JSON, Object, Array, String, Number,
    Boolean, RegExp, Error, parseInt, parseFloat, isNaN, Uint8Array, Uint8ClampedArray,
    Float32Array, Uint32Array, Promise,
    AbortSignal: { timeout() { return {}; } },
    URL: { createObjectURL() { return 'blob:mock'; }, revokeObjectURL() {} },
    Image: class { set src(v) {} },
    FileReader: class {},
    FormData: class { append(k, v) { captured[k] = v; } },
    fetch: async function (url) {
      captured.url = url;
      return {
        ok: true,
        blob: async () => 'BLOB',
        headers: { get(k) {
          return ({
            'X-Framework-Used': 'texture',
            'X-Prompt-Intent': '"目标：蓝色包 · 按衣物/背景纹理补全"',
            'X-Strict-Box': 'true',
            'X-Elapsed-Ms': '123'
          })[k] || null;
        } }
      };
    }
  };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return sandbox;
}

const ctx = buildContext();
const S = ctx.__S, B = ctx.__B, LS = ctx.__LS;

check('脚本语法与加载：页面初始化成功', function () {
  assert.ok(S && B && LS && ctx.__FW && ctx.__CFG, '脚本应成功执行');
  assert.strictEqual(B.framework, 'smart');
  assert.strictEqual(LS.tool, 'rect');
});

check('权威状态：S 与定稿逐字段一致', function () {
  assert.deepStrictEqual(Object.keys(S).sort(),
    ['drawing','img','iter','mode','resultData','scale','sharpen','start','cur','rects'].sort());
  assert.strictEqual(S.mode, 'smart');
  assert.strictEqual(S.iter, 2);
  assert.strictEqual(S.sharpen, true);
});

check('提示词解析：示例提示词 → 蓝色包 / 纹理重建', function () {
  const info = ctx.parsePrompt(ctx.__CFG.promptExample);
  assert.strictEqual(info.target, '蓝色包');
  assert.strictEqual(info.framework, 'texture');
  assert.ok(info.intent.indexOf('衣物') >= 0, info.intent);
});

check('提示词解析：与小程序 prompt.js 的示例一致', function () {
  const src = fs.readFileSync(MINI_JS, 'utf8');
  const mm = src.match(/var EXAMPLE\s*=\s*'([^']+)'/);
  assert.ok(mm, '未能从小程序 JS 抽取示例');
  const mini = ctx.parsePrompt(mm[1]);
  const backend = ctx.parsePrompt(ctx.__CFG.promptExample);
  assert.strictEqual(mini.target, backend.target);
  assert.strictEqual(mini.framework, backend.framework);
});

check('框架切换：点击后更新状态、说明并同步 S.mode', function () {
  ctx.setFramework('texture');
  assert.strictEqual(B.framework, 'texture');
  assert.strictEqual(S.mode, 'texture');
  assert.ok(els.fwDesc.textContent.indexOf('纹理') >= 0);
});

check('提示词框架：按解析结果选算法，空提示词回退智能扩散', function () {
  ctx.setFramework('prompt');
  ctx.onPromptInput({ target: { value: ctx.__CFG.promptExample } });
  assert.strictEqual(ctx.resolveFramework().actual, 'texture');
  assert.strictEqual(S.mode, 'texture');
  assert.ok(els.promptIntent.textContent.indexOf('蓝色包') >= 0);
  ctx.onPromptInput({ target: { value: '' } });
  assert.strictEqual(ctx.resolveFramework().actual, 'smart');
  assert.strictEqual(S.mode, 'smart');
});

check('用示例按钮：填入提示词并展示意图', function () {
  ctx.useExamplePrompt();
  assert.ok(B.promptText.indexOf('蓝色包') >= 0);
  assert.ok(els.promptIntent.textContent.indexOf('衣物') >= 0);
});

check('换下一张照片：触发文件选择且不重置框架/提示词', function () {
  ctx.setFramework('prompt');
  ctx.onPromptInput({ target: { value: ctx.__CFG.promptExample } });
  const before = els.fileInput._clicked || 0;
  ctx.nextImage();
  assert.strictEqual(els.fileInput._clicked, before + 1);
  assert.strictEqual(B.framework, 'prompt');
  assert.ok(B.promptText.length > 0);
});

check('后端交互：FormData 携带 framework/prompt/strict_box', async function () {
  B.serverOnline = true;
  B.file = {}; S.rects = [{ x: 1, y: 1, w: 10, h: 10 }]; S.scale = 1;
  ctx.setFramework('prompt');
  ctx.onPromptInput({ target: { value: ctx.__CFG.promptExample } });
  const result = await ctx.callBackend();
  assert.strictEqual(captured.framework, 'prompt');
  assert.strictEqual(captured.prompt, ctx.__CFG.promptExample);
  assert.strictEqual(captured.strict_box, 'true');
  assert.ok(captured.url.indexOf('/api/v2/process') >= 0);
  assert.strictEqual(result.framework, 'texture');
  assert.strictEqual(result.strict, 'true');
  assert.ok(result.intent.indexOf('蓝色包') >= 0);
});

check('多框：矩形可连续添加，互不覆盖', function () {
  S.rects = []; LS.sel = null;
  for (let i = 0; i < 5; i++) S.rects.push({ x: i * 10, y: 10, w: 20, h: 20 });
  assert.strictEqual(S.rects.length, 5);
});

check('线条框选：画一圈后进入 lineState.shapes，不污染 S.rects', function () {
  S.rects = []; LS.shapes = []; LS.sel = null; LS.tool = 'line';
  LS.active = true; LS.pts = [{x:10,y:10},{x:30,y:20},{x:50,y:40},{x:10,y:40}];
  ctx.up(null);
  assert.strictEqual(S.rects.length, 0);
  assert.strictEqual(LS.shapes.length, 1);
  assert.strictEqual(LS.shapes[0].length, 4);
  assert.ok(LS.sel && LS.sel.kind === 'line');
});

check('删除当前框：通过统一选中态只删一个', function () {
  S.rects = [{ x: 1, y: 1, w: 2, h: 2 }, { x: 5, y: 5, w: 2, h: 2 }];
  LS.shapes = []; LS.sel = { kind: 'rect', index: 1 };
  els.toolDel.onclick();
  assert.strictEqual(S.rects.length, 1);
  assert.strictEqual(S.rects[0].x, 1);
});

check('后端交互：多个矩形全部提交且只含 x/y/w/h', async function () {
  S.rects = [
    { x: 1, y: 2, w: 3, h: 4 },
    { x: 5, y: 6, w: 7, h: 8 },
    { x: 9, y: 10, w: 11, h: 12 }
  ];
  LS.shapes = [];
  B.serverOnline = true; B.file = {}; S.scale = 1;
  captured.rects = 'SENTINEL';
  await ctx.callBackend();
  const sent = JSON.parse(captured.rects);
  assert.strictEqual(sent.length, 3);
  assert.deepStrictEqual(Object.keys(sent[0]).sort(), ['h', 'w', 'x', 'y']);
});

check('结果展示：对比线归位到中央（回归手柄贴左）', function () {
  ctx.__setBase({ src: 'data:image/png;base64,AA' });
  els.handle.style.left = '14%';
  ctx.showResult('blob:mock', { framework: 'texture', strict: 'true', intent: '测试' });
  assert.strictEqual(els.handle.style.left, '50%');
  assert.ok(String(els.imgBefore.style.clipPath).indexOf('50%') >= 0);
});

check('轮廓线稿：保留原始轨迹点（不强制闭合），供多边形 mask 使用', function () {
  S.rects = []; LS.shapes = []; LS.sel = null; LS.tool = 'line';
  LS.active = true; LS.pts = [{x:10,y:10},{x:50,y:10},{x:50,y:50},{x:45,y:48}];
  ctx.up(null);
  assert.strictEqual(LS.shapes.length, 1);
  assert.strictEqual(LS.shapes[0].length, 4);
  assert.notDeepStrictEqual(LS.shapes[0][0], LS.shapes[0][3]);
});

check('后端交互：轮廓走 contour + polygon，矩形才走 rects', async function () {
  B.serverOnline = true; B.file = {}; S.scale = 1;
  S.rects = [];
  LS.shapes = [[{x:10,y:10},{x:50,y:10},{x:50,y:50},{x:10,y:50}]];
  captured.rects = 'SENTINEL';
  await ctx.callBackend();
  assert.strictEqual(captured.effect, 'contour');
  const polys = JSON.parse(captured.polygon);
  assert.strictEqual(polys.length, 1);
  assert.strictEqual(polys[0].length, 4);
  assert.strictEqual(captured.rects, 'SENTINEL', '线条路径不应提交矩形框');
});

(async function () {
  for (const [name, fn] of tests) {
    try { await fn(); console.log('PASS  ' + name); pass++; }
    catch (e) { console.log('FAIL  ' + name + '  ->  ' + e.message); fail++; }
  }
  console.log('\n合计 ' + (pass + fail) + ' 项，PASS ' + pass + '，FAIL ' + fail);
  process.exit(fail ? 1 : 0);
})();
