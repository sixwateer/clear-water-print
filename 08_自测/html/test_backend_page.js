/**
 * 后端对接版 HTML 新功能回归测试（Node 直接运行）
 *   node 08_自测/html/test_backend_page.js
 *
 * 做法：从交付的 HTML 中抽取 <script>，在 Node 沙箱里用最小 DOM mock 执行，
 * 测的是页面里的真代码，不是抄写的副本。
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
const code = m[1] + '\n;globalThis.__S=S;globalThis.__FW=FRAMEWORKS;globalThis.__CFG=CONFIG;globalThis.__setBase=function(v){baseImage=v};';
// 语法检查：构造时即抛错
new Function(code);

function makeEl(id) {
  const ctxMock = new Proxy({}, { get: (t, k) => (k === 'measureText' ? function () { return { width: 40 }; } : (k in t ? t[k] : () => {})) });
  return {
    id, style: {}, dataset: {}, value: '', textContent: '', innerHTML: '',
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
  Object.keys(els).forEach(function (k) { delete els[k]; }); // 每次用全新 mock 元素
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
    Boolean, RegExp, Error, parseInt, parseFloat, isNaN, Uint8Array, Float32Array,
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
const S = ctx.__S;

check('脚本语法与加载：页面初始化成功', function () {
  assert.ok(S && ctx.__FW && ctx.__CFG, '脚本应成功执行');
  assert.strictEqual(S.framework, 'smart');
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

check('框架切换：点击后更新状态与说明', function () {
  ctx.setFramework('texture');
  assert.strictEqual(S.framework, 'texture');
  assert.ok(els.fwDesc.innerHTML === undefined || els.fwDesc.textContent.indexOf('纹理') >= 0);
});

check('提示词框架：按解析结果选算法，空提示词回退智能扩散', function () {
  ctx.setFramework('prompt');
  ctx.onPromptInput({ target: { value: ctx.__CFG.promptExample } });
  assert.strictEqual(ctx.resolveFramework().actual, 'texture');
  assert.ok(els.promptIntent.textContent.indexOf('蓝色包') >= 0);
  ctx.onPromptInput({ target: { value: '' } });
  assert.strictEqual(ctx.resolveFramework().actual, 'smart');
});

check('用示例按钮：填入提示词并展示意图', function () {
  ctx.useExamplePrompt();
  assert.ok(S.promptText.indexOf('蓝色包') >= 0);
  assert.ok(els.promptIntent.textContent.indexOf('衣物') >= 0);
});

check('换下一张照片：触发文件选择且不重置框架/提示词', function () {
  ctx.setFramework('prompt');
  ctx.onPromptInput({ target: { value: ctx.__CFG.promptExample } });
  const before = els.fileInput._clicked || 0;
  ctx.nextImage();
  assert.strictEqual(els.fileInput._clicked, before + 1);
  assert.strictEqual(S.framework, 'prompt');
  assert.ok(S.promptText.length > 0);
});

check('后端交互：FormData 携带 framework/prompt/strict_box', async function () {
  S.serverOnline = true;
  S.file = {}; S.rects = [{ x: 1, y: 1, w: 10, h: 10 }]; S.scale = 1; S.img = {};
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

check('多框：最多 3 个，超出替换当前框', function () {
  S.rects = []; S.activeBox = 0; S.tool = 'rect';
  for (let i = 0; i < 5; i++) ctx.commitBox({ x: i * 10, y: 10, w: 20, h: 20 });
  assert.strictEqual(S.rects.length, 3);
});

check('线条框选：轨迹外接矩形标记为自定义框', function () {
  S.rects = []; S.activeBox = 0; S.tool = 'line';
  S.action = 'line';
  S.linePts = [{ x: 10, y: 10 }, { x: 30, y: 20 }, { x: 50, y: 40 }];
  ctx.up(null);
  assert.strictEqual(S.rects.length, 1);
  assert.strictEqual(S.rects[0].kind, 'line');
  assert.strictEqual(S.rects[0].w, 40);
  assert.strictEqual(S.rects[0].h, 30);
});

check('删除当前框：只删一个而非清空', function () {
  S.rects = [{ x: 1, y: 1, w: 2, h: 2 }, { x: 5, y: 5, w: 2, h: 2 }];
  S.activeBox = 1;
  els.toolDel.onclick();
  assert.strictEqual(S.rects.length, 1);
  assert.strictEqual(S.rects[0].x, 1);
});

check('后端交互：三个框全部提交且只含 x/y/w/h', async function () {
  S.rects = [
    { x: 1, y: 2, w: 3, h: 4, kind: 'line' },
    { x: 5, y: 6, w: 7, h: 8 },
    { x: 9, y: 10, w: 11, h: 12 }
  ];
  S.serverOnline = true; S.file = {}; S.scale = 1; S.img = {};
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

check('轮廓线稿：保留轨迹点并自动闭合，不再取外接矩形', function () {
  S.rects = []; S.activeBox = 0; S.tool = 'line';
  S.action = 'line';
  S.linePts = [{ x: 10, y: 10 }, { x: 50, y: 10 }, { x: 50, y: 50 }, { x: 45, y: 48 }];
  ctx.up(null);
  const r = S.rects[0];
  assert.ok(r && r.points && r.points.length === 5, '应为 4 点 + 闭合点');
  assert.strictEqual(r.kind, 'line');
  assert.deepStrictEqual(r.points[0], r.points[r.points.length - 1]);
});

check('后端交互：轮廓走 contour + polygon，矩形才走 rects', async function () {
  S.serverOnline = true; S.file = {}; S.scale = 1; S.img = {};
  S.rects = [{ x: 10, y: 10, w: 40, h: 40, kind: 'line', points: [
    { x: 10, y: 10 }, { x: 50, y: 10 }, { x: 50, y: 50 }, { x: 10, y: 50 }, { x: 10, y: 10 }
  ] }];
  captured.rects = 'SENTINEL';
  await ctx.callBackend();
  assert.strictEqual(captured.effect, 'contour');
  const polys = JSON.parse(captured.polygon);
  assert.strictEqual(polys.length, 1);
  assert.strictEqual(polys[0].length, 5);
  assert.strictEqual(captured.rects, 'SENTINEL', 'sketch 时不应提交矩形框');
});

(async function () {
  for (const [name, fn] of tests) {
    try { await fn(); console.log('PASS  ' + name); pass++; }
    catch (e) { console.log('FAIL  ' + name + '  ->  ' + e.message); fail++; }
  }
  console.log('\n合计 ' + (pass + fail) + ' 项，PASS ' + pass + '，FAIL ' + fail);
  process.exit(fail ? 1 : 0);
})();
