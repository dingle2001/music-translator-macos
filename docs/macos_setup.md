# macOS 安装与使用

实测环境为 macOS 27.2.1、Apple Silicon、Python 3.11.17 和 LilyPond 2.26.0。完成下文安装后，从仓库目录构建并双击 `../output/五线谱转简谱.app` 打开应用。应用使用构建时记录的源码目录和本机运行环境，移动源码目录后请重新构建。

Intel Mac 请先看 [Intel Mac 导入 MusicXML](#intel-mac-导入-musicxml)。

```bash
source scripts/env.sh
python scripts/check_macos_env.py
bash macos/build.sh
```

## 0. 前置条件

| 组件 | 要求 | 检查命令 |
|---|---|---|
| 芯片 | Apple Silicon（M 系列）支持完整流程。Intel Mac 可导入已有 MusicXML/MXL | `uname -m` |
| 系统 | 原生应用的构建目标为 macOS 14+，实测 macOS 27.2.1 | `sw_vers` |
| Python | 与本机芯片架构匹配的 Python 3.11 | `python -V` |
| 排版 | 与本机芯片架构匹配的 LilyPond 2.26 | `lilypond --version` |
| 命令行工具 | 构建应用需要 Xcode Command Line Tools（含 Swift） | `xcode-select -p` |
| 磁盘 | 常规转换建议至少 3 GB 可用空间，用于依赖、模型、缓存和产物；音频模型另计 | `df -h .` |
| 内存 | 未验证统一的最低内存，所需内存随识谱后端、页图尺寸和乐谱复杂度而变化 | — |
| 网络 | 安装依赖与首次下载模型需要联网；资源就绪后可本地转换 | — |

没装 CLT 时：

```bash
xcode-select --install
```

> **不需要 Homebrew，也不需要 Rosetta。** 本项目刻意避开 `brew install lilypond`：Homebrew 的 LilyPond 在 arm64 上并不总是提供 bottle，而官方 2.26 有原生 arm64 包。

---

## 1. 安装 Python 3.11（arm64）

homr 0.7 要求 Python ≥ 3.11。使用 arm64 的 Python 3.11。

### 方案 A：uv（推荐，无需管理员权限）

```bash
# 任选一种方式安装 uv：https://docs.astral.sh/uv/
# 已有 uv 时：
uv python install 3.11
```

若你的环境限制写入 `~/.cache` / `~/.local`（例如沙箱、只读 home），把目录重定向到工作区：

```bash
export UV_CACHE_DIR="$PWD/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$PWD/.toolchain/python"
```

### 方案 B：python.org 官方安装包

下载 `python-3.11.x-macos11-arm64.pkg` 安装后，用 `/usr/local/bin/python3.11`（或 `/Library/Frameworks/...`）建 venv。

### 建 venv

```bash
"$(uv python find 3.11 2>/dev/null || command -v python3.11)" -m venv .venv
source .venv/bin/activate
python -V          # 必须显示 3.11.x
python -c "import platform; print(platform.machine())"   # 必须 arm64
```

---

## 2. 安装 Python 依赖

```bash
python -m pip install --upgrade pip wheel
# 复现本次验证过的版本（推荐）：
python -m pip install -r requirements-macos.txt
# 或跟随上游下限（可能装到未验证的新版本）：
python -m pip install -r requirements.txt
```

Homr 使用 ONNX Runtime。Audiveris 使用官方 Mac 应用内的 Java。

## 3. 安装 LilyPond 2.26（arm64，必需）

macOS arm64 的官方构建从 **2.26.0** 开始。下载的是 `.tar.gz`，解压即可用，不写 `/Applications`、不需要管理员：

```bash
# 从仓库目录进入其父目录，安装到 scripts/env.sh 会查找的位置。
cd ..
mkdir -p .toolchain/downloads .toolchain/lilypond
# https://gitlab.com/lilypond/lilypond/-/releases/v2.26.0
curl -fL -o .toolchain/downloads/lilypond-2.26.0-darwin-arm64.tar.gz \
  https://gitlab.com/lilypond/lilypond/-/releases/v2.26.0/downloads/lilypond-2.26.0-darwin-arm64.tar.gz
tar -xzf .toolchain/downloads/lilypond-2.26.0-darwin-arm64.tar.gz \
  -C .toolchain/lilypond --strip-components=1
.toolchain/lilypond/bin/lilypond --version    # GNU LilyPond 2.26.0 (running Guile 3.0)
```

返回仓库目录。运行时把它放进 `PATH`（`scripts/env.sh` 已代为处理）：

```bash
export PATH="$PWD/../.toolchain/lilypond/bin:$PATH"
```

随仓库提供的 `scripts/jianpu-ly.py` 已兼容 2.26 的自定义记号和装饰音。

**字体缓存告警**：首次运行可能出现多行 `Fontconfig error: No writable cache directories`。
这是 fontconfig 想写 `~/.cache/fontconfig` 但被限制；不影响输出。消除办法：

```bash
export XDG_CACHE_HOME="$PWD/.cache/xdg"   # 确保可写
mkdir -p "$XDG_CACHE_HOME"
```

---

## 4. 预下载 OMR 模型权重（强烈建议）

首次识别会下载缺少的 Homr 和 OCR 模型。弱网可先预下载 Homr CPU 和默认 Core ML 模型。

```bash
python -c "import homr.main as m; m.download_weights(False, False, False); m.download_weights(True, False, False)"
```

预下载到正在使用的 venv。运行一次样谱也会准备 RapidOCR 资源。

## 5. 自检

```bash
export PATH="$PWD/../.toolchain/lilypond/bin:$PATH"
python scripts/check_macos_env.py
```

Audiveris 未安装时会显示可选项警告。Homr、LilyPond 和模型检查通过后即可运行默认转换。

## 6. 转换示例

```bash
# 整页和原位对照，默认 Core ML
python jianpu.py 曲笛.pdf --strict -o ../output/曲笛

# CPU 识别扫描图像
python jianpu.py input/erhu_p1.png --mode jianpu --backend cpu --strict -o ../output/扫描二胡

# 直接导入 MusicXML，输出固定调简谱、MIDI 和校对文本
python jianpu.py tests/fixtures/sheng_original.musicxml --mode jianpu --strict \
  --pitch-mode fixed --fixed-tonic C --midi ../output/笙.mid \
  --editor-workspace editor-workspace -o ../output/笙

# 有原 PDF 和 MusicXML 时跳过识谱，使用原字号换行
python jianpu.py tests/fixtures/sheng.pdf --mxl tests/fixtures/sheng_original.musicxml \
  --mode insitu --layout wrap --strict -o ../output/笙

# 目录批处理，ZIP 中收录成功生成的原位谱
python batch.py /path/to/pdf-folder --strict -o ../output/批量 --zip ../output/批量/对照谱.zip
```

默认 `spaced` 保持纸张尺寸并自动分页，`strip` 是它的兼容别名。`stamp` 保留原位置和页数，空白不足时会跳过该行并写入 `*.insitu.report.json`。`--strict` 会拒绝漏页、漏行、备用排版和超限截尾。识谱结果仍以原谱为准，尤其注意报告中的时值、延音和小节数。

`--transpose-to D` 或 `--transpose 2` 改变实际音高，派生 MusicXML 保存在工作目录。固定调只改变简谱的唱名参考。移调后原位 PDF 的五线谱保留源谱。简谱文本可用 `python -m core.app.tui` 的「打开简谱编辑器」校对和重排，TUI 从仓库的 `editor-workspace` 读取。

Mac 窗口也能打开生成的 `.jianpu.txt`，交给文本编辑修改，再点击「开始转换」重新排版。命令行对应 `python jianpu.py 已校对.jianpu.txt --mode jianpu`。

### Agent 辅助校谱

转换完成后可用本地 MCP 把指定页的原谱图、MusicXML 摘录和疑点交给兼容的 Agent 工具。见 [Agent 校谱接入](agent_review.md)。

### Audiveris

从 [Audiveris 官方发行页](https://github.com/Audiveris/audiveris/releases/tag/5.11.0) 下载并安装 macOS arm64 版。程序会在 `/Applications`、用户的 `Applications` 或工作区的 `.toolchain/audiveris` 查找。也可以把 `AUDIVERIS_EXE_PATH` 指向 `Audiveris.app/Contents/MacOS/Audiveris`。

```bash
python jianpu.py 曲笛.pdf --omr audiveris --strict -o ../output/曲笛-audiveris
```

### 钢琴音频

钢琴音频使用独立的可选依赖。安装后首次转换会下载模型。支持 WAV、FLAC、OGG 和 MP3，适用于钢琴录音。

```bash
python -m pip install torch==2.15.0 piano-transcription-inference==0.0.6 torchlibrosa==0.1.0 \
  audioread==3.1.0 pretty-midi==0.2.11.post0 librosa==0.11.0 soundfile==0.14.0
python jianpu.py 钢琴.mp3 --mode jianpu --strict --midi ../output/钢琴.mid -o ../output/钢琴
```

## 7. 硬件加速与低内存设置

Mac 窗口可在「Homr 后端」选择自动、CPU、Core ML · GPU 或 Core ML · 神经网络引擎。命令行和目录批处理使用同一个后端参数。

| 后端 | 适用情况 |
|---|---|
| `auto`（默认） | Apple Silicon 上有 Core ML 且可用内存足够时，使用 Core ML 的 CPU + GPU 配置。可用内存不足约 2 GiB 或 Core ML 不可用时走 CPU。 |
| `coreml-gpu` | 允许 Core ML 使用 Apple GPU 和 CPU。 |
| `coreml-ane` | 允许 Core ML 使用 Apple Neural Engine（ANE）和 CPU。 |
| `cpu` | 使用 CPU 推理，可用于低内存机器或排查加速兼容性。 |
| `coreml` | 兼容已有命令。默认 CPU + GPU，可用环境变量覆盖。 |

默认只把 Homr 的 SegNet 图像分割交给 Core ML。谱表编码器、解码器及后续排版默认使用 CPU。多页 PDF 在同一次识谱中复用已激活的 SegNet 会话。若加速执行发生错误，应用会记录原因并以 CPU 重试。回退结果可用于本次导出，下次会重新尝试所选加速后端。

可用内存越少，SegNet 批大小上限越低。8 GB 及以下的 Mac 默认最多 4，内存紧张时降为 2 或 1。可用 `HOMR_SEGNET_BATCH_SIZE=1` 手动限制批大小。表中的内存阈值用于选后端和批大小，实际需求取决于乐谱页尺寸和其他应用的占用。

```bash
python jianpu.py 曲笛.pdf --mode jianpu --backend coreml-gpu -o ../output/曲笛-gpu
python jianpu.py 曲笛.pdf --mode jianpu --backend coreml-ane -o ../output/曲笛-ane
HOMR_SEGNET_BATCH_SIZE=1 python jianpu.py 曲笛.pdf --mode jianpu --backend cpu -o ../output/曲笛-cpu
```

Apple M5 Max、macOS 27.2.1、Homr 0.7.0、ONNX Runtime 1.31.0。每种模式单独起进程，各测一次，计入模型会话加载，不计简谱排版。磁盘上已有模型及 Core ML 编译缓存。

| 《曲笛》样谱 | CPU | Core ML GPU | Core ML ANE |
|---|---:|---:|---:|
| 5 页、193 小节 | 20.71 秒 | 14.94 秒 | 20.87 秒 |
| 第 1 页 | 4.77 秒 | 3.84 秒 | 4.96 秒 |
| 第 1 页，批大小限制为 1 | 4.34 秒 | 3.78 秒 | 4.31 秒 |

三种模式的样谱小节数、音符音高、音符起点、时值和休止序列一致。单页 GPU 批大小从默认值降到 1 后，识谱进程峰值 RSS 由约 2.51 GiB 降到 1.98 GiB。RSS 只反映进程驻留内存，各机型速度和统一内存占用以实际测试为准。低内存策略已用模拟内存输入测试，批大小 1 已在本机运行真实样谱。

复测与诊断：

```bash
python scripts/bench_backends.py --pdf 曲笛.pdf --backends cpu,coreml-gpu,coreml-ane --repeat 2
HOMR_COREML_PROFILE=1 python jianpu.py 曲笛.pdf --mode jianpu --backend coreml-ane -o ../output/诊断
```

计算计划诊断依赖系统和运行时支持的 Core ML Compute Plan，通常需要 macOS 14.4 或更新版本。它会列出算子的首选设备和估计成本。正常转换日志会显示 Core ML 会话是否激活、是否复用、是否回退。见 [ONNX Runtime Core ML 说明](https://onnxruntime.ai/docs/execution-providers/CoreML-ExecutionProvider.html)。

### Intel Mac 导入 MusicXML

使用 x86_64 Python 3.11 建立虚拟环境，安装 `requirements-macos-intel.txt`，并将 x86_64 版 LilyPond 2.26 放在 `PATH`，或通过 `LILYPOND` 指定其路径。可用已有 MusicXML/MXL 生成简谱，也可通过 `--mxl` 提供与原 PDF 对应的 MusicXML。构建脚本会按当前架构生成应用。

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-macos-intel.txt
python jianpu.py tests/fixtures/sheng_original.musicxml --mode jianpu -o ../output/笙
```

当前完整 Homr 依赖集缺少受支持的 Intel Mac ONNX Runtime 轮子。Intel 导入流程已用 x86_64 Python 和 LilyPond 在 Rosetta 环境验证，原生 Intel 实机尚未验收。

---

## 8. 运行测试

```bash
export PATH="$PWD/../.toolchain/lilypond/bin:$PATH"
python -m unittest discover -s tests -v
```

## 9. 环境变量速查

| 变量 | 作用 |
|---|---|
| `LILYPOND` | 直接指定 LilyPond 可执行文件 |
| `LILYPOND_PATH` / `LILYPOND_HOME` | `core/render/lilypond_runner.py` 的查找根 |
| `HOMR_BACKEND` | `auto` / `cpu` / `coreml` / `coreml-gpu` / `coreml-ane` / `cuda`，CLI `--backend` 优先 |
| `SUMISORA_ROOT` | 用外部 SumisoraOMR 覆盖内置 `core/` |
| `XDG_CACHE_HOME` | 给 fontconfig 一个可写的缓存目录 |
| `HOMR_COREML_ENCODER` | `1` = encoder 也上 Core ML（默认 `0`，仅 segnet） |
| `HOMR_COREML_COMPUTE_UNITS` | 兼容 `coreml` 模式的计算单元设置，支持 `CPUAndGPU`、`CPUAndNeuralEngine`、`ALL` 和 `CPUOnly`。显式 GPU 或 ANE 模式优先 |
| `HOMR_COREML_PROFILE` | `1` 启用计算计划诊断，并跳过已有识谱结果缓存 |
| `HOMR_SEGNET_BATCH_SIZE` | macOS 可设为 `1`、`2`、`4` 或 `8`，覆盖自动计算的 SegNet 批大小上限 |
| `HOMR_COREML_MODEL_CACHE_DIR` | 覆盖 Core ML 编译缓存位置 |

---

## 10. 验收范围

本机已验证 PDF 和图像识谱、MusicXML/MXL 导入、整页和原位排版、移调、MIDI、批量 ZIP、校对文本、钢琴 MP3 转录及 Mac 窗口导出。已通过 stdio MCP 验证逐页返回原谱图和对应 MusicXML。

macOS 应用以当前架构构建，依赖本地源码与运行环境。独立安装包、公证、简谱与五线谱同步编辑和完整的人工逐音准确率仍待实现或验收。
