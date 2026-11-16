# GitHub 去水印开源项目调研报告

> 调研日期：2026-11-16
> 项目目标：处理本人有权处理的个人内容（小红书、抖音等平台自有内容）水印，支持图片/视频输入，完成识别 → 去除 → 画质修复，尽量保留原始细节与清晰度。
> 用途定位：**二次开发选型参考**。所有方案仅用于处理自有或已获授权内容，遵守平台服务条款与相关法律法规。

---

## 〇、核心结论：两条技术路线

调研发现，所谓"去水印"实际存在两条完全不同的技术路线，选型前必须先分清：

| 路线 | 原理 | 画质 | 稳定性 | 适用场景 | 代表项目 |
|---|---|---|---|---|---|
| **A. 源头解析（去水印=取原图）** | 通过平台分享链接解析出平台存储的**无水印原始资源** | ⭐⭐⭐⭐⭐ 无损 | 较低（依赖平台接口，易失效） | 小红书/抖音**自己刚发布的内容**、公开无水印源 | parse-video、parse-video-py |
| **B. AI 图像修复（Inpainting）** | 检测水印区域 → 生成掩码 → AI 重建像素 | ⭐⭐⭐ 有损但自然 | 高（本地运行，不依赖接口） | 已保存的、只有水印版本的图片/视频 | IOPaint/LaMA、DeMark-World |

**推荐策略：双引擎融合。**
- 若是"自己账号刚发布的内容"：优先走路线 A，直接拿到无水印原图/原视频，**画质零损失**，这是最理想的结果。
- 若手里只有带水印的成品文件：走路线 B，用 AI 修复擦除，再用超分/人脸修复补足画质。
- 路线 A 作为"优先通道"，失败时自动回退到路线 B。

> ⚠️ 合规提示：路线 A 的解析类项目用于抓取他人内容会涉及版权与平台条款风险。本项目**仅限处理自己有权处理的内容**，代码中应加入用途声明与授权确认环节。

---

## 一、重点推荐项目（可用于二次开发）

### 1. IOPaint（原 lama-cleaner）⭐ 图片处理首选基座

- **链接**：https://github.com/Sanster/IOPaint
- **Star**：约 23.3k ｜ **许可证**：Apache-2.0 ｜ **活跃度**：2025 年仍有提交（最近 2025-04）
- **特点**：
  - SOTA AI 修复，支持擦除（LaMA）、替换（PowerPaint）、文字绘制（AnyText）、外扩
  - 明确支持"remove watermarks"场景
  - 完全本地自托管，支持 CPU / GPU / Apple Silicon
  - 交互式分割（SAM）、批量处理、命令行、FileManager
  - 前端为独立 React/Vite 工程（`web_app/`），**界面可直接二次开发**
- **可复用模块**：
  - `iopaint/model/` 下各类 erase 模型封装（LaMA/MAT/ZITS 等），可单独抽出水印擦除能力
  - 插件体系：RealESRGAN 超分、GFPGAN/RestoreFormer 人脸修复、RemoveBG、SAM
  - `iopaint run` 批量 CLI：`--image` + `--mask` 目录即可批处理
  - 后端 FastAPI + 前端 React 分离架构，便于封装成自有 API 服务
- **选型理由**：许可证宽松、功能最全、生态成熟，是图片去水印 + 修复的**最佳二次开发基座**。

---

### 2. DeMark-World ⭐ 视频处理首选基座

- **链接**：https://github.com/linkedlist771/DeMark-World
- **许可证**：Apache-2.0 ｜ **活跃度**：2025 年新项目（由 SoraWatermarkCleaner 演进而来）
- **特点**：
  - 通用 AI 视频去水印框架，面向 Sora/Runway/Pika/Kling/Veo 等，两阶段流水线设计通用性强
  - **检测**：YOLO 逐帧检测水印框，邻帧区间均值回填漏检 → 可直接替换/训练成小红书、抖音水印检测器
  - **修复**：双后端可选 —— LaMa（快，静态水印）/ E2FGVI-HQ（时序一致，无闪烁，动态内容）
  - 四种接口：Web UI（Streamlit）、Python API、CLI、REST Server（队列异步），含 Docker GPU 编排
  - 性能优化：批量 YOLO、BF16、torch.compile 缓存
- **可复用模块**：
  - `src/demark_world/core` 的 `DeMarkWorld` 类 + `CleanerType` 枚举 —— 上传视频后一行调用
  - 检测→修复两阶段流水线，可拆出"检测服务"与"修复服务"
  - REST Server 的 `submit_remove_task` / `get_results` / `get_queue_status` / `download` 接口，可直接做前后端分离的异步任务
  - E2FGVI-HQ 时序修复模块，解决视频去水印的"闪烁"痛点
- **选型理由**：视频去水印里架构最完整、许可证宽松、异步 API 现成，适合做服务端核心引擎。

---

### 3. Real-ESRGAN ⭐ 画质修复/超分标配

- **链接**：https://github.com/xinntao/Real-ESRGAN
- **Star**：约 37.5k ｜ **许可证**：BSD-3-Clause ｜ **活跃度**：2022 年后趋于稳定（经典项目）
- **特点**：
  - 通用图像/视频超分辨率与修复（去压缩伪影、去噪、放大）
  - 图片、视频均有推理脚本；提供免 PyTorch 的 NCNN 便携 exe（Windows/Linux/macOS）
  - 集成 GFPGAN 人脸增强；支持动漫专用模型
  - 腾讯 ARC Lab 出品，工业界事实标准
- **可复用模块**：
  - `inference_realesrgan.py`（图片）/ `inference_realesrgan_video.py`（视频）—— 直接作为修复流水线最后一环
  - `realesrgan/` 网络结构定义，可嵌入自定义服务
  - 便携 exe 可打包进桌面端，降低用户部署门槛
- **选型理由**：画质修复环节的事实标准，BSD 许可证极宽松，作为"修"的最后一环。

---

### 4. WatermarkRemover-AI ⭐ 检测+修复一体化（带 GUI）

- **链接**：https://github.com/Geetansh-Jangid/WatermarkRemover-AI （README 内亦指向 D-Ogi/WatermarkRemover-AI）
- **许可证**：见仓库 LICENSE ｜ **活跃度**：2025 年底仍在更新（i18n、主题、中国镜像支持）
- **特点**：
  - **Florence-2（微软多模态模型）做智能检测** + **LaMA 做修复**，检测与修复解耦
  - 图片 + 视频（两遍检测、保留音频）；批量处理；预览模式；淡入淡出水印掩码扩展
  - PyWebview 现代 GUI，多语言（含中文）、配置持久化、多主题
  - Windows 一键脚本（自动下载便携 Python）、支持国内镜像
- **可复用模块**：
  - `remwm.py` CLI、`utils.py` 工具、`remwmgui.py` GUI —— Florence-2 检测思路值得借鉴
  - 两遍检测（two-pass）+ 音频保留的视频处理流程
  - 中文本地化与国内镜像配置，可直接复用
- **选型理由**：提供了"自动检测"这一环节的参考实现，GUI 交互设计可借鉴。

---

### 5. gemini-watermark-remover（特定水印无损方案）

- **链接**：https://github.com/GargantuaX/gemini-watermark-remover
- **Star**：约 5.6k ｜ **许可证**：MIT（基于 AllenK 的 Reverse Alpha Blending 方法）｜ **活跃度**：2026 年仍活跃
- **特点**：
  - **纯 JavaScript、100% 浏览器本地**，无需上传
  - 数学精确的"反向 Alpha 混合"——**无损**去除，非 AI 幻觉式生成
  - 自动检测水印尺寸位置；图片 + 视频；浏览器扩展/Userscript/CLI/Skill 多形态
- **可复用模块**：
  - Reverse Alpha Blending 算法核心 —— 对**已知的、固定模板的合成水印**可实现像素级无损去除
  - 前端纯 JS 实现，可直接移植到 HTML 页面（离线、隐私友好）
- **选型理由**：对"固定模板水印"提供无损思路；但其针对特定 AI 水印，通用性有限。**启发**：若小红书/抖音水印是固定位置固定图样，可探索类似的模板匹配+逆向混合，实现比 AI 修复更保真的效果。

---

## 二、平台解析类项目（路线 A：源头取无水印）

### 6. parse-video-py ⭐ Python 解析首选

- **链接**：https://github.com/fluidcat/parse-video-py
- **许可证**：见仓库 LICENSE ｜ **活跃度**：2025 年仍在更新（MCP、高清地址修复）
- **支持平台**：视频 20+（抖音、小红书、快手、B站、微博等）；图集（抖音/快手/小红书/皮皮虾）；小红书 LivePhoto
- **特点**：Python ≥3.10，FastAPI 接口，Docker，已支持 MCP（StreamableHttp）
- **可复用模块**：解析模块、FastAPI 路由、`main.py` 的 MCP 接入；小红书图集高清地址修复逻辑
- **注意**：解析接口依赖平台，稳定性随时间下降，需持续维护；仅用于自有内容。

### 7. parse-video（Go 版）

- **链接**：https://github.com/yibele/parse-video
- **许可证**：见仓库 ｜ **活跃度**：2025-08 更新（新增 MCP 支持）
- **特点**：Go 实现，同样支持 20+ 平台，stdib/SSE 双传输 MCP，5 个核心解析工具
- **可复用模块**：Go 解析器可作为独立微服务；`parser.ParseVideoShareUrl` / `ParseVideoId` 接口
- **选型建议**：若服务端用 Go 生态选它，否则优先 Python 版。

---

## 三、其他值得关注的项目

| 项目 | 链接 | 特点 | 许可证/活跃度 |
|---|---|---|---|
| MinerU Tianshu 天枢 | https://github.com/readmagic/mineru-tianshu | 2025-10 新增水印去除：YOLO11x 检测 + LaMa 修复，支持图片/PDF，可调置信度与范围 | 见仓库 / 2025 活跃 |
| Clean PicGo | https://github.com/thyenergy/cleanup | 浏览器本地 LaMa 擦除 + Gemini 无损模式 + Web Worker + PWA + 实时对比 + 高清导出 | 见仓库 / 2025-12 |
| xiaobai-watermark-remover | https://github.com/Baishukai/xiaobai-watermark-remover | OpenCV vs LaMA 效果对比（LaMa 优约 40%）、手动标记、big-lama.pt 本地化、CPU 可跑 | 见仓库 / 2025-12 |
| DeMark-World 前身 | https://github.com/linkedlist771/SoraWatermarkCleaner | 专注 Sora 视频水印，DeMark-World 的演进基础 | Apache-2.0 |

---

## 四、许可证与合规汇总

| 项目 | 许可证 | 商用/二开友好度 |
|---|---|---|
| IOPaint | Apache-2.0 | ✅ 友好，需保留声明 |
| DeMark-World | Apache-2.0 | ✅ 友好 |
| Real-ESRGAN | BSD-3-Clause | ✅ 极友好 |
| gemini-watermark-remover | MIT | ✅ 极友好 |
| parse-video / parse-video-py | 见各仓库 LICENSE | ⚠️ 需自行核对 |

**合规红线（务必内置到产品流程）：**
1. 仅处理**自己创作或已获明确授权**的内容；去除水印不等于获得版权。
2. 不得用于去除他人作品的版权水印、署名、平台标识并再分发。
3. 解析类能力遵守目标平台服务条款，不做批量抓取。
4. 产品内加入"用途声明 / 授权确认"步骤，保留处理日志。

---

## 五、推荐技术栈组合（最终选型）

```
路线 A（优先）: parse-video-py  → 拿到无水印原图/原视频（画质无损）
        ↓ 失败/无源
路线 B（兜底）: 
   检测层  : YOLO（DeMark-World 检测器）或 Florence-2 / OCR，定位水印框
   掩码层  : SAM 交互式分割 / 固定模板匹配
   擦除层  : LaMA（IOPaint 封装）— 图片；E2FGVI-HQ — 视频时序一致
   修复层  : Real-ESRGAN 超分 + GFPGAN 人脸增强
   编排层  : Python FastAPI 异步任务队列（参考 DeMark-World REST Server）
   界面层  : HTML 原型 → 可选 Skill / 小程序
```

**可复用模块优先级（P0 必用 / P1 推荐 / P2 可选）：**
- P0：IOPaint LaMA 擦除、DeMark-World 检测+视频修复、Real-ESRGAN
- P1：parse-video-py 源头解析、SAM 分割、GFPGAN 人脸增强
- P2：Florence-2 检测、Reverse Alpha Blending（固定模板无损）、Clean PicGo 前端交互
