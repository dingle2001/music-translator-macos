# 仓库审计报告：music_translator（Apple Silicon 移植基线）

- 审计日期：2026-10-25
- 审计人：DSH（在本机 `macOS 27.0.1 / arm64` 上实际执行，非静态阅读）
- 交接文档：`../DualScore_DSH_Development_Handoff.md`
- 结论一句话：**交接文档描述的主线（`jianpu.py` + `core/` + `insitu/`）是真实存在的，但它位于 `master` 分支，而不是仓库默认认知里的 `main`；在 arm64 macOS 上跑到可交付状态需要 4 处真实修复，其中 2 处是"退出码 0 但产物是错的"这类静默失败。**

---

## 1. 仓库事实（以真实代码为准）

| 项目 | 实测值 |
|---|---|
| 远程 | `https://github.com/starpacker/music_translator` |
| 默认分支 | **`master`**（HEAD `a0c9372e074f56577758059e1f629eba597d8ad0`，2026-10-24） |
| 其他分支 | `main`（`dc66c13d`，**与本项目无关的 Web 演示**：FastAPI + GitHub Pages，只有 15 个文件）、`arena/9dbdc2ec-music-translator`（`9ecb73a6`） |
| 仓库体积 | 约 5 MB（含 3 个示例 PDF、模板图、测试样本） |
| 许可证 | **AGPL-3.0**（`LICENSE` 与 `THIRD_PARTY_NOTICES.md` 一致，交接文档的判断正确） |
| 入口 | `jianpu.py`（161 行，真实存在） |
| 引脚 | 本次工作在 `feature/macos-apple-silicon` 分支上进行 |

> **差异 D1（重要）**：交接文档只说"仓库支持 `jianpu.py`"，未提分支问题。若按 GitHub 默认页签或 `git clone` 后直接查看，会看到 `main` 上的 Web 演示，从而误判"仓库没有 OMR 代码"。**必须先 `git switch master`。**
>
> 本次审计同时确认 `main` 分支的 `backend/vendor/score_align.py` 与 master 的 `insitu/vendor/score_align.py` 是同一份代码的副本，`main` 不是废弃分支而是另一条产品线（Web 版），长期需要决定是否合并。

### 1.1 实际目录（master，节选）

```
jianpu.py                # 唯一 CLI 入口
batch.py                 # 目录级批处理
_env.py                  # 定位 core/、lilypond、python
homr_shim.py             # 适配 pip 版 homr 的 ProcessingConfig
core/
  omr/                   # homr_runner / engine_router / audiveris_runner / audio_runner …
  notation/jianpu/       # extract / measure / primitives（MusicXML → 简谱文本）
  render/                # renderer / lilypond_runner / jianpu_runner
  image/                 # 预处理 / 超分 / 谱表切分
insitu/                  # align.py / pdf_structure.py / render_insitu.py / vendor/score_align.py
scripts/jianpu-ly.py     # vendored jianpu-ly v1.866（含本地修改声明）
prototype_cv/            # 第一代纯 CV 实现（保留，不参与主链路）
tests/                   # 4 个测试文件 + fixtures（sheng.pdf / *.musicxml）
曲笛.pdf / 二胡.pdf       # 示例输入
```

### 1.2 CLI 实际参数（`python jianpu.py --help` 实测）

与交接文档 3.1 节列出的 `--gpu off`、`--mode jianpu|insitu|both`、`--mxl`、`--engine strip`、`-o` **完全一致**，另有 `--work`、`--title`。本次新增 `--backend {auto,cpu,coreml,cuda}`。

### 1.3 依赖实测

`requirements.txt`（未锁定版本）：PyMuPDF、music21、Pillow、numpy、reportlab、fonttools、**homr>=0.7.0**、requests、truststore。

实际解析结果（Python 3.11.17 arm64）：

| 包 | 解析到 | 与交接文档的差异 |
|---|---|---|
| PyMuPDF | **2.0**（不是 1.28.2） | 2.x 移除了 `fitz` 旧别名，`core/omr/multirest_collapse.py:59` 与 `run_reference_erhu.py:8` 仍 `import fitz`，会产生 FutureWarning；建议统一 `import pymupdf` |
| music21 | 10.5.1 | 一致 |
| homr | 0.7.0 | **纯 ONNX，不依赖 torch** |
| onnxruntime | **1.31.0** | 自带 `CoreMLExecutionProvider`（arm64 wheel） |
| LilyPond | **2.26.0 arm64** | 交接文档假设 2.22+；2.26 是 macOS arm64 唯一官方构建 |

> homr 0.7 的实际依赖是 `onnxruntime / opencv-python-headless / rapidocr / musicxml / numpy / Pillow`，**没有 torch、没有 CUDA 运行时**。交接文档中"CUDA 生态引发迁移需求"的表述在依赖层面已不成立：本仓库在 macOS 上的阻塞点是 **LilyPond 版本 + GPU 探测只认 CUDA/DML**，不是 CUDA wheel。

---

## 2. 逐项验证结果

| # | 交接文档要求 | 结果 | 证据 |
|---|---|---|---|
| 1 | 仓库真实代码审计 | ✅ | 本文件 |
| 2 | arm64 Python + venv + 依赖 | ✅ | Python 3.11.17 arm64，`.venv`，`requirements-macos.txt` |
| 3 | 单元测试通过 | ⚠️ 9/10 → **10/10** | 原失败项为测试自身过时（见 F4），已修 |
| 4 | MusicXML → 简谱 PDF | ✅ | `output/sheng_full.jianpu.pdf`（79 KB，1 页 A4，含和弦/八度点/升降号） |
| 5 | CPU OMR → MusicXML | ✅ | 5 页 / 193 小节 / 23.5 s（含排版），峰值 RSS 1.78 GB |
| 6 | 五线谱/简谱对照 PDF | ✅ 双引擎 | `stamp`（页面尺寸不变，60/60 行）与 `strip`（加高页面，185/185） |
| 7 | 冷启动/缓存区分 | ✅ | 见 §4 |
| 8 | Core ML | ✅ 已适配并量化 | **本机反而更慢**，见 §5，属真实结论 |

未验证/受阻项见 `docs/status.md`。

---

## 3. 审计发现的缺陷与修复（全部已在本分支修复并有测试）

### F1 分支陷阱
`main` 与本项目无关。**修复**：文档明确 `git switch master`；本工作分支基于 `master`。

### F2 LilyPond 2.26 不兼容（两个独立原因，均会**静默产出错误 PDF**）
macOS arm64 只有 2.26+ 的官方构建；仓库内置的 `scripts/jianpu-ly.py`（v1.866）与上游最新 v1.891 **都**按 2.20 语法生成 LilyPond 源码：

1. 无条件输出 `#(define fonts (set-global-fonts …))`（仅当 `/Library/Fonts/Arial Unicode.ttf` 存在时）。2.26 删除了该 Scheme 函数 → `Unbound variable: set-global-fonts`。
2. 自定义 `two-dots` / `three-dots` 音符符号缺少 `(side-axis . ,Y)` 与 `(script-priority . -200)` → 2.26 报 `no side-axis setting found for grob Script`，随后在 `init.ly` 阶段崩溃。

**最危险的地方**：主渲染器在 LilyPond 失败后会"降级"生成一个**纯文本转储 PDF**（把 `(2 4 #6)` 这样的记号直接印在页面上），并且 **退出码仍是 0**。交接文档 §5 说"不能只看进程退出码"，这里就是实例。该坏样本留在 `../output/evidence_broken_fallback_text_dump.pdf` 作为对照（7 KB、文字层就是记号串），正常产物是 79 KB 的真简谱。

**修复**（`scripts/jianpu-ly.py`，已写入文件头 Apache-2.0 修改声明第 7 条）：
- 字体块加版本门：`lilypond_minor_version() < 26`；
- 从上游 v1.891 回移 `side-axis` / `script-priority` 到两个自定义 script 定义。

**验证**：`tests/test_macos_compat.py::LilyPondCompatTest` 断言生成源码不含 `set-global-fonts`（2.26 下）、含两处 `side-axis`，并真实调用 LilyPond 编译成功。

### F3 `--engine stamp`（README 默认引擎）在 HEAD 上直接崩
`insitu/render_insitu.py` 从 `core.notation.jianpu` 导入 `pad_measure_to_bar`，而该函数在内置快照中已被移除 → `ImportError`。`--mode both`（默认）因此 100% 失败。

修的过程中还发现第二层问题：新内核明确"不再补齐小节"，但 `stamp` 是**一行一编译**，jianpu-ly 的 barcheck 会因小节不足/超长整行报错。仅删导入后仍有 10/60 行失败。

**修复**：
1. 从上游 SumisoraOMR 回移 `pad_measure_to_bar`（`core/notation/jianpu/measure.py`）并在 `__init__.py` 重新导出；
2. 把内部的单位换算从 `_DURATION_TO_UNITS` 表 + 浮点兜底改为 `jianpu_note_units()`（与 `jianpu_note_token` 逐一对应，三连音/非格点时值不再漂移）。

**结果**：`placed 60/60 lines`（修复前 50/60，仅删导入后 57/60）。

### F4 仓库自带测试与代码不一致
`tests/test_sheng_chord_rendering.py` 断言 `\override LedgerLineSpanner #'stencil = ##f`，但生成器早已改为 `.stencil` 点号语法。属于测试过时，不是渲染回归。**修复**：断言改为兼容两种写法，并补充 `side-axis` 断言。

### F5 `--backend` 会被 shim 静默吞掉（新写的功能，第一次跑就踩中）
`_build_processing_config()` 用 `inspect.signature(ProcessingConfig.__init__)` 过滤 kwargs。`homr_shim.install()` 把 `__init__` 替换成 `(*args, **kwargs)` 后，签名里只剩 `self/args/kwargs`，于是**所有** kwarg 被丢掉，配置退回 dataclass 默认值（`segnet_use_gpu=False, coreml_encoder=False`）。

后果极具欺骗性：日志打印 "CoreML 模式"，实际全程 CPU，且 CPU 基线结果完全正确，所以不会有人发现。**修复**：探测到 `VAR_KEYWORD` 时改用 `dataclasses.fields()` 作为可接受参数集。

### F6 GPU 探测只认 CUDA / DirectML
`_homr_gpu_available()` 在 macOS 上恒为 `False`，`download_weights(..., coreml_encoder=False)` 被硬编码 → 即使 homr 0.7 原生支持 Core ML，仓库也永远不会启用。

**修复**：新增 `_resolve_inference_backend()` / `_backend_from_flags()`，CLI 增加 `--backend`，环境变量 `HOMR_BACKEND` 兜底；CUDA 语义保持不变。

### F7 模型权重下载超时过短
`_run_with_heartbeat(..., max_seconds=120)` 包住 `download_weights`。全新环境需下载 **134 MB**（segnet 54 + encoder 50 + decoder 45，启用 Core ML 再加 27+25 MB），实测 34 s（约 4 MB/s）；弱网下必然超时并让整次识别失败。

**缓解**：文档给出预下载命令（`scripts/check_macos_env.py` 会报告缺哪个权重），并把"下载超时"与"识别失败"在日志里区分。

### F8 `stamp` 的垂直间距是按单行分谱调的
对 `曲笛.pdf`（总谱，谱表间距小）与 `sheng.pdf` 会出现简谱条与下一行谱表相撞。`Y_OFFSET`（默认 20 pt）与 `strip` 的 `gap_above_pt/gap_below_pt` 需按输入类型调参，或改成"按可用空白自适应"。**未修**，属排版调参，记入 `status.md`。

### F9 扫描件质量依赖可选组件
`waifu2x-ncnn-vulkan` 缺失时日志会明确警告"超分未生效，识别质量明显下降"。矢量 PDF 不受影响；扫描件需要单独评估（交接文档 §7 已列为风险）。

---

## 4. CPU 基线实测数据（本机，Apple Silicon）

命令：

```bash
cd music_translator
export PATH="$PWD/../.toolchain/lilypond/bin:$PATH"
../.venv/bin/python jianpu.py 曲笛.pdf --backend cpu --mode jianpu \
    --work ../output/work_cpu -o ../output/qudi_cpu
```

| 项目 | 数值 |
|---|---|
| 输入 | `曲笛.pdf`，5 页 A4 矢量谱 |
| OMR + 排版总耗时 | **23.46 s**（user 150.6 s，说明多线程/批量已生效） |
| 峰值 RSS | **1.78 GB** |
| 识别结果 | 193 小节，与 README 声称的 193 小节一致 |
| 中间产物 | `output/work_cpu/曲笛.musicxml`（282 KB）+ `曲笛.omr/` 逐页输出 |
| 最终产物 | `output/qudi_cpu.jianpu.pdf`（62 KB，3 页 A4） |
| 模型下载（首次） | 134 MB / 34 s；之后离线可跑 |

MusicXML-only 路径（跳过 OMR）：

```bash
../.venv/bin/python jianpu.py tests/fixtures/sheng.pdf \
    --mxl tests/fixtures/sheng_original.musicxml --mode both -o ../output/sheng_full
```

| 引擎 | 结果 |
|---|---|
| `jianpu` | 79 KB / 1 页，和弦、八度点、升号、小节号齐全 |
| `insitu --engine strip` | 7 页，185 谱表 ↔ 185 简谱格，页面 595×(1538–1737) pt |
| `insitu --engine stamp` | 7 页，595×842 pt（与原谱同尺寸），`placed 60/60 lines` |

---

## 5. Core ML 适配结果（默认开启，数字与取舍）

实现方式：**不自己写 provider 管线**。homr 0.7 已内置 Apple 支持，本仓库要做的只是把开关接上（F6）并按平台语义分配：

| 模型 | 后端（交付默认） | 理由 |
|---|---|---|
| segnet | CoreML EP（`MLProgram`, `CPUAndGPU`） | fp16 模型，MLProgram 才能真正把节点放到 GPU/ANE |
| transformer encoder | **CPU fp32**（`HOMR_COREML_ENCODER=1` 可切 CoreML） | 每行谱表一次 CoreML 调用，实测多 ~4 s/页 |
| transformer decoder | **CPU fp32** | CoreML EP 跑不了动态 KV-cache 维度，强行放会崩 |

> 早期版本还把 encoder 放到 CoreML，那一版单页 12.2–13.7 s；改成 segnet-only 后降到 8.3–8.4 s，整本从 +11% 变成基本持平。

单页（`曲笛.pdf` 第 1 页），各跑两次：

| 后端 | wall | 峰值 RSS | 音符 | 与 CPU 的差异 |
|---|---|---|---|---|
| cpu | **4.84–4.85 s** | 1190–1210 MB | 164 | —（基准） |
| coreml（segnet only） | **8.34–8.41 s** | 1272 MB | 164 | 逐音全等 |

整本 5 页（193 小节、804 音符）：

| 后端 | wall | 峰值 RSS | 与 CPU 的差异 |
|---|---|---|---|
| cpu | **20.87 s** | 1688 MB | —（基准） |
| coreml（segnet only） | **21.06 s** | 1944 MB | 逐音全等 |

配置对比（同页，用于定默认值）：CPU 4.88 s；segnet-only 8.61 s；segnet+encoder 12.54 s；`MLComputeUnits=ALL` 20.59 s。

编译缓存确认已生成（证明真的走了 Core ML，而不是静默回退）：
`homr/segmentation/*_fp16.coreml_cache` 55 MB（开启 encoder 另有 182 MB）。

**结论**：按"开箱即用 Apple 加速"的产品决策，`auto` 在 Apple Silicon 上**默认解析为 Core ML（segnet-only）**：
- 整本分谱与 CPU 基本持平（+0.9%），但计算落在 GPU/ANE，CPU 更空闲；
- 单页片段慢约 1.7×，因此 `--backend cpu` / `HOMR_BACKEND=cpu` 被明确写成"短片段快路径"；
- 准确率无退化（逐音序列全等）；失败会回退 CPU 并打印**实际**后端。

> 交接文档 §5-B 要求"不能因为检测到 CoreMLExecutionProvider 就宣布加速"。本次审计正好验证了这条：**第一次接上时确实没生效**（F5），修好后才测出真实差异，并据此选了 segnet-only。

## 6. 许可证与发行风险（AGPL 复核）

| 组件 | 许可 | 影响 |
|---|---|---|
| 本项目 | AGPL-3.0 | 分发 `.app` 即触发 §13 网络/源码提供义务 |
| SumisoraOMR（内置于 `core/`） | AGPL-3.0 | 同上，且需保留上游声明 |
| Homr | AGPL-3.0 | 模型权重单独看（ONNX checkpoints 未附许可文件，需向作者确认） |
| PyMuPDF | AGPL-3.0 或商业 | 走 AGPL 分支，闭源发行必须买 Artifex 商业许可 |
| LilyPond | GPL-2.0 | **独立进程调用**，不链接；随包分发二进制需附源码/许可 |
| jianpu-ly | Apache-2.0 | 已按 §4(b) 在文件头声明 7 条本地修改 |
| music21 | BSD-3 | 宽松 |

**结论**：若目标是闭源商业 `.app`，必须替换 PyMuPDF（或购买商业许可）并去掉 SumisoraOMR/Homr 的 AGPL 传染面；若接受 AGPL 开源发行，则当前依赖链是合规的（需随包提供完整源码与构建脚本）。此结论已写入 `docs/status.md` 的待决策项，不在本阶段实施。

---

## 7. 与交接文档的其他口径差异（记录，不阻塞）

| 交接文档说法 | 实测 |
|---|---|
| "Homr / SumisoraOMR / Audiveris 三引擎" | Audiveris 路径存在（`core/omr/audiveris_runner.py`）但需 Java + 外部安装，本次未验证 |
| "CUDA 生态导致迁移困难" | homr 0.7 已无 torch/CUDA 硬依赖；真正阻塞是 LilyPond 与 GPU 探测 |
| "music_translator 采用 AGPL-3.0，另有 GPL/AGPL 依赖" | 属实，且 PyMuPDF 的双许可是闭源路线上的硬约束 |
| "`main` 分支即仓库" | **不成立**，主线在 `master`（D1） |
| "测试可通过" | 原为 9/10（F4） |
