const inpaint = require('../../utils/inpaint.js');

const app = getApp();

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
    // 处理结果
    resultPath: '',
    processed: false,
    busy: false,
    // 设置
    mode: 'smart',
    modeDesc: {
      smart: '智能修复：根据水印四周颜色向内推算，纯色/渐变背景近乎无痕（推荐）',
      average: '快速填充：取边缘颜色平铺，适合面积很小、背景单一的水印',
      texture: '纹理修复：对木纹、草地等纹理背景整框扩散重建，彻底去除文字、不留残影'
    },
    modes: [
      { key: 'smart', label: '智能修复' },
      { key: 'average', label: '快速填充' },
      { key: 'texture', label: '纹理修复' }
    ],
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
        that.setData({
          imagePath: path,
          displayW: dw,
          displayH: dh,
          hasImage: true,
          processed: false,
          box: null,
          resultPath: ''
        }, function () {
          that._drawBase();
        });
      },
      fail: function () {
        wx.showToast({ title: '图片读取失败，请换一张', icon: 'none' });
      }
    });
  },

  // 画原图 + 框（基础 canvas 2d 绘制）
  _drawBase: function (box) {
    const that = this;
    const query = wx.createSelectorQuery().in(this);
    // rect: true 同时取 canvas 在视口中的位置，用于触摸坐标兜底换算
    query.select('#stage').fields({ node: true, size: true, rect: true }).exec(function (res) {
      const canvas = res[0] && res[0].node;
      if (!canvas) return;
      // 缓存画布屏幕位置（触摸事件仅提供 clientX/clientY 时的兜底）
      that._rect = { left: res[0].left || 0, top: res[0].top || 0 };
      const ctx = canvas.getContext('2d');
      const dpr = that._getDpr();
      canvas.width = that.data.displayW * dpr;
      canvas.height = that.data.displayH * dpr;
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, that.data.displayW, that.data.displayH);
      const img = canvas.createImage();
      img.onload = function () {
        ctx.drawImage(img, 0, 0, that.data.displayW, that.data.displayH);
        const b = box || that.data.box;
        if (b) {
          ctx.strokeStyle = '#0F9E8E';
          ctx.lineWidth = 2;
          ctx.setLineDash([6, 4]);
          ctx.strokeRect(b.x, b.y, b.w, b.h);
          ctx.fillStyle = 'rgba(15,158,142,0.12)';
          ctx.fillRect(b.x, b.y, b.w, b.h);
        }
      };
      img.src = that.data.imagePath;
    });
  },

  // 触摸开始
  onTouchStart: function (e) {
    if (!this.data.hasImage || this.data.processed) return;
    const t = this._touchPos(e.touches && e.touches[0]);
    // 钳制到画布范围内，保证框选坐标合法
    this._sx = Math.max(0, Math.min(t.x, this.data.displayW));
    this._sy = Math.max(0, Math.min(t.y, this.data.displayH));
    this.setData({ drawing: true });
  },

  // 触摸移动
  onTouchMove: function (e) {
    if (!this.data.drawing) return;
    const t = this._touchPos(e.touches[0]);
    const x = Math.min(this._sx, t.x), y = Math.min(this._sy, t.y);
    const w = Math.abs(t.x - this._sx), h = Math.abs(t.y - this._sy);
    this._drawBase({ x: x, y: y, w: w, h: h });
  },

  // 触摸结束
  onTouchEnd: function (e) {
    if (!this.data.drawing) return;
    const ct = e.changedTouches && e.changedTouches[0];
    this.setData({ drawing: false });
    if (!ct) { this._drawBase(this.data.box); return; }
    const t = this._touchPos(ct);
    const x = Math.min(this._sx, t.x), y = Math.min(this._sy, t.y);
    const w = Math.abs(t.x - this._sx), h = Math.abs(t.y - this._sy);
    // 钳制到画布内，避免手指拖出画布产生负坐标框
    const maxW = this.data.displayW, maxH = this.data.displayH;
    const cx = Math.max(0, Math.min(x, maxW - 1));
    const cy = Math.max(0, Math.min(y, maxH - 1));
    const cw = Math.min(w, maxW - cx), ch = Math.min(h, maxH - cy);
    if (cw > 8 && ch > 8) {
      const box = { x: Math.round(cx), y: Math.round(cy), w: Math.round(cw), h: Math.round(ch) };
      this.setData({ box: box });
      this._drawBase(box);
      wx.showToast({ title: '已框选区域', icon: 'success' });
    } else {
      this._drawBase(this.data.box);
    }
  },

  // 自动框右下角（常见平台水印位置；比例贴近实际水印，配合修复时的自动外扩兜边）
  autoBox: function () {
    if (!this.data.hasImage) return;
    const bw = this.data.displayW * 0.24, bh = this.data.displayH * 0.07;
    const box = {
      x: Math.round(this.data.displayW - bw - 8),
      y: Math.round(this.data.displayH - bh - 8),
      w: Math.max(10, Math.round(bw)),
      h: Math.max(10, Math.round(bh))
    };
    this.setData({ box: box });
    this._drawBase(box);
    wx.showToast({ title: '已框右下角，可拖动重框微调', icon: 'none' });
  },

  clearBox: function () {
    this.setData({ box: null });
    this._drawBase();
  },

  // 微调框大小：data-d 为每边调整像素（正=扩大，负=缩小）
  adjustBox: function (e) {
    if (!this.data.box) { wx.showToast({ title: '请先框选区域', icon: 'none' }); return; }
    const d = parseInt(e.currentTarget.dataset.d, 10) || 0;
    const b = this.data.box;
    const x1 = Math.max(0, b.x - d), y1 = Math.max(0, b.y - d);
    const x2 = Math.min(this.data.displayW, b.x + b.w + d);
    const y2 = Math.min(this.data.displayH, b.y + b.h + d);
    if (x2 - x1 < 10 || y2 - y1 < 10) return; // 防止缩没
    const box = { x: Math.round(x1), y: Math.round(y1), w: Math.round(x2 - x1), h: Math.round(y2 - y1) };
    this.setData({ box: box });
    this._drawBase(box);
  },

  setMode: function (e) {
    this.setData({ mode: e.currentTarget.dataset.key });
  },

  toggleAuth: function () {
    this.setData({ authorized: !this.data.authorized });
  },

  // 核心：执行修复
  process: function () {
    const that = this;
    if (!this.data.box) { wx.showToast({ title: '请先框选要修复的区域', icon: 'none' }); return; }
    if (!this.data.authorized) { wx.showToast({ title: '请先勾选使用确认', icon: 'none' }); return; }
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
        const rect = [{
          x: Math.round(that.data.box.x * s),
          y: Math.round(that.data.box.y * s),
          w: Math.round(that.data.box.w * s),
          h: Math.round(that.data.box.h * s)
        }];
        inpaint.repair(imageData, rect, that.data.mode, app.globalData.algo.smartIterations);
        octx.putImageData(imageData, 0, 0);

        exportFn({
          success: function (res) {
            that.setData({ resultPath: res.tempFilePath, processed: true, busy: false });
            wx.hideLoading();
            wx.showToast({ title: '修复完成', icon: 'success' });
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

  reset: function () {
    this.setData({
      hasImage: false, box: null, resultPath: '', processed: false, authorized: false
    });
  },

  // 跳转用户协议与隐私政策
  goPrivacy: function () {
    wx.navigateTo({ url: '/pages/privacy/privacy' });
  }
});
