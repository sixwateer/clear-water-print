/**
 * 小程序新功能回归测试（Node 直接运行，无需微信开发者工具）
 *   node tests/test_new_features.js
 *
 * 覆盖：
 *   1) repairStrict 严格只改框内，框外像素逐字节不变
 *   2) 框内水印确实被去除，且纹理模式能跑通
 *   3) 提示词解析（示例提示词 → 目标 + 补全依据 + 推荐框架）
 *   4) 页面逻辑 mock：框架切换、提示词输入、换图保留设置
 */
const assert = require('assert');
const inpaint = require('../utils/inpaint.js');
const promptUtil = require('../utils/prompt.js');

let pass = 0, fail = 0;
function check(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '  ->  ' + e.message); fail++; }
}

function makeImage(W, H, rect) {
  const data = new Uint8ClampedArray(W * H * 4);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const i = (y * W + x) * 4;
    data[i] = 90 + (x % 17);
    data[i + 1] = 110 + (y % 13);
    data[i + 2] = 130;
    data[i + 3] = 255;
  }
  // 框内叠半透明白色"水印"：高亮、低饱和
  for (let y = rect.y; y < rect.y + rect.h; y++) {
    for (let x = rect.x; x < rect.x + rect.w; x++) {
      const i = (y * W + x) * 4;
      if ((x + y) % 3 === 0) { data[i] = 248; data[i + 1] = 250; data[i + 2] = 252; }
    }
  }
  return { width: W, height: H, data: data };
}

function snapshotOutside(img, rect) {
  const out = [];
  for (let y = 0; y < img.height; y++) for (let x = 0; x < img.width; x++) {
    if (x >= rect.x && x < rect.x + rect.w && y >= rect.y && y < rect.y + rect.h) continue;
    const i = (y * img.width + x) * 4;
    out.push(img.data[i], img.data[i + 1], img.data[i + 2], img.data[i + 3]);
  }
  return out;
}

function watermarkPixels(img, rect) {
  let n = 0;
  for (let y = rect.y; y < rect.y + rect.h; y++) for (let x = rect.x; x < rect.x + rect.w; x++) {
    const i = (y * img.width + x) * 4;
    const r = img.data[i], g = img.data[i + 1], b = img.data[i + 2];
    if (r > 235 && g > 235 && b > 235) n++;
  }
  return n;
}

const RECT = { x: 18, y: 16, w: 26, h: 20 };

check('repairStrict：框外像素逐字节不变（smart）', function () {
  const img = makeImage(64, 56, RECT);
  const before = snapshotOutside(img, RECT);
  inpaint.repairStrict(img, [RECT], 'smart', 200, { textureDetail: true });
  assert.deepStrictEqual(snapshotOutside(img, RECT), before);
});

check('repairStrict：框外像素逐字节不变（texture 含高频回注）', function () {
  const img = makeImage(64, 56, RECT);
  const before = snapshotOutside(img, RECT);
  inpaint.repairStrict(img, [RECT], 'texture', 200, { textureDetail: true });
  assert.deepStrictEqual(snapshotOutside(img, RECT), before);
});

check('text 文字水印框架：框外像素逐字节不变', function () {
  const img = makeImage(64, 56, RECT);
  const before = snapshotOutside(img, RECT);
  inpaint.repair(img, [RECT], 'text', 240);
  assert.deepStrictEqual(snapshotOutside(img, RECT), before);
});

check('text 文字水印框架：框内亮字被削弱且可导出调用', function () {
  assert.strictEqual(typeof inpaint.textWatermarkRemove, 'function', '应导出 textWatermarkRemove');
  const img = makeImage(64, 56, RECT);
  const before = watermarkPixels(img, RECT);
  inpaint.repair(img, [RECT], 'text', 240);
  const after = watermarkPixels(img, RECT);
  assert.ok(after < before, '亮字点应减少：' + before + ' -> ' + after);
});

check('repairStrict：框内水印被去净（残影 0）', function () {
  const img = makeImage(64, 56, RECT);
  const before = watermarkPixels(img, RECT);
  assert.ok(before > 50, '测试图水印点应足够多，实际 ' + before);
  inpaint.repairStrict(img, [RECT], 'smart', 200, {});
  const after = watermarkPixels(img, RECT);
  assert.strictEqual(after, 0, '修复后不应残留高亮水印点，实际 ' + after);
});

check('repairStrict：贴边框不越界、不抛错', function () {
  const rect = { x: 0, y: 0, w: 20, h: 16 };
  const img = makeImage(40, 40, rect);
  const before = snapshotOutside(img, rect);
  inpaint.repairStrict(img, [rect], 'smart', 100, {});
  assert.deepStrictEqual(snapshotOutside(img, rect), before);
});

check('提示词：示例提示词解析为目标+纹理补全', function () {
  const info = promptUtil.parsePrompt(promptUtil.EXAMPLE);
  assert.strictEqual(info.target, '蓝色包');
  assert.strictEqual(info.framework, 'texture');
  assert.ok(info.intent.indexOf('衣物') >= 0, info.intent);
});

check('提示词：渐变背景映射到智能扩散', function () {
  const info = promptUtil.parsePrompt('去掉框住的水印，背景是渐变色');
  assert.strictEqual(info.framework, 'smart');
});

check('提示词：空输入不报错', function () {
  const info = promptUtil.parsePrompt('');
  assert.strictEqual(info.intent, '');
});

// ---- 页面逻辑 mock ----
check('页面：框架切换 / 提示词输入 / 换图保留设置', function () {
  let pageCfg = null;
  const listeners = {};
  global.Page = function (cfg) { pageCfg = cfg; };
  global.getApp = function () {
    return { globalData: { compliance: '测试合规文案', algo: { smartIterations: 80 } } };
  };
  global.wx = {
    showToast: function () {},
    showLoading: function () {},
    hideLoading: function () {},
    chooseMedia: function (o) { o.success({ tempFiles: [{ tempFilePath: '/tmp/a.png' }] }); },
    getImageInfo: function (o) { o.success({ width: 690, height: 460 }); },
    createSelectorQuery: function () { return { in: function () { return this; }, select: function () { return this; }, fields: function () { return this; }, exec: function () {} }; }
  };
  delete require.cache[require.resolve('../pages/index/index.js')];
  require('../pages/index/index.js');
  assert.ok(pageCfg, 'Page 配置应被捕获');

  const ctx = Object.assign({}, pageCfg);
  ctx.data = JSON.parse(JSON.stringify(pageCfg.data));
  ctx.setData = function (o) { Object.assign(this.data, o); };
  ctx.onLoad();
  assert.ok(ctx.data.frameworks.length >= 4, '至少 4 个可切换框架');
  ctx.setFramework({ currentTarget: { dataset: { key: 'prompt' } } });
  assert.strictEqual(ctx.data.framework, 'prompt');
  ctx.onPromptInput({ detail: { value: promptUtil.EXAMPLE } });
  assert.ok(ctx.data.promptIntent.indexOf('蓝色包') >= 0, ctx.data.promptIntent);
  ctx._loadImage('/tmp/a.png');
  assert.strictEqual(ctx.data.hasImage, true);
  ctx.nextImage();
  assert.strictEqual(ctx.data.framework, 'prompt', '换图应保留所选框架');
  assert.ok(ctx.data.promptText.length > 0, '换图应保留提示词');
});

check('画布交互：手柄缩放 / 框内移动 / 空白重画', function () {
  let pageCfg = null;
  global.Page = function (cfg) { pageCfg = cfg; };
  global.getApp = function () {
    return { globalData: { compliance: '', algo: { smartIterations: 40 } } };
  };
  global.wx = {
    showToast: function () {},
    createSelectorQuery: function () {
      return { in: function () { return this; }, select: function () { return this; },
        fields: function () { return this; }, exec: function () {} };
    }
  };
  delete require.cache[require.resolve('../pages/index/index.js')];
  require('../pages/index/index.js');
  const c = Object.assign({}, pageCfg);
  c.data = JSON.parse(JSON.stringify(pageCfg.data));
  c.data.hasImage = true;
  c.data.displayW = 200; c.data.displayH = 200;
  c._rect = { left: 0, top: 0 };
  c.setData = function (o) { Object.assign(this.data, o); };

  // 已有框：点左上角手柄 → 缩放
  c.data.box = { x: 50, y: 50, w: 60, h: 40 };
  c.onTouchStart({ touches: [{ x: 50, y: 50 }] });
  assert.strictEqual(c._action, 'resize', '点手柄应进入缩放');
  c.onTouchMove({ touches: [{ x: 40, y: 40 }] });
  c.onTouchEnd({ changedTouches: [{ x: 40, y: 40 }] });
  assert.strictEqual(c.data.box.x, 40, '缩放后左上角应跟随手指');

  // 点框内部 → 移动
  c.data.box = { x: 50, y: 50, w: 60, h: 40 };
  c.onTouchStart({ touches: [{ x: 80, y: 70 }] });
  assert.strictEqual(c._action, 'move', '点框内部应进入移动');
  c.onTouchMove({ touches: [{ x: 90, y: 80 }] });
  c.onTouchEnd({ changedTouches: [{ x: 90, y: 80 }] });
  assert.strictEqual(c.data.box.x, 60, '移动后位置应跟随位移');

  // 点空白处 → 重新画框
  c.onTouchStart({ touches: [{ x: 150, y: 150 }] });
  assert.strictEqual(c._action, 'draw', '空白处应进入画新框');
  c.onTouchMove({ touches: [{ x: 180, y: 190 }] });
  c.onTouchEnd({ changedTouches: [{ x: 180, y: 190 }] });
  assert.deepStrictEqual(c.data.box, { x: 150, y: 150, w: 30, h: 40 });
});

console.log('\n合计 ' + (pass + fail) + ' 项，PASS ' + pass + '，FAIL ' + fail);
process.exit(fail ? 1 : 0);
