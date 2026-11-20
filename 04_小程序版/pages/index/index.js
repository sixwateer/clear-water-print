const inpaint = require('../../utils/inpaint.js');
const lineInpaint = require('../../utils/lineInpaint.js');
const promptUtil = require('../../utils/prompt.js');

const app = getApp();

// 触摸交互常量（CSS 像素；画布用 dpr 缩放绘制，触摸坐标也是 CSS 像素，两者一致）
const HIT = 18;       // 手柄命中半径，手指友好
const MIN_BOX = 12;   // 选框最小边长
const HANDLES = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];

// 标注样式：与权威 HTML 的 MARK 常量一致，矩形与线条共用同一套属性
const MARK = {
  stroke: 'rgba(15,158,142,.95)', strokeSel: 'rgba(91,110,225,1)',
  fill: 'rgba(15,158,142,.13)', fillSel: 'rgba(91,110,225,.13)',
  preview: 'rgba(91,110,225,1)', dash: [6, 4]
};

// 统一画笔：矩形(strokeRect)与线条(path)走同一套属性，避免两套不一致实现
function withMark(ctx, stroke, fill, fn) {
  ctx.save();
  ctx.strokeStyle = stroke; ctx.lineWidth = 2;
  ctx.setLineDash(MARK.dash); ctx.lineJoin = 'round'; ctx.lineCap = 'round';
  if (fill) ctx.fillStyle = fill;
  fn();
  ctx.restore();
}
// 只描线条，不产生填充块或矩形；样式由 withMark 统一提供，与矩形框完全一致
function strokePath(ctx, pts, close, color) {
  if (!pts || pts.length < 2) return;
  withMark(ctx, color, null, function () {
    ctx.beginPath(); ctx.moveTo(pts[0].x, pts[0].y);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
    if (close) ctx.closePath();
    ctx.stroke();
  });
}
// 选中项手柄：白底蓝边小方点，矩形与线条共用
function drawHandles(ctx, hs) {
  const size = 8;
  ctx.save();
  for (const k of HANDLES) {
    const q = hs[k];
    ctx.fillStyle = '#fff'; ctx.strokeStyle = MARK.strokeSel; ctx.lineWidth = 1.6;
    ctx.fillRect(q.x - size / 2, q.y - size / 2, size, size);
    ctx.strokeRect(q.x - size / 2, q.y - size / 2, size, size);
  }
  ctx.restore();
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

Page({
  data: {
    // 图片与画布
    hasImage: false,
    displayW: 0,
    displayH: 0,
    imagePath: '',
    // 框选（显示坐标，相对画布）
    box: null,          // {x,y,w,h}
    drawing: false,
    // 线条去除：与矩形框选并列的独立工具，状态互相隔离
    tool: 'rect',       // 'rect' | 'line'
    shapes: [],         // 闭合线条轨迹数组（显示坐标）
    sel: null,          // 选中项 {kind:'box'|'line', index}
    toolHint: '在图片上拖拽框住水印；点框选中，拖手柄缩放',
    // 处理结果
    resultPath: '',
    processed: false,
    busy: false,
    elapsedText: '',
    // 修复框架（可切换）
    framework: 'smart',
    frameworks: [
      { key: 'smart', label: '智能扩散', tag: '推荐' },
      { key: 'texture', label: '纹理重建', tag: '衣物/木纹' },
      { key: 'average', label: '快速填充', tag: '最快' },
      { key: 'prompt', label: '提示词引导', tag: '按描述' }
    ],
    frameworkDesc: {
      smart: '智能扩散：依据框外背景颜色向内推算，纯色/渐变背景近乎无痕',
      texture: '纹理重建：扩散重建后回注邻近衣物/木纹高频，纹理背景不糊成平色',
      average: '快速填充：取边缘平均色平铺，适合面积很小、背景单一的目标',
      prompt: '提示词引导：按你输入的描述自动选择框架；未写提示词时用智能扩散'
    },
    // 提示词
    promptText: '',
    promptExample: promptUtil.EXAMPLE,
    promptIntent: '',
    // 合规
    authorized: false,
    compliance: ''
  },

  onLoad: function () {
    this.setData({ compliance: app.globalData.compliance });
  },

  // 获取设备像素比，兼容新旧基础库（getSystemInfoSync 已逐步废弃）
  _getDpr: function () {
    try {
      if (wx.getWindowInfo) {
        var info = wx.getWindowInfo();
        if (info && info.pixelRatio) return info.pixelRatio;
      }
    } catch (e) {}
    try {
      return (wx.getSystemInfoSync().pixelRatio) || 1;
    } catch (e) {}
    return 1;
  },

  // 读取触摸点相对画布的坐标。
  // canvas 组件触摸事件优先提供相对画布的 x/y；仅给 clientX/clientY 的机型，
  // 需减去画布在视口中的位置（缓存在 _drawBase 的 _rect），否则框选会错位。
  _touchPos: function (t) {
    if (!t) return { x: 0, y: 0 };
    if (t.x != null && t.y != null) return { x: t.x, y: t.y };
    const rect = this._rect || { left: 0, top: 0 };
    return { x: (t.clientX || 0) - rect.left, y: (t.clientY || 0) - rect.top };
  },

  // 选择图片
  chooseImage: function () {
    const that = this;
    // wx.chooseMedia 需基础库 2.10.0+，老版本兜底用 wx.chooseImage
    if (wx.chooseMedia) {
      wx.chooseMedia({
        count: 1,
        mediaType: ['image'],
        sourceType: ['album', 'camera'],
        success: function (res) {
          const path = res.tempFiles && res.tempFiles[0] && res.tempFiles[0].tempFilePath;
          if (path) that._loadImage(path);
        }
      });
    } else {
      wx.chooseImage({
        count: 1,
        sourceType: ['album', 'camera'],
        success: function (res) {
          const path = res.tempFilePaths && res.tempFilePaths[0];
          if (path) that._loadImage(path);
        }
      });
    }
  },

  // 换下一张照片：重新选图，但保留框架、提示词与授权设置
  nextImage: function () {
    this._img = null; // 强制重建画布图像缓存
    this.chooseImage();
    wx.showToast({ title: '选择下一张照片', icon: 'none' });
  },

  // 读取图片信息并加载到画布
  _loadImage: function (path) {
    const that = this;
    wx.getImageInfo({
      src: path,
      success: function (info) {
        const maxW = 345; // px，约 690rpx
        const scale = Math.min(1, maxW / info.width);
        const dw = Math.round(info.width * scale);
        const dh = Math.round(info.height * scale);
        that._scale = scale;
        that._originW = info.width;
        that._originH = info.height;
        that._img = null;      // 新图必须重建缓存
        that._preview = null;
        that._linePts = null;
        that.setData({
          imagePath: path,
          displayW: dw,
          displayH: dh,
          hasImage: true,
          processed: false,
          box: null,
          shapes: [],
          sel: null,
          resultPath: '',
          elapsedText: ''
        }, function () {
          that._drawBase();
        });
      },
      fail: function () {
        wx.showToast({ title: '图片读取失败，请换一张', icon: 'none' });
      }
    });
  },

  // 8 个缩放手柄的位置（显示坐标）——矩形与线条共用
  _handles: function (b) {
    const x = b.x, y = b.y, w = b.w, h = b.h, cx = x + w / 2, cy = y + h / 2;
    return {
      nw: { x: x, y: y }, n: { x: cx, y: y }, ne: { x: x + w, y: y },
      e: { x: x + w, y: cy }, se: { x: x + w, y: y + h }, s: { x: cx, y: y + h },
      sw: { x: x, y: y + h }, w: { x: x, y: cy }
    };
  },

  _pickHandleAt: function (p, b) {
    if (!b) return null;
    const hs = this._handles(b);
    for (const k of HANDLES) {
      const q = hs[k];
      if (Math.abs(p.x - q.x) <= HIT && Math.abs(p.y - q.y) <= HIT) return k;
    }
    return null;
  },

  _pickHandle: function (p) { return this._pickHandleAt(p, this.data.box); },

  _inBox: function (p, b) {
    return b && p.x >= b.x && p.x <= b.x + b.w && p.y >= b.y && p.y <= b.y + b.h;
  },

  // 线条的外接矩形：只用于交互命中与手柄定位，绝不画出、也不参与像素修复
  _shapeBox: function (pts) {
    let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
    for (const p of pts) {
      x1 = Math.min(x1, p.x); y1 = Math.min(y1, p.y);
      x2 = Math.max(x2, p.x); y2 = Math.max(y2, p.y);
    }
    return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
  },

  _selBox: function () {
    const s = this.data.sel;
    if (!s) return null;
    if (s.kind === 'box') return this.data.box || null;
    const pts = this.data.shapes[s.index];
    return pts && pts.length ? this._shapeBox(pts) : null;
  },

  // 画原图 + 矩形框 + 线条 + 选中项手柄。矩形与线条共用 MARK 样式，
  // 图层顺序：未选中项底层 → 选中高亮置顶 → 预览 → 手柄（与权威 HTML 一致）
  _paint: function (ctx, b, dpr) {
    const W = this.data.displayW, H = this.data.displayH;
    ctx.clearRect(0, 0, W, H);
    if (this._img) ctx.drawImage(this._img, 0, 0, W, H);
    const sel = this.data.sel;
    const box = b === undefined ? this.data.box : b;
    const paint = (active) => {
      if (box) {
        const isBoxSel = !!(sel && sel.kind === 'box');
        if (isBoxSel === active) {
          withMark(ctx, isBoxSel ? MARK.strokeSel : MARK.stroke,
            isBoxSel ? MARK.fillSel : MARK.fill, function () {
              ctx.strokeRect(box.x, box.y, box.w, box.h);
              ctx.fillRect(box.x, box.y, box.w, box.h);
            });
        }
      }
      this.data.shapes.forEach((pts, i) => {
        const isLineSel = !!(sel && sel.kind === 'line' && sel.index === i);
        if (isLineSel === active) strokePath(ctx, pts, true, isLineSel ? MARK.strokeSel : MARK.stroke);
      });
    };
    paint(false); paint(true);
    // 正在画的线条预览
    if (this._linePts && this._linePts.length > 1) strokePath(ctx, this._linePts, false, MARK.preview);
    // 选中项手柄：矩形与线条共用同一套小方点
    const sb = this._selBox();
    if (sb) drawHandles(ctx, this._handles(sb));
  },

  _drawBase: function (box) {
    const that = this;
    const query = wx.createSelectorQuery().in(this);
    // rect: true 同时取 canvas 在视口中的位置，用于触摸坐标兜底换算
    query.select('#stage').fields({ node: true, size: true, rect: true }).exec(function (res) {
      const canvas = res[0] && res[0].node;
      if (!canvas) return;
      that._rect = { left: res[0].left || 0, top: res[0].top || 0 };
      const ctx = canvas.getContext('2d');
      const dpr = that._getDpr();
      canvas.width = that.data.displayW * dpr;
      canvas.height = that.data.displayH * dpr;
      ctx.scale(dpr, dpr);
      const b = box === undefined ? that.data.box : box;
      if (that._img && that._imgSrc === that.data.imagePath) {
        that._paint(ctx, b, dpr);
        return;
      }
      const img = canvas.createImage();
      img.onload = function () {
        that._img = img;
        that._imgSrc = that.data.imagePath;
        that._paint(ctx, b || that.data.box, dpr);
      };
      img.src = that.data.imagePath;
    });
  },

  // 触摸开始：手柄优先 → 框内/线条内移动 → 空白按当前工具新建。
  // 矩形与线条共用同一套命中顺序与选中反馈，与权威 HTML 一致。
  onTouchStart: function (e) {
    if (!this.data.hasImage || this.data.processed || this.data.busy) return;
    const t = this._touchPos(e.touches && e.touches[0]);
    const p = {
      x: clamp(t.x, 0, this.data.displayW),
      y: clamp(t.y, 0, this.data.displayH)
    };
    const b = this.data.box;
    const that = this;

    // 线条命中：手柄缩放 / 内部移动，与矩形行为一致
    const hitLine = (idx) => {
      const pts = that.data.shapes[idx];
      if (!pts || !pts.length) return false;
      const sb = that._shapeBox(pts);
      const h = that._pickHandleAt(p, sb);
      if (h) {
        that._action = 'resizeLine'; that._handle = h; that._actIndex = idx;
        that._orig = Object.assign({}, sb);
        that._actPts = pts.map(q => ({ x: q.x, y: q.y }));
        that.data.sel = { kind: 'line', index: idx };
        that._drawBase();
        return true;
      }
      if (that._inBox(p, sb)) {
        that._action = 'moveLine'; that._actIndex = idx;
        that._orig = Object.assign({}, sb); that._start = p;
        that._actPts = pts.map(q => ({ x: q.x, y: q.y }));
        that.data.sel = { kind: 'line', index: idx };
        that._drawBase();
        return true;
      }
      return false;
    };

    // 1) 已选中的线条优先
    const s = this.data.sel;
    if (s && s.kind === 'line' && this.data.shapes[s.index] && hitLine(s.index)) return;
    // 2) 线条工具下从后往前检查所有线条
    if (this.data.tool === 'line') {
      for (let i = this.data.shapes.length - 1; i >= 0; i--) if (hitLine(i)) return;
    }

    // 3) 矩形手柄 → 框内移动（原有逻辑，行为不变）
    const handle = this._pickHandle(p);
    if (handle) {
      this._action = 'resize';
      this._handle = handle;
      this._orig = Object.assign({}, b);
      this._preview = Object.assign({}, b);
      this.data.sel = { kind: 'box', index: 0 };
      this._drawBase();
      return;
    }
    if (this._inBox(p, b)) {
      this._action = 'move';
      this._orig = Object.assign({}, b);
      this._start = p;
      this._preview = Object.assign({}, b);
      this.data.sel = { kind: 'box', index: 0 };
      this._drawBase();
      return;
    }

    // 4) 空白按下：按当前工具新建
    this.data.sel = null;
    this._linePts = null;
    if (this.data.tool === 'line') {
      this._action = 'drawLine';
      this._linePts = [p];
      this._drawBase();
      return;
    }
    this._action = 'draw';
    this._start = p;
    this._preview = { x: p.x, y: p.y, w: 0, h: 0 };
    this.setData({ drawing: true });
  },

  onTouchMove: function (e) {
    if (!this._action) return;
    const t = this._touchPos(e.touches && e.touches[0]);
    const p = { x: t.x, y: t.y };
    const W = this.data.displayW, H = this.data.displayH;

    // 正在画线条：按距离采样轨迹点，避免过密
    if (this._action === 'drawLine') {
      const last = this._linePts[this._linePts.length - 1];
      if (!last || Math.hypot(p.x - last.x, p.y - last.y) > 2) this._linePts.push(p);
      this._drawBase(); return;
    }
    // 线条整体移动：轨迹点同步平移（与矩形移动一致）
    if (this._action === 'moveLine') {
      const o = this._orig;
      const nx = clamp(o.x + p.x - this._start.x, 0, W - o.w);
      const ny = clamp(o.y + p.y - this._start.y, 0, H - o.h);
      this.data.shapes[this._actIndex] = this._actPts.map(q => ({ x: q.x + nx - o.x, y: q.y + ny - o.y }));
      this._drawBase(); return;
    }
    // 线条手柄缩放：线随框同步等比缩放，修复区域随之变化
    if (this._action === 'resizeLine') {
      const o = this._orig, hdl = this._handle;
      let x1 = o.x, y1 = o.y, x2 = o.x + o.w, y2 = o.y + o.h;
      if (hdl.indexOf('w') >= 0) x1 = clamp(p.x, 0, x2 - MIN_BOX);
      if (hdl.indexOf('e') >= 0) x2 = clamp(p.x, x1 + MIN_BOX, W);
      if (hdl.indexOf('n') >= 0) y1 = clamp(p.y, 0, y2 - MIN_BOX);
      if (hdl.indexOf('s') >= 0) y2 = clamp(p.y, y1 + MIN_BOX, H);
      const nb = { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
      const sx = o.w ? nb.w / o.w : 1, sy = o.h ? nb.h / o.h : 1;
      this.data.shapes[this._actIndex] = this._actPts.map(q => ({
        x: nb.x + (q.x - o.x) * sx,
        y: nb.y + (q.y - o.y) * sy
      }));
      this._drawBase(); return;
    }

    if (this._action === 'draw') {
      const x1 = clamp(Math.min(this._start.x, p.x), 0, W);
      const y1 = clamp(Math.min(this._start.y, p.y), 0, H);
      const x2 = clamp(Math.max(this._start.x, p.x), 0, W);
      const y2 = clamp(Math.max(this._start.y, p.y), 0, H);
      this._preview = { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
    } else if (this._action === 'move') {
      const o = this._orig;
      this._preview = {
        x: clamp(o.x + p.x - this._start.x, 0, W - o.w),
        y: clamp(o.y + p.y - this._start.y, 0, H - o.h),
        w: o.w, h: o.h
      };
    } else if (this._action === 'resize') {
      const o = this._orig, hdl = this._handle;
      let x1 = o.x, y1 = o.y, x2 = o.x + o.w, y2 = o.y + o.h;
      if (hdl.indexOf('w') >= 0) x1 = clamp(p.x, 0, x2 - MIN_BOX);
      if (hdl.indexOf('e') >= 0) x2 = clamp(p.x, x1 + MIN_BOX, W);
      if (hdl.indexOf('n') >= 0) y1 = clamp(p.y, 0, y2 - MIN_BOX);
      if (hdl.indexOf('s') >= 0) y2 = clamp(p.y, y1 + MIN_BOX, H);
      this._preview = { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
    }
    this._drawBase(this._preview);
  },

  onTouchEnd: function (e) {
    if (!this._action) return;
    const action = this._action;
    this._action = null;
    this._handle = null;
    const p = this._touchPos(e.changedTouches && e.changedTouches[0]);

    // 线条画完：至少 3 点才成环，首尾自动闭合并选中
    if (action === 'drawLine') {
      const pts = this._linePts || [];
      this._linePts = null;
      this.setData({ drawing: false });
      if (pts.length >= 3) {
        this.data.shapes.push(pts.slice());
        this.data.sel = { kind: 'line', index: this.data.shapes.length - 1 };
        this.setData({ shapes: this.data.shapes.slice(), sel: this.data.sel });
      }
      this._drawBase(); return;
    }
    if (action === 'moveLine' || action === 'resizeLine') {
      this.setData({ shapes: this.data.shapes.slice() });
      this._drawBase(); return;
    }

    if (action === 'draw') {
      if (p) {
        const x1 = clamp(Math.min(this._start.x, p.x), 0, this.data.displayW);
        const y1 = clamp(Math.min(this._start.y, p.y), 0, this.data.displayH);
        const x2 = clamp(Math.max(this._start.x, p.x), 0, this.data.displayW);
        const y2 = clamp(Math.max(this._start.y, p.y), 0, this.data.displayH);
        if (x2 - x1 > MIN_BOX && y2 - y1 > MIN_BOX) {
          this._preview = { x: Math.round(x1), y: Math.round(y1), w: Math.round(x2 - x1), h: Math.round(y2 - y1) };
        }
      }
    }
    this.setData({ drawing: false });
    if (this._preview && this._preview.w >= MIN_BOX && this._preview.h >= MIN_BOX) {
      const box = {
        x: Math.round(this._preview.x), y: Math.round(this._preview.y),
        w: Math.round(this._preview.w), h: Math.round(this._preview.h)
      };
      this.data.sel = { kind: 'box', index: 0 };
      this.setData({ box: box, sel: this.data.sel });
      this._drawBase(box);
    } else {
      this._drawBase(this.data.box);
    }
  },

  // 自动框右下角（常见平台水印位置；配合修复时的自动外扩兜边）
  autoBox: function () {
    if (!this.data.hasImage) return;
    const bw = this.data.displayW * 0.24, bh = this.data.displayH * 0.07;
    const box = {
      x: Math.round(this.data.displayW - bw - 8),
      y: Math.round(this.data.displayH - bh - 8),
      w: Math.max(10, Math.round(bw)),
      h: Math.max(10, Math.round(bh))
    };
    this.setData({ box: box, sel: { kind: 'box', index: 0 } });
    this._drawBase(box);
    wx.showToast({ title: '已框右下角，可拖动手柄微调', icon: 'none' });
  },

  clearBox: function () {
    this.setData({ box: null, shapes: [], sel: null });
    this._preview = null;
    this._linePts = null;
    this._drawBase();
  },

  adjustBox: function (e) {
    if (!this.data.box) { wx.showToast({ title: '请先框选区域', icon: 'none' }); return; }
    const d = parseInt(e.currentTarget.dataset.d, 10) || 0;
    const b = this.data.box;
    const x1 = Math.max(0, b.x - d), y1 = Math.max(0, b.y - d);
    const x2 = Math.min(this.data.displayW, b.x + b.w + d);
    const y2 = Math.min(this.data.displayH, b.y + b.h + d);
    if (x2 - x1 < MIN_BOX || y2 - y1 < MIN_BOX) return;
    const box = { x: Math.round(x1), y: Math.round(y1), w: Math.round(x2 - x1), h: Math.round(y2 - y1) };
    this.setData({ box: box, sel: { kind: 'box', index: 0 } });
    this._drawBase(box);
  },

  // 工具切换：矩形框选 / 线条去除，两类状态互相隔离
  setTool: function (e) {
    const key = (e.currentTarget.dataset.key === 'line') ? 'line' : 'rect';
    this._linePts = null;
    this.setData({
      tool: key,
      toolHint: key === 'line'
        ? '沿目标画一圈闭合线条，松开自动闭合；点线条选中，拖小手柄缩放'
        : '在图片上拖拽框住水印；点框选中，拖手柄缩放'
    });
    this._drawBase();
    wx.showToast({ title: key === 'line' ? '线条去除：沿目标画一圈' : '矩形框选：拖拽框住水印', icon: 'none' });
  },

  // 撤销：优先撤销选中项，否则撤销最后添加的线条 / 框（矩形与线条一致）
  undoMark: function () {
    const s = this.data.sel;
    if (s && s.kind === 'line' && this.data.shapes[s.index]) this.data.shapes.splice(s.index, 1);
    else if (s && s.kind === 'box' && this.data.box) this.data.box = null;
    else if (this.data.shapes.length) this.data.shapes.pop();
    else if (this.data.box) this.data.box = null;
    this.data.sel = null;
    this._linePts = null;
    this._preview = null;
    this.setData({ box: this.data.box, shapes: this.data.shapes.slice(), sel: null });
    this._drawBase();
    wx.showToast({ title: '已撤销', icon: 'none' });
  },

  // 顶部「下一页」入口：与底部「重新选图」一致，重置为可上传下一张的状态
  nextPage: function () {
    if (!this.data.hasImage) { wx.showToast({ title: '当前还没有图片', icon: 'none' }); return; }
    this.reset();
  },

  setFramework: function (e) {
    const key = e.currentTarget.dataset.key;
    this.setData({ framework: key });
    // 选提示词框架时若提示词为空，给一次友好提醒（不强制填写）
    if (key === 'prompt' && !this.data.promptText.trim()) {
      wx.showToast({ title: '可填写提示词，或留空用智能扩散', icon: 'none' });
    }
  },

  onPromptInput: function (e) {
    const text = (e.detail.value || '').slice(0, 300);
    const info = promptUtil.parsePrompt(text);
    this.setData({ promptText: text, promptIntent: info.intent });
  },

  useExamplePrompt: function () {
    const text = promptUtil.EXAMPLE;
    this.setData({ promptText: text, promptIntent: promptUtil.parsePrompt(text).intent });
    wx.showToast({ title: '已填入示例提示词', icon: 'none' });
  },

  toggleAuth: function () {
    this.setData({ authorized: !this.data.authorized });
  },

  // 核心：执行修复
  process: function () {
    const that = this;
    if (!this.data.box && !this.data.shapes.length) {
      wx.showToast({ title: '请先框选或画线条圈住要修复的区域', icon: 'none' }); return;
    }
    if (!this.data.authorized) { wx.showToast({ title: '请先勾选使用确认', icon: 'none' }); return; }
    this._t0 = Date.now();
    this.setData({ busy: true });
    wx.showLoading({ title: '修复中…' });

    // 原图分辨率离屏处理。wx.createOffscreenCanvas 需基础库 2.16.1+，
    // 老版本退回到页面上隐藏的 type=2d 画布（#offstage）。
    if (wx.createOffscreenCanvas) {
      const off = wx.createOffscreenCanvas({ type: '2d', width: that._originW, height: that._originH });
      that._runRepair(off, off.getContext('2d'), function (cb) {
        wx.canvasToTempFilePath({ canvas: off, success: cb.success, fail: cb.fail });
      });
    } else {
      wx.createSelectorQuery().in(that).select('#offstage').fields({ node: true, size: true }).exec(function (res) {
        const node = res[0] && res[0].node;
        if (!node) {
          wx.hideLoading(); that.setData({ busy: false });
          wx.showToast({ title: '当前微信版本过低，请升级', icon: 'none' });
          return;
        }
        node.width = that._originW; node.height = that._originH;
        that._runRepair(node, node.getContext('2d'), function (cb) {
          wx.canvasToTempFilePath({ canvas: node, success: cb.success, fail: cb.fail });
        });
      });
    }
  },

  // 在给定 canvas 上执行修复并导出
  _runRepair: function (off, octx, exportFn) {
    const that = this;
    const img = off.createImage();
    img.onload = function () {
      try {
        octx.drawImage(img, 0, 0, that._originW, that._originH);
        const imageData = octx.getImageData(0, 0, that._originW, that._originH);
        const s = 1 / that._scale;
        // 处理前的原图副本：线条 texture 模式据此取样（等价于 HTML 从原图画布 getImageData）
        const sourceData = new Uint8ClampedArray(imageData.data);
        const rect = that.data.box ? [{
          x: Math.round(that.data.box.x * s),
          y: Math.round(that.data.box.y * s),
          w: Math.round(that.data.box.w * s),
          h: Math.round(that.data.box.h * s)
        }] : [];

        // 提示词框架：按解析出的补全依据自动选择算法；其余框架直接用用户所选
        const info = promptUtil.parsePrompt(that.data.promptText);
        let mode = that.data.framework;
        if (mode === 'prompt') mode = info.framework || 'smart';
        const iters = app.globalData.algo.smartIterations;
        // 矩形：严格框内，外扩只作采样来源，框外像素一个字节都不改
        if (rect.length) inpaint.repairStrict(imageData, rect, mode, iters, { textureDetail: true });
        // 线条：与权威 HTML lineRemove 逐像素一致；回写（含锐化）严格限制在多边形内
        const regions = lineInpaint.repairLines(imageData, that.data.shapes, mode, iters, {
          scale: that._scale, sourceData: sourceData, sharpenAmount: 0.25
        });

        octx.putImageData(imageData, 0, 0);
        const ms = Date.now() - that._t0;
        exportFn({
          success: function (res) {
            that.setData({
              resultPath: res.tempFilePath, processed: true, busy: false,
              elapsedText: '耗时 ' + ms + ' ms · 仅修改框选/线条区域' +
                (regions.length ? ' · ' + regions.length + ' 条线条' : '')
            });
            wx.hideLoading();
            wx.showToast({ title: '修复完成 · ' + ms + 'ms', icon: 'success' });
          },
          fail: function () {
            wx.hideLoading(); that.setData({ busy: false });
            wx.showToast({ title: '导出失败，请重试', icon: 'none' });
          }
        });
      } catch (err) {
        wx.hideLoading(); that.setData({ busy: false });
        wx.showToast({ title: '处理失败：' + (err.message || '未知错误'), icon: 'none' });
      }
    };
    img.onerror = function () {
      wx.hideLoading(); that.setData({ busy: false });
      wx.showToast({ title: '图片加载失败', icon: 'none' });
    };
    img.src = that.data.imagePath;
  },

  // 保存到相册
  saveResult: function () {
    const that = this;
    if (!this.data.resultPath) return;
    wx.saveImageToPhotosAlbum({
      filePath: this.data.resultPath,
      success: function () { wx.showToast({ title: '已保存到相册', icon: 'success' }); },
      fail: function (err) {
        if (err.errMsg && err.errMsg.indexOf('auth') >= 0) {
          wx.showModal({
            title: '需要授权',
            content: '请在设置中允许保存到相册',
            confirmText: '去设置',
            success: function (r) { if (r.confirm) wx.openSetting(); }
          });
        } else {
          wx.showToast({ title: '保存失败', icon: 'none' });
        }
      }
    });
  },

  // 换下一张：只清图片与框，保留框架/提示词/授权
  reset: function () {
    this._img = null;
    this._preview = null;
    this._linePts = null;
    this.setData({
      hasImage: false, box: null, shapes: [], sel: null,
      resultPath: '', processed: false, elapsedText: ''
    });
    wx.showToast({ title: '请选择下一张照片', icon: 'none' });
  },

  goPrivacy: function () {
    wx.navigateTo({ url: '/pages/privacy/privacy' });
  }
});
