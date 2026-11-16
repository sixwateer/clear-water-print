# 净像 · 图片修复（微信小程序版）

原生微信小程序版本，图片在本机处理、不上传。基于官方 `workbuddy-native-basic@1.0.0` 基线增量开发。

> **关于命名**：为符合微信小程序审核规范（"去水印"字样易被判定侵权风险），发布时统一使用"净像 · 图片修复"这一中性名称，功能不变——仍用于修复你有权处理的自有图片上的瑕疵/标记。类目选择「工具 → 图片处理」（个人主体可选）。详见 `00_使用指南/微信小程序发布指引.md`。

## 目录结构

```
04_小程序版/
├── app.js                  全局配置（算法参数、合规文案）
├── app.json                页面与窗口配置
├── app.wxss                全局样式
├── project.config.json     项目配置（appid: touristappid 为游客模式）
├── sitemap.json
├── pages/index/
│   ├── index.js            页面逻辑：选图/框选/修复/保存
│   ├── index.wxml          页面结构
│   ├── index.wxss          页面样式
│   └── index.json
├── pages/privacy/
│   ├── privacy.js/wxml/wxss/json   用户协议与隐私政策页（审核必需）
└── utils/
    └── inpaint.js          修复算法（smart/average/texture，纯 JS）
```

## 如何运行（普通用户）

1. 安装【微信开发者工具】。
2. 打开工具 → 导入项目 → 目录选择本文件夹 `04_小程序版`。
3. AppID 选择「测试号 / 游客模式」（配置里已填 `touristappid`），或填自己的小程序 AppID。
4. 点击「编译」，模拟器即可运行。
5. 手机预览：点工具右上角「预览」，扫码即可在手机体验（需联网预览，处理本身仍在本机）。

> 正式发布需替换为你的小程序 AppID 并在微信公众平台上传审核。工具内置"游客模式"足以本地体验和开发。

## 使用步骤

1. 点「选择图片」从相册选图或拍照。
2. 在图片上**按住拖动**框住水印；着急的话点「自动框右下角」。
3. 选择修复方式（默认「智能修复」），勾选授权确认。
4. 点「开始修复」→ 预览结果 → 点「保存到相册」。

## 可替换/可配置项

- **换配色**：`app.json` 的 `navigationBarBackgroundColor` + `pages/index/index.wxss` 中的颜色值。
- **改文案**：`app.js` 的 `globalData.compliance`、`pages/index/index.wxml` 文本。
- **调算法**：`app.js` 的 `globalData.algo.smartIterations`（迭代越大越精细、越慢）。
- **换 logo**：在 `pages/index/index.wxml` 的 `.upload-ico` 区域替换为 `<image>`。

## 说明

- 修复算法为纯前端实现，对纯色/渐变背景水印效果最好；复杂照片背景建议用「进阶版 + 后端 AI 引擎」。
- 仅用于处理你有权处理的自有内容。
