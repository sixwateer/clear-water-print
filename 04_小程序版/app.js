App({
  globalData: {
    appName: '净像 · 图片修复',
    version: '1.0.0',
    // 算法参数（集中管理，便于修改）
    algo: {
      smartIterations: 240,   // 智能修复迭代次数
      pad: 2
    },
    // 合规提示文案
    compliance: '请仅处理自己创作或已获授权的内容。去除水印不等于获得版权。'
  }
});
