# Apple Silicon (arm64) macOS 安装与运行

目标：在一台**全新、没装 Homebrew、没装 Python 3.11、没装 LilyPond** 的 Apple Silicon Mac 上，
从零复现"五线谱 PDF → MusicXML → 简谱 PDF"全链路，并可选开启 Core ML。

本文件里的每条命令都在 macOS 27.0.1 / arm64 上实际执行过（2026-10-25）。凡是未验证的步骤都标了 **[未验证]**。

---

## 0. 前置条件

| 组件 | 要求 | 检查命令 |
|---|---|---|
| 芯片 | Apple Silicon（arm64） | `uname -m` → `arm64` |
| 系统 | macOS 14+（本机 27.0.1） | `sw_vers` |
| 命令行工具 | Xcode Command Line Tools | `xcode-select -p` |
| 磁盘 | ≥ 3 GB（venv 约 600 MB + 模型 160 MB + Core ML 缓存可选 240 MB） | `df -h .` |
| 网络 | 首次需下载 Python / 模型 / LilyPond（约 320 MB） | — |

没装 CLT 时：

```bash
xcode-select --install
```

> **不需要 Homebrew，也不需要 Rosetta。** 本项目刻意避开 `brew install lilypond`：Homebrew 的 LilyPond 在 arm64 上并不总是提供 bottle，而官方 2.26 有原生 arm64 包。

---

## 1. 安装 Python 3.11（arm64）

homr 0.7 要求 Python ≥ 3.11。系统自带的是 3.9，不能用。两条路任选：

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
cd music_translator
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

> 实测解析到 **PyMuPDF 2.0**（上游只写了 `>=1.28.2`）。2.x 会移除 `fitz` 旧别名，
> 仓库里 `core/omr/multirest_collapse.py`、`run_reference_erhu.py` 仍 `import fitz`，
> 目前只是 FutureWarning，不影响运行，但升级前需知悉。

没有 CUDA、没有 torch、没有 Java：homr 0.7 的推理链是纯 ONNX。

---

## 3. 安装 LilyPond 2.26（arm64，必需）

macOS arm64 的官方构建从 **2.26.0** 开始。下载的是 `.tar.gz`，解压即可用，不写 `/Applications`、不需要管理员：

```bash
cd <工作目录>
mkdir -p .toolchain/downloads .toolchain/lilypond
# https://gitlab.com/lilypond/lilypond/-/releases/v2.26.0
curl -fL -o .toolchain/downloads/lilypond-2.26.0-darwin-arm64.tar.gz \
  https://gitlab.com/lilypond/lilypond/-/releases/v2.26.0/downloads/lilypond-2.26.0-darwin-arm64.tar.gz
tar -xzf .toolchain/downloads/lilypond-2.26.0-darwin-arm64.tar.gz \
  -C .toolchain/lilypond --strip-components=1
.toolchain/lilypond/bin/lilypond --version    # GNU LilyPond 2.26.0 (running Guile 3.0)
```

运行时把它放进 `PATH`（脚手架脚本已代为处理）：

```bash
export PATH="$PWD/../.toolchain/lilypond/bin:$PATH"
```

> **必须打补丁**：LilyPond 2.26 删除了 `set-global-fonts`，且自定义 `two-dots`/`three-dots`
> 需要 `side-axis`。本仓库 `scripts/jianpu-ly.py` 已含修复（见 `docs/repo_audit.md` F2）。
> 若你把仓库回退到上游原版，编译会失败——**而且失败后会静默产出一个纯文本 PDF、退出码仍为 0**。

**字体缓存告警**：首次运行可能出现多行 `Fontconfig error: No writable cache directories`。
这是 fontconfig 想写 `~/.cache/fontconfig` 但被限制；不影响输出。消除办法：

```bash
export XDG_CACHE_HOME="$PWD/.cache/xdg"   # 确保可写
mkdir -p "$XDG_CACHE_HOME"
```

---

## 4. 预下载 OMR 模型权重（强烈建议）

首次识别会自动下载 134 MB（segnet 54 MB + encoder 50 MB + decoder 45 MB），
仓库对下载只给了 120 s 超时，弱网必然失败。先手动下好：

```bash
# CPU / 基线
python -c "import homr.main as m; m.download_weights(False, False, False)"

# 如果要试 Core ML（额外 segnet fp16 27 MB + encoder fp16 25 MB）
python -c "import homr.main as m; m.download_weights(True, False, True)"
```

权重落在 venv 的 `site-packages/homr/segmentation|transformer/` 下；**删除 venv 会连带删除权重**。
离线运行 = 依赖已装好 + 权重已就位，之后不再联网。

---

## 5. 自检

```bash
export PATH="$PWD/../.toolchain/lilypond/bin:$PATH"
python scripts/check_macos_env.py
```

期望结尾：`21 项检查：0 失败 / 1 警告`（唯一警告通常是 `waifu2x` 不可用，矢量 PDF 不受影响）。
任何 `FAIL` 都会在后续步骤变成更难定位的问题，先修。

---

## 6. 跑通三条链路

### 6.1 已有 MusicXML → 简谱 PDF（最快验证，不碰 OMR）

```bash
python jianpu.py tests/fixtures/sheng.pdf \
    --mxl tests/fixtures/sheng_original.musicxml --mode jianpu -o ../output/sheng
# → ../output/sheng.jianpu.pdf   约 79 KB / 1 页 / A4
```

### 6.2 PDF → OMR → MusicXML → 简谱 PDF（CPU 基线）

```bash
python jianpu.py 曲笛.pdf --backend cpu --mode jianpu \
    --work ../output/work_cpu -o ../output/qudi
# → ../output/work_cpu/曲笛.musicxml   (282 KB, 193 小节)
# → ../output/qudi.jianpu.pdf          (62 KB, 3 页)
# 实测 23.5 s，峰值内存 1.78 GB
```

### 6.3 五线谱/简谱对照 PDF（两种引擎）

```bash
# stamp：页面尺寸与原谱完全一致，逐行贴字
python jianpu.py 曲笛.pdf --backend cpu --mode insitu --engine stamp -o ../output/qudi_stamp

# strip：在每个谱表系统下方插入简谱条，页面随之加高
python jianpu.py 曲笛.pdf --backend cpu --mode insitu --engine strip -o ../output/qudi_strip
```

> **选哪个**：要"原版式+简谱"用 `stamp`；原谱下方已经很挤、或要重新排版打印用 `strip`。
> 已知限制：`stamp` 的垂直间距（`Y_OFFSET`）是按单行分谱调的，总谱（谱表间距小）会与下一行相撞。

---

## 7. Core ML（可选，默认关闭）

```bash
python jianpu.py 曲笛.pdf --backend coreml --mode jianpu -o ../output/qudi_ml
```

- 首次运行会把 segnet/encoder 编译成 MLProgram，并在模型文件旁生成 `*.coreml_cache`（约 240 MB）。
- 实测**单页 12.2–13.7 s vs CPU 5.1 s（约慢 2.4×）**，音符/小节/音高序列与 CPU 完全一致。
- 想量化对比：

```bash
python scripts/bench_backends.py --pdf 曲笛.pdf --page 1 --backends cpu,coreml --repeat 2 \
    --out docs/bench_coreml.json
```

- 也可用环境变量给 GUI/其他入口设默认后端：`export HOMR_BACKEND=coreml`。

---

## 8. 运行测试

```bash
export PATH="$PWD/../.toolchain/lilypond/bin:$PATH"
python -m unittest discover -s tests -v
```

期望 `Ran 25 tests ... OK`（其中 LilyPond 相关用例在找不到 lilypond 时会 skip）。
最初的仓库是 9/10，失败项为测试自身过时，见 `docs/repo_audit.md` F4。

---

## 9. 环境变量速查

| 变量 | 作用 |
|---|---|
| `LILYPOND` | 直接指定 LilyPond 可执行文件（`insitu` 用） |
| `LILYPOND_PATH` / `LILYPOND_HOME` | `core/render/lilypond_runner.py` 的查找根 |
| `HOMR_BACKEND` | `auto` / `cpu` / `coreml` / `cuda`，CLI `--backend` 优先 |
| `SUMISORA_ROOT` | 用外部 SumisoraOMR 覆盖内置 `core/` |
| `XDG_CACHE_HOME` | 给 fontconfig 一个可写的缓存目录 |
| `HOMR_COREML_COMPUTE_UNITS` | `ALL`（默认，ANE+GPU+CPU）/ `CPUAndGPU` |
| `HOMR_COREML_MODEL_CACHE_DIR` | 覆盖 Core ML 编译缓存位置 |

---

## 10. 故障排查

| 现象 | 根因 | 处理 |
|---|---|---|
| `Unbound variable: set-global-fonts` | LilyPond ≥ 2.26 + 未打补丁的 jianpu-ly | 确认 `scripts/jianpu-ly.py` 含 `lilypond_minor_version() < 26` 判断 |
| `no side-axis setting found for grob Script` 后接 `init.ly` 崩溃 | 自定义符号缺 `side-axis` | 确认源码含两处 `(side-axis . ,Y)` |
| 退出码 0，但 PDF 里是 `(2 4 #6)` 纯文本 | LilyPond 失败后的"备用排版" | 看日志里是否出现 `已生成备用简谱 PDF`；按上两行修根因 |
| `ImportError: cannot import name 'pad_measure_to_bar'` | 用了未修复的 `insitu/render_insitu.py` | 本仓库已回移该函数；确认 `core/notation/jianpu/measure.py` 存在它 |
| `barcheck fail: note crosses barline` | 一行一编译时小节时值不匹配 | 同上，`pad_measure_to_bar` 必须参与 `stamp` 渲染 |
| `[homr] 模型权重下载超时（>120s）` | 首下载超时 | 按 §4 预下载 |
| `CoreMLExecutionProvider` 存在但耗时没变化 | 参数被 shim 吞掉（历史缺陷） | 本仓库已修；用 `--backend coreml` 后确认生成了 `*.coreml_cache` |
| `fontconfig: No writable cache directories` | 只读 home | 设 `XDG_CACHE_HOME` |
| `未找到 waifu2x-ncnn-vulkan` | 可选超分组件缺失 | 矢量 PDF 忽略即可；扫描件需另装 |

---

## 11. 未验证事项（如要对外发布必须补）

- Developer ID 签名、公证（notarization）、Gatekeeper 首次启动：**[未验证]**
- 打包成不依赖系统 Python 的 `.app`（PyInstaller/Nuitka/sidecar）：**[未验证]**
- Intel / Universal Binary：**[未验证]**（本方案只承诺 arm64）
- Audiveris 后端（需要 Java）：**[未验证]**
