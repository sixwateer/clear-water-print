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

## 快速开始（Windows）

1. 双击 `start.bat`（首次运行会自动安装基础依赖）
2. 看到 `Uvicorn running on http://127.0.0.1:8000` 即启动成功
3. 打开项目根目录 `02_HTML版/原始原型_对接后端版.html`，右上角显示"本地引擎已就绪"即可使用
4. 上传图片 → 框选水印 → 点击"开始智能修复" → 对比并下载

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
| GET | `/api/v2/engines` | 引擎状态与回退顺序 |
| GET/POST | `/api/v2/templates` | 查看 / 注册固定水印模板 |
| POST | `/api/v2/process` | 融合处理，返回 PNG + 元数据响应头 |
| POST | `/api/v2/process/json` | 融合处理，仅返回 JSON（调试决策） |

关键参数：`file`、`rects`、`source_url`、`template_id`、`authorized`、`prefer_engine`。
响应头：`X-Engine-Used` / `X-Lossless` / `X-Elapsed-Ms` / `X-Trace`。

## 运行测试

```bash
cd 05_后端引擎   # 从项目根目录进入
set PYTHONPATH=%CD%
python tests\test_orchestrator.py
```
覆盖授权终止、三步流水线、失败回退、指定引擎、Alpha无损、全部失败 6 项，应 6/6 通过。

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
├── tests/                  # 回归测试
└── start.bat / requirements.txt
```

## 扩展新引擎

实现 `engines/fusion.py` 的 `FusionEngine`（`kind` / `available` / `execute`），失败抛 `RecoverableError` 子类，并在 `engine_registry.py` 注册。详见架构文档第九节。
