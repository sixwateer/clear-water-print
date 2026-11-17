# 净像 · 去水印后端服务

为 `02_HTML版/原始原型_对接后端版.html` 提供真实图片去水印能力的 FastAPI 服务。**v2 采用双引擎融合架构**：源头解析 → 反向Alpha无损 → AI修复流水线 → OpenCV兜底，失败自动回退。

> 目录已从旧的 `code/` 迁移到 `05_后端引擎/`，本文路径均已更新。若只想去水印不想配置后端，请直接用 `02_HTML版/净像去水印_普通版_双击即用.html`。

## 特性

- **双引擎融合（v2）**：引擎A 源头解析（无损）→ 反向Alpha混合（固定模板无损）→ 引擎B AI修复（检测→擦除→修复）→ OpenCV 兜底
- **自动回退**：单引擎失败按回退链自动尝试下一引擎，全程状态轨迹可观测
- **像素级无损**：反向Alpha混合代数逆运算，固定模板水印误差 ≤ 1
- **开箱即用**：基础依赖装完即可跑通闭环，AI 模型未装时各步自动降级
- **合规设计**：授权未确认直接终止；前端内置授权勾选
- **清晰扩展**：统一 `FusionEngine` 契约，新增引擎不改编排逻辑

> 完整架构、选择逻辑、回退条件、异常契约见仓库根目录的 `双引擎融合架构与集成文档.md`。

## 本次更新（功能入口 / 修改点速查）

| 你关心的点 | 去哪里看 / 改 | 说明 |
|---|---|---|
| 服务怎么启动 | `start.bat` 或 `python server.py` | 唯一入口是 `server.py`，末尾 `uvicorn.run(...)` 改端口 |
| 智能识别（自动选方式） | `POST /api/v2/detect` + `engines/opencv_engine.py::detect_content` | 框选后识别纯色/渐变/纹理/照片，返回推荐引擎与方式 |
| 纹理自然融合 | `engines/opencv_engine.py::inpaint(method="auto")` | 文字水印走"笔画级"修复保留木纹；色块走源块羽化融合 |
| 前端引擎通俗说明 | `api_v2.py::get_engines` 的 `engine_guide` | 前端"选择引擎"区展示的名称/说明来自这里 |
| 选框交互（单选/拖拽/缩放） | `02_HTML版/*.html` 的画布交互区 | 两页统一：只保留一个框、可拖动移动、8 向手柄缩放 |
| 启动自检与依赖 | `python server.py --check` / `start.bat` | 自检打印解释器、依赖版本、引擎状态、8000 端口占用；`start.bat` 自动跳过微软商店占位符 Python |
| 输入校验 / 异常处理 | `api_v2.py::_parse_rects`、`process_fusion` | 非法 rects 统一返回 400；处理异常兜底 500 且任务状态正确落库；任务存储有上限 |
| 修复框架 / 提示词 | `api_v2.py::parse_prompt`、`resolve_framework` | `framework=prompt` 时按提示词解析结果自动选 smart/texture/average，规则与小程序 `utils/prompt.js` 一致 |
| 严格框内约束 | `api_v2.py::compose_strict` | 默认把原图框外像素贴回结果图，保证「仅框选区域被修改」，source_url 场景无原图时跳过 |

> 注意：前端两版（普通版 / 后端对接版）选框交互与视觉规范已保持一致；普通版纯前端即可用，后端版需先启动本服务。

## 快速开始（Windows）

1. 双击 `start.bat`（自动寻找装了依赖的 Python，跳过微软商店占位符；首次会装依赖）
2. 看到 `Uvicorn running on http://127.0.0.1:8000` 即启动成功
3. 打开项目根目录 `02_HTML版/原始原型_对接后端版.html`，右上角显示"本地引擎已就绪"即可使用
4. 上传图片 → 框选水印 → 点击"开始智能修复" → 对比并下载

> **无法启动时**：先运行 `python server.py --check` 自检。它会打印实际使用的解释器路径、各依赖版本、引擎可用性和 8000 端口占用情况。最常见的两个原因：① 系统 `python` 命中了微软商店占位符（自检显示的解释器路径含 `WindowsApps`）；② 8000 端口被其他程序占用。

> 接口文档：http://127.0.0.1:8000/docs

## 手动启动

```bash
cd 05_后端引擎   # 从项目根目录进入
python -m pip install -r requirements.txt
python server.py
```

## 双引擎说明

| 引擎 | 依赖 | 特点 | 状态 |
|---|---|---|---|
| **OpenCV** | opencv-python-headless | 零模型、秒级、纯色/简单背景水印效果好 | 默认启用 |
| **LaMA AI** | torch + simple-lama-inpainting | 大模型重建，复杂背景/大水印效果显著更好 | 可选，需安装 |

### 启用 LaMA AI 高质量引擎（可选，推荐有 GPU 时）

```bash
# 1. 安装 PyTorch（RTX 5060 用 CUDA 12.1 版本；无 GPU 用 CPU 版）
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
# CPU 版：pip install torch torchvision

# 2. 安装 LaMA 封装
pip install simple-lama-inpainting

# 3. 重启 server.py，界面会显示"AI 引擎已就绪"，引擎下拉可选 LaMA
```
首次调用会自动下载约 200MB 模型到 `05_后端引擎/models/`（已加入 .gitignore，不会入库）。

## API 接口

### `GET /api/health` — 健康检查
返回服务状态与可用引擎列表。前端据此切换状态指示。

### `POST /api/inpaint` — 图片去水印（核心接口）

| 字段 | 类型 | 说明 |
|---|---|---|
| `file` | file | 原始图片 |
| `rects` | str(JSON) | 水印框，原图像素坐标 `[{"x":280,"y":240,"w":100,"h":35}]` |
| `engine` | str | `auto` / `lama` / `opencv` |
| `strength` | int | 修复强度 1-3 |
| `enhance` | bool | 画质增强 |
| `face` | bool | 人脸保真（预留） |

返回修复后的 PNG 图片，响应头含 `X-Engine` / `X-Elapsed-Ms` 等元信息。

## v2 融合接口（推荐）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v2/engines` | 引擎状态、回退顺序、通俗名称说明（engine_guide） |
| GET/POST | `/api/v2/templates` | 查看 / 注册固定水印模板 |
| POST | `/api/v2/detect` | **智能识别**：分析框选区域内容类型并推荐修复方式 |
| POST | `/api/v2/process` | 融合处理，返回 PNG + 元数据响应头 |
| POST | `/api/v2/process/json` | 融合处理，仅返回 JSON（调试决策） |

关键参数：`file`、`rects`、`source_url`、`template_id`、`authorized`、`prefer_engine`。
新增参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `framework` | `smart` | `smart` / `texture` / `average` / `prompt`（按提示词自动选）；非法值回退 smart |
| `prompt` | 空 | 描述框住的目标与补全依据；`framework=prompt` 时生效 |
| `strict_box` | `true` | 仅把框内修复像素写回原图，框外逐字节不变 |

新增响应头：`X-Framework-Used`（实际使用的框架）、`X-Prompt-Intent`（意图摘要，JSON 转义）、
`X-Strict-Box`（是否应用严格框内）。均已加入 `Access-Control-Expose-Headers`。

提示词规则示例：

```
输入：我要去掉的是框住的蓝色包，其余区域依据背景或人物衣物进行修改。
解析：目标：蓝色包 · 按衣物/背景纹理补全 · 推荐「纹理重建」
结果：X-Framework-Used: texture
```

严格框内约束：引擎可能输出整图（例如源头解析），API 层统一按原框把修复像素贴回原图。
因此返回的图片中，**框外像素与原图逐字节一致**；框内完成去除并按背景/纹理补全。
若只提供了 `source_url` 而没有原图对象，则跳过合成（`X-Strict-Box: false`）。
响应头：`X-Engine-Used` / `X-Lossless` / `X-Elapsed-Ms` / `X-Trace`。

### `POST /api/v2/detect` — 智能识别（本次新增）

| 字段 | 类型 | 说明 |
|---|---|---|
| `file` | file | 原始图片 |
| `rects` | str(JSON) | 水印框，取第一个框识别 |

返回示例：`{"ok":true,"type":"texture","label":"重复纹理","confidence":0.85,
"suggest_method":"texture","suggest_engine":"opencv","detail":{...}}`。前端"智能识别"选项据此自动推荐修复方式。

## 运行测试

```bash
cd 05_后端引擎   # 从项目根目录进入
set PYTHONPATH=%CD%
python tests\test_orchestrator.py        # 核心流程 11 项
python tests\test_api_robustness.py      # 边界与异常 19 项
python tests\test_framework_strict.py    # 框架解析 + 严格框内 13 项
```
- `test_orchestrator.py`：授权终止、三步流水线、失败回退、指定引擎、Alpha无损、全部失败、智能识别（纯色/渐变/木纹）、纹理融合质量（文字去除且保留纹理），共 11 项。
- `test_api_robustness.py`：rects 非法结构（非 JSON / 非数组 / 元素非对象 / 字段非数值 / NaN / 宽高为 0）、任务存储 FIFO 淘汰、引擎边界输入（空框 / 越界 / 负坐标 / 异常强度）、编排器边界场景，共 19 项。

合计 43/43 应全部通过。测试素材见 `06_素材与示例/测试输入/`。

`test_framework_strict.py` 内含**跨端一致性**用例：从小程序的 `utils/prompt.js`
抽取示例提示词，交给 Python 解析，结果必须与前端一致——防止两端规则漂移。
另含严格框内逐像素比对：框外必须与原图完全相同，框内必须取修复结果。

## 目录结构

```
05_后端引擎/
├── server.py / api_v2.py   # FastAPI 服务（v1 + v2）
├── engine_registry.py      # 引擎装配
├── engines/
│   ├── fusion.py           # 统一引擎契约
│   ├── source_engine.py    # 引擎A 源头解析
│   ├── alpha_engine.py + reverse_alpha.py  # 反向Alpha无损
│   ├── ai_pipeline.py      # 引擎B 三步流水线
│   └── opencv_adapter.py   # 兜底
├── pipeline/               # 编排核心（状态/异常/上下文/Orchestrator）
├── tests/
│   ├── test_orchestrator.py     # 核心流程回归（unittest，11 项）
│   └── test_api_robustness.py   # 边界与异常回归（unittest，19 项）
├── models/                 # LaMA 模型缓存（自动生成，已 gitignore）
└── start.bat / requirements.txt
```

## 扩展新引擎

实现 `engines/fusion.py` 的 `FusionEngine`（`kind` / `available` / `execute`），失败抛 `RecoverableError` 子类，并在 `engine_registry.py` 注册。详见架构文档第九节。
