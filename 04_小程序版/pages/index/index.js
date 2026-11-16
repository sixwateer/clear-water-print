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
      smart: '智能修复：适合纯色/渐变背景，近乎无痕（推荐）',
      average: '快速填充：适合小面积水印，速度最快',
      texture: '纹理平移：适合草地、砖墙等重复纹理背景'
    },
    modes: [
      { key: 'smart', label: '智能修复' },
      { key: 'average', label: '快速填充' },
      { key: 'texture', label: '纹理平移' }
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

  // 读取触摸点相对画布的坐标，部分机型只提供 clientX/clientY
  _touchPos: function (t) {
    return {
      x: (t.x != null ? t.x : t.clientX) || 0,
      y: (t.y != null ? t.y : t.clientY) || 0
    };
  },

  // 选择图片
  chooseImage: function () {
    const that = this;
    wx.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sourceType: ['album', 'camera'],
      success: function (res) {
        const path = res.tempFiles[0].tempFilePath;
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
          }
        });
      }
    });
  },

  // 画原图 + 框（基础 canvas 2d 绘制）
  _drawBase: function (box) {
    const that = this;
    const query = wx.createSelectorQuery().in(this);
    query.select('#stage').fields({ node: true, size: true }).exec(function (res) {
      const canvas = res[0].node;
      const ctx = canvas.getContext('2d');
      const dpr = this._getDpr();
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
    const t = this._touchPos(e.touches[0]);
    this.setData({ drawing: true });
    this._sx = t.x; this._sy = t.y;
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
    const t = this._touchPos(e.changedTouches[0]);
    const x = Math.min(this._sx, t.x), y = Math.min(this._sy, t.y);
    const w = Math.abs(t.x - this._sx), h = Math.abs(t.y - this._sy);
    this.setData({ drawing: false });
    if (w > 8 && h > 8) {
      const box = { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) };
      this.setData({ box: box });
      this._drawBase(box);
      wx.showToast({ title: '已框选水印', icon: 'success' });
    }
  },

  // 自动框右下角
  autoBox: function () {
    if (!this.data.hasImage) return;
    const bw = this.data.displayW * 0.3, bh = this.data.displayH * 0.12;
    const box = {
      x: Math.round(this.data.displayW - bw - 8),
      y: Math.round(this.data.displayH - bh - 8),
      w: Math.round(bw), h: Math.round(bh)
    };
    this.setData({ box: box });
    this._drawBase(box);
    wx.showToast({ title: '已自动框右下角', icon: 'none' });
  },

  clearBox: function () {
    this.setData({ box: null });
    this._drawBase();
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
    if (!this.data.box) { wx.showToast({ title: '请先框选水印', icon: 'none' }); return; }
    if (!this.data.authorized) { wx.showToast({ title: '请先勾选使用确认', icon: 'none' }); return; }
    this.setData({ busy: true });
    wx.showLoading({ title: '修复中…' });

    const off = wx.createOffscreenCanvas({ type: '2d', width: that._originW, height: that._originH });
    const octx = off.getContext('2d');
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

        wx.canvasToTempFilePath({
          canvas: off,
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
  }
});
