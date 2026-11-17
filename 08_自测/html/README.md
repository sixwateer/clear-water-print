# HTML 普通版 · 自测套件

对 `02_HTML版/净像去水印_普通版_双击即用.html` 的**可复跑**自测，属于
"自我测试 → 提问 → 修复 → 验证"闭环的执行部分。问题清单见 `ISSUES.md`。

## 运行

```bash
cd 08_自测/html
python prepare.py     # 把真实测试图转成 _tmp/wood.bin（8.3MB，临时文件）
node run.js           # 18 项断言（6 场景 × 3 模式），有失败时退出码为 1
python compare.py     # 生成 对比图.png（前 3 个场景，上原图下修复后）
python make_e2e.py    # 生成浏览器端到端测试页 _tmp/e2e.html
```

浏览器端到端（验证真实页面逻辑：识别/框选/三模式/三档/整图框）：

```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless \
  --disable-gpu --virtual-time-budget=40000 --dump-dom _tmp/e2e.html | grep "<title>"
```

结果在 `<title>` 里：`E2E|OK 贴边识别(...)|OK 自动框(...)|...|DONE`。

依赖：Node ≥ 16；Python 3 + Pillow + NumPy（prepare/compare/make_e2e 需要）。

## 测的是什么

- **测真代码**：`run.js` 用正则从交付的 HTML 里抽取 `fillLaplace` /
  `fillAverage` / `sharpen` / `growRect` / `injectTexture` 等函数源码，
  在 Node 里执行——不是抄一份副本，改了 HTML 断言立即跟着变。
- **测真实图**：`06_素材与示例/测试输入/test_wood_texture_watermark.jpg`
  （木桌 + 手 + 半透明"豆包AI生成"水印，1280×2278）。
- **指标**：
  | 指标 | 含义 | 判定 |
  |------|------|------|
  | 残影率 | 修复区内"高亮 + 低饱和"像素占比（水印特征） | < 修复前的 25%，或 <2% |
  | 边界色差 | 修复区最外沿与框外 2px 的平均色差 | 越小过渡越自然（仅记录） |
  | 平滑度 | 修复区平均梯度（条带/残留笔画会拉高） | 超大框 < 8 |
  | 与原图均色差 | 对照区（无水印）修复前后均色差 | smart < 45 |
- **场景**：正常框 / 贴底边 / 贴右下角 / 贴左上角（对照）/ 超大框 / 极小框。

## 产出

- `report.json`：每项指标的机器可读结果（含时间戳，便于对比不同版本）。
- `_tmp/out_*.ppm`：各场景裁剪图（PPM 无损，方便脚本拼图）。
- `对比图.png`：人工复核用（每次 `compare.py` 覆盖）。
- `浏览器实跑_修复前后.png`：真实浏览器里走完整流程（选图→框选→修复）
  后截的对比图，用于人工确认最终观感。

`_tmp/` 已在 `.gitignore` 中忽略，不进仓库。

## 最近一次结果

```
18 项，PASS 18，FAIL 0
超大框 1582ms → 40ms（多尺度）
贴底边 边差 44.9 → 6.9（镜像采样）
```
