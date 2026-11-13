# 状态清单：已完成 / 未验证 / 阻塞 / 下一步

此页记录 2026-10-25 的初版移植。当前分支的运行方式和验收范围见 [macOS 安装与使用](macos_setup.md)。

- 更新：2026-10-25
- 分支：`feature/macos-apple-silicon`（基于 `master@a0c9372`）
- 机器：Apple Silicon arm64 / macOS 27.0.1

---

## 1. 已完成（有可复现命令或产物）

| # | 事项 | 证据 |
|---|---|---|
| 1 | 仓库真实审计（分支/CLI/依赖/许可证/测试） | `docs/repo_audit.md` |
| 2 | arm64 Python 3.11 venv + 全量依赖 + 锁定文件 | `requirements-macos.txt`（50 行） |
| 3 | LilyPond 2.26.0 arm64 原生安装（无需 Homebrew/Rosetta） | `docs/macos_setup.md` §3 |
| 4 | **修复 LilyPond 2.26 不兼容**（`set-global-fonts` 版本门 + `side-axis` 回移） | `scripts/jianpu-ly.py`；`tests/test_macos_compat.py` |
| 5 | **修复 `--engine stamp` 崩溃**（回移 `pad_measure_to_bar` + byte-accurate 单位换算） | `core/notation/jianpu/measure.py`；`placed 60/60 lines` |
| 6 | MusicXML → 简谱 PDF | `output/sheng_full.jianpu.pdf`（79 KB） |
| 7 | PDF → OMR → MusicXML → 简谱 PDF（CPU） | `output/work_cpu/曲笛.musicxml`（193 小节）+ `output/qudi_cpu.jianpu.pdf`，23.5 s |
| 8 | 对照 PDF 双引擎 | `stamp` 60/60（原尺寸）、`strip` 185/185（加高页面） |
| 9 | Provider 抽象 `--backend cpu/coreml/cuda/auto` + `HOMR_BACKEND` | `core/omr/homr_runner.py`、`jianpu.py`；`tests/test_inference_backend.py`（9 例） |
| 10 | 修复 shim 吞掉后端参数（静默跑 CPU） | `_build_processing_config`；`docs/repo_audit.md` F5 |
| 11 | Core ML 实测 + **默认开启**（segnet-only，整本与 CPU 持平） | `docs/coreml_plan.md`、`docs/bench_coreml*.json` |
| 12 | 环境自检脚本 | `scripts/check_macos_env.py`（21 项） |
| 13 | 后端基准脚本 | `scripts/bench_backends.py`（耗时/RSS/逐音 diff） |
| 14 | 安装与排障文档 | `docs/macos_setup.md` |
| 15 | 测试从 9/10 → **28/28** | `python -m unittest discover -s tests -v` |

---

## 2. 未验证（本次没有条件/时间做，不能算完成）

| 事项 | 为什么未验证 | 建议验收方式 |
|---|---|---|
| 3 类真实乐谱人工校谱 | 只有仓库自带 2 份矢量 PDF，缺"扫描件/其它制谱软件导出"样本 | 找 3 类 PDF，逐页比对音高/时值/调号，记录错音率 |
| 扫描件 OMR 质量 | `waifu2x-ncnn-vulkan` 未安装，超分路径未跑 | 安装后跑 300 DPI 扫描件，对比有无超分 |
| Audiveris 后端 | 需要 Java + 外部安装，未安装 | `--engine audiveris` 路径单测 + 端到端 |
| Core ML 跨页复用 session | 需要改 homr 内部构造逻辑 | 见 `docs/coreml_plan.md` §5 实验 1 |
| `.app` / `.dmg` 打包、签名、公证 | 属阶段 E | 非开发者 Mac 冷启动测试 |
| Intel / Universal Binary | 方案只承诺 arm64 | — |
| 大模型校谱 API（阶段 C） | 未开始 | — |
| 双谱同步编辑（阶段 D） | 未开始 | — |

---

## 3. 已知缺陷 / 阻塞（按严重度）

| 级别 | 问题 | 说明 | 建议 |
|---|---|---|---|
| 中 | 排版引擎失败会**静默降级**为纯文本 PDF 且退出码 0 | 见 `repo_audit.md` F2 末尾。CI 里无法靠退出码发现 | 增加 `--strict`：检测到"备用简谱排版"日志即返回非零；或校验产物文字层 |
| 中 | `stamp` 垂直间距按单行分谱调参 | 总谱（谱表间距小）简谱条会与下一行相撞 | 按系统间距自适应 `Y_OFFSET`；或对总谱默认 `strip` |
| 低 | `import fitz` 旧别名（2 处） | PyMuPDF 2.x 仅告警 | 统一 `import pymupdf` |
| 低 | 模型下载超时 120 s | 弱网首跑必失败 | 已用文档+自检脚本缓解；可改为可配置 |
| 低 | `main` 分支是另一条产品线 | 长期维护会分叉 | 决定是否合并 Web 版 |
| 已定 | **开源发行（AGPL-3.0）** | 决策 D3：接受 AGPL 与 PyMuPDF 的 AGPL 分支；闭源商业路线暂不考虑 | 需随包提供完整源码/构建脚本 |

---

## 4. 已定产品决策

| 编号 | 日期 | 决策 | 影响 |
|---|---|---|---|
| D1 | 2026-10-25 | 目标平台仅 Apple Silicon（arm64），Intel/Universal 暂不做 | 简化打包与依赖 |
| D2 | 2026-10-25 | **Apple 加速开箱即用**：macOS 上 `auto` = Core ML（segnet-only） | 整本持平、单页慢 1.7×；`--backend cpu` 作为快路径写进文档 |
| D3 | 2026-10-25 | **接受开源发行（AGPL-3.0）** | 无需替换 PyMuPDF / SumisoraOMR / Homr；需履行 AGPL 源码提供义务，模型权重许可仍需向作者确认 |

---

## 5. 下一步（严格按此顺序）

1. **补 3 类真实样本的人工校谱记录**（阶段 A 的验收门槛还差这一条）。产出 `docs/proofreading_<样本>.md`：页码 / 小节 / 原谱 / 识别结果 / 判定。
2. 给 CLI 加 `--strict`，把"备用排版"变成硬失败；顺手把 `import fitz` 清理掉。
3. 若确定要继续投入 Core ML：先做"跨页复用 session"实验（`coreml_plan.md` §5.1），只有 ≥1.2× 且逐音一致才改默认。
4. 阶段 C（规则校验 + 云端 API）应建立在自己的 `score model` 上，**不要**直接改 MusicXML 文本；先做小节时值合计与休止符校验。
5. 阶段 D（双谱编辑）在 `packages/score-model` 上推进，本阶段的 `pad_measure_to_bar` / `jianpu_note_token` 可直接复用为简谱视图的渲染层。

---

## 6. 复现本文档全部结论的最小命令序列

```bash
cd music_translator
export PATH="$PWD/../.toolchain/lilypond/bin:$PATH"
export XDG_CACHE_HOME="$PWD/../.cache/xdg"

# 1) 环境
../.venv/bin/python scripts/check_macos_env.py

# 2) 测试
../.venv/bin/python -m unittest discover -s tests -v      # 28 passed

# 3) MusicXML -> 简谱
../.venv/bin/python jianpu.py tests/fixtures/sheng.pdf \
  --mxl tests/fixtures/sheng_original.musicxml --mode both -o ../output/sheng_full

# 4) CPU 全链路
../.venv/bin/python jianpu.py 曲笛.pdf --backend cpu --mode jianpu \
  --work ../output/work_cpu -o ../output/qudi_cpu

# 5) 后端基准
../.venv/bin/python scripts/bench_backends.py --pdf 曲笛.pdf --page 1 \
  --backends cpu,coreml --repeat 2 --out docs/bench_coreml.json
```
