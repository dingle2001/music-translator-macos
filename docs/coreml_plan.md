# Core ML 适配方案与实测结论

这页记录 2026-10-25 的方案和基准。当前 GPU／神经网络引擎模式、跨页会话复用和内存适配见 [macOS 安装与使用](macos_setup.md#7-硬件加速与低内存设置)。

- 日期：2026-10-25（末次更新：默认配置改为 segnet-only 后重测）
- 机器：Apple Silicon（arm64），macOS 27.0.1
- 运行时：onnxruntime 1.31.0、homr 0.7.0、Python 3.11.17
- 原始数据：`docs/bench_coreml.json`（单页）、`docs/bench_coreml_full.json`（5 页）

---

## 1. 结论先行

1. **Apple 加速现在默认开启**（`auto` → Core ML）：产品决策是"开箱即用"，见 `docs/status.md` 决策 D2。
2. **整本谱有竞争力**：5 页 193 小节，CPU 20.87 s vs Core ML **21.06 s**（差 0.9%，且计算落在 GPU/ANE，CPU 更空闲）。
3. **单页仍慢**：4.84 s vs 8.34–8.41 s（约 1.7×），因为 Core ML 的会话/绑定固定开销摊不开。`--backend cpu` 因此被明确定义为"短片段/批处理的快路径"。
4. **默认只加速 segnet**。把 transformer encoder 也放上 Core ML（homr 的 opt-in）会**再慢约 4 s/页**，需要 `HOMR_COREML_ENCODER=1` 显式打开。
5. **`MLComputeUnits=ALL`（用 ANE）更差**：20.59 s vs 12.54 s（默认 `CPUAndGPU`），ANE 特化预热压垮了小模型。homr 的默认选择是对的。

---

## 2. 为什么不需要自己写 provider 管线

homr 0.7.0 已内置 Apple 支持（`homr/onnx_providers.py`），且**按模型区别对待**：

| 模型 | 能否上 Core ML | 说明 |
|---|---|---|
| segnet | ✅（默认开） | fp16；必须 `ModelFormat=MLProgram`，否则几乎不接节点、静默退回 CPU |
| transformer encoder | ✅（opt-in） | 必须 fp16；每行谱表一次调用，短谱上不划算 |
| transformer decoder | ❌ | 动态 KV-cache 维度在 MLProgram 下崩溃；固定 CPU fp32（且比 CPU fp16 快） |

Core ML EP **不暴露 device memory**：输入输出绑定在 CPU（`io_binding_device = "cpu"`），GPU 只负责计算。这也是小模型收益有限的原因。

本仓库改动只有"把开关接上 + 平台语义正确"：

- `core/omr/homr_runner.py`：`_resolve_inference_backend()` / `_backend_from_flags()`，把 `auto|cpu|coreml|cuda` 映射为 `(segnet_use_gpu, transformer_use_gpu, coreml_encoder)`；
- `--backend` CLI + `$HOMR_BACKEND`；
- `$HOMR_COREML_COMPUTE_UNITS`：覆盖 homr 硬编码的 `CPUAndGPU`（用于 A/B，不作默认）；
- `$HOMR_COREML_ENCODER=1`：把 encoder 也移到 Core ML。

**关键**：`transformer_use_gpu` 在 Core ML 下必须保持 `False`。它不是"开加速"的开关，设 True 会让 decoder 走 fp16+CoreML 而崩溃。

---

## 3. 实测数据

每个后端独立子进程（冷启动计入），同机同输入。

### 3.1 整本（`曲笛.pdf`，5 页，193 小节）— 交付默认配置

| 后端 | wall | 峰值 RSS | 音符 | 与 CPU 差异 |
|---|---|---|---|---|
| cpu | **20.87 s** | 1688 MB | 804 | —（基准） |
| coreml（segnet only） | **21.06 s** | 1944 MB | 804 | 逐音全等 |

> 内存高约 250 MB：Core ML 需要同时保留编译后的 MLProgram 与权重。

### 3.2 单页（第 1 页，5 行谱表）

| 后端 | 第 1 次 | 第 2 次 | 峰值 RSS | 音符 |
|---|---|---|---|---|
| cpu | 4.84 s | 4.85 s | 1210 / 1191 MB | 164 |
| coreml（segnet only） | 8.41 s | 8.34 s | 1272 MB | 164 |

### 3.3 配置对比（同一页，用于选定默认值）

| 配置 | wall | 结论 |
|---|---|---|
| CPU（base） | 4.88 s | 最快 |
| Core ML：segnet only | **8.61 s** | **Apple 配置里最快 → 选为默认** |
| Core ML：segnet + encoder | 12.54 s | encoder 上 Core ML 反而多 ~4 s |
| Core ML：segnet + encoder，`MLComputeUnits=ALL` | 20.59 s | ANE 特化预热代价过大 |

### 3.4 证据：Core ML 确实生效（不是静默回退）

- 编译缓存已生成：`homr/segmentation/*_fp16.coreml_cache` 55 MB；若开启 encoder 另有 182 MB；
- 若后端参数被 shim 吞掉（曾经的缺陷，见 `repo_audit.md` F5），这两个目录**不会**出现——最初正是靠这个反证发现开关没生效。

### 3.5 怎么读这组数字

- 固定开销 ≈ 3.5 s（会话建立 + MLProgram 装载 + 绑定），所以"页数越多越划算"。
- 5 页时固定开销已基本摊平，落在噪声范围内；分水岭是**文档长度**，不是单纯页数。
- 若把"每页重建 segnet session"改成跨页复用，单页延迟有望降到 5–6 s。这是唯一值得再投入的优化，见 §5。

---

## 4. 默认值与回退

| 场景 | 建议 | 原因 |
|---|---|---|
| 整本分谱 / 多页 PDF | 默认（`auto` → Core ML） | 与 CPU 持平，但计算在 GPU/ANE，CPU 更空闲 |
| 单页片段 / 批处理大量短 PDF / CI | `--backend cpu` 或 `HOMR_BACKEND=cpu` | 快 1.7× |
| 只有 CPU 的环境 | 自动落到 CPU | provider 缺失时降级并**在日志打印实际后端** |
| 想试 encoder 也上 Core ML | `HOMR_COREML_ENCODER=1` | 已知更慢，仅供实验 |

回退保证：
- 推理期 Core ML 异常会命中 `_is_gpu_err`（已含 `coreml` 关键字）→ 当页及其后各页回退 CPU 重试；
- 日志永远打印**实际运行**的后端（`[homr] 推理后端: …`），不把请求值当结果；
- `auto` 在没有 CoreML 的机器上仍是 CPU。

---

## 5. 唯一值得继续做的实验

**跨页复用 Core ML 会话。** 现状：homr 的 `Segnet` 在每次 `inference()` 里新建（每页 1 次，单页内复用 16 次推理），encoder 是模块级单例。
已实测 session 创建本身只要 0.2 s，所以省的不是创建时间，而是**每次会话都要重新装载 MLProgram / 绑定 device** 的固定成本。

做法：在 `core/omr/` 里用一个按 `use_gpu` 键缓存 `Segnet` 的工厂替换模块内名字（不动 homr 源码），并加 homr 版本守卫。
预期：单页 8.4 s → 5–6 s；整本不变。
验收：`scripts/bench_backends.py --pdf <样本> --page 1` 单页 ≥1.2× 提升，且 `diffs_vs` 逐音全等。

---

## 6. 不建议做的事

- 不要覆盖 homr 对 segnet/encoder/decoder 的差异化处理（fp16/fp32、MLProgram、decoder 不上 CoreML）：那是踩过坑的结论。
- 不要把 `transformer_use_gpu=True` 当作"开 Core ML"。
- 不要用 `MLComputeUnits=ALL` 做默认：实测更慢。
- 不要在 CI/回归里用 Core ML 跑基准：噪声大且依赖 GPU 状态；用 CPU 跑正确性回归。
