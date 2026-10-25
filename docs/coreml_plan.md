# Core ML 适配方案与实测结论

- 日期：2026-10-25
- 机器：Apple Silicon（arm64），macOS 27.0.1
- 运行时：onnxruntime 1.31.0、homr 0.7.0、Python 3.11.17
- 原始数据：`docs/bench_coreml.json`（单页）、`docs/bench_coreml_full.json`（5 页）

---

## 1. 结论先行

1. **Core ML 的接线已经完成并可复现**，不是"检测到 provider 就宣布成功"：编译缓存、输出等价性、耗时三项都有证据。
2. **但在当前组合下它更慢**：整本 5 页 +11%，单页 +140%。因此**默认不用**，`--backend auto` 在 macOS 上解析为 CPU；要试必须显式 `--backend coreml`。
3. 慢的原因是**结构性**的，不是配置问题：homr 每页都新建 ONNX session，Core ML 的 MLProgram 编译/绑定成本按页重复支付；单页推理本身的收益 < 会话开销。
4. 因此 Core ML 不应阻塞主链路（符合交接文档 §9 的 DoD 排序）。要继续投入，先做 §5 的三个实验，任意一个能把"每页会话成本"摊掉，才值得继续。

---

## 2. 为什么不需要自己写 provider 管线

homr 0.7.0 已内置 Apple 支持（`homr/onnx_providers.py`），且**按模型区别对待**：

| 模型 | 能否上 Core ML | 说明 |
|---|---|---|
| segnet | ✅ | fp16 模型；必须 `ModelFormat=MLProgram`，否则几乎不接节点、静默退回 CPU |
| transformer encoder | ✅（opt-in） | 必须用 fp16 权重；`coreml_encoder=True` |
| transformer decoder | ❌ | 动态 KV-cache 维度在 MLProgram 下崩溃；固定 CPU fp32（且 CPU fp32 比 CPU fp16 快） |

注意 Core ML EP **不暴露 device memory**，输入输出仍绑定在 CPU（`io_binding_device = "cpu"`），与 CUDA 的 `"cuda"` 不同。

所以本仓库的改动只是"把开关接上 + 平台语义正确"，共两处：

- `core/omr/homr_runner.py`：新增 `_resolve_inference_backend()` / `_backend_from_flags()`，把 `auto|cpu|coreml|cuda` 映射为 `(segnet_use_gpu, transformer_use_gpu, coreml_encoder)`；
- `jianpu.py`：新增 `--backend`，并保留 `--gpu` 旧语义。

关键映射（`coreml`）：`segnet_gpu=True, transformer_gpu=False, coreml_encoder=True`。
**不能**像 CUDA 那样把 `transformer_use_gpu` 也设为 True——那会让 decoder 走 fp16 + 尝试 Core ML，直接失败。

---

## 3. 实测数据

同一输入、同一机器、每个后端独立子进程（冷启动计入）：

### 3.1 单页（`曲笛.pdf` 第 1 页）

| 后端 | 第 1 次 | 第 2 次 | 峰值 RSS | 音符 | 与 CPU 差异 |
|---|---|---|---|---|---|
| cpu | 5.11 s | 5.09 s | 1211 / 1190 MB | 164 | — |
| coreml | 13.68 s | 12.23 s | 1273 / 1272 MB | 164 | 0（音高序列逐音相同） |

### 3.2 整本（`曲笛.pdf`，5 页，193 小节）

| 后端 | wall | 峰值 RSS | 音符 | 与 CPU 差异 |
|---|---|---|---|---|
| cpu | **21.63 s** | 1695 MB | 804 | — |
| coreml | **24.16 s** | 1723 MB | 804 | 0（小节/音符/休止/音高序列全等） |

### 3.3 证据：Core ML 确实生效

- 编译缓存已生成：`homr/segmentation/*_fp16.coreml_cache` 55 MB、`homr/transformer/*_fp16.coreml_cache` 182 MB；
- 若参数被吞（见 `repo_audit.md` F5），这两个目录**不会**出现——最初正是靠这个反证发现开关没生效的。

### 3.4 解读

- 单页 +8.6 s ≈ 一次 MLProgram 会话建立 + 编译（缓存命中也要加载 240 MB 权重）。
- 5 页只慢 2.5 s，说明**每页边际成本**已接近 CPU：`(24.16-?)/5` vs `21.63/5 ≈ 4.3 s/页`。
- 仍然没有正收益：segnet/encoder 的计算量不足以抵消 ANE/GPU 的数据搬运与绑定成本（Core ML EP 的 IO 在 CPU）。

---

## 4. 可回退性

- `--backend` 缺省为 `None` → `auto`；macOS 上 `auto` = **CPU**，即"不会因为装了 Core ML 就悄悄变慢"。
- 显式 `coreml` 但 provider 缺失 → 解析为 `cpu`，并且**日志打印实际后端**（`[homr] 推理后端: CPU …`），不会谎报。
- 推理期 GPU/CoreML 异常 → 命中 `_is_gpu_err`（已加入 `coreml` 关键字）→ 当页与后续页回退 CPU 重试。
- 环境变量 `HOMR_BACKEND` 可给 GUI / 批处理统一设默认值。

---

## 5. 下一步实验（按性价比排序）

1. **跨页复用 session**（最可能翻盘）
   homr 的 `Segnet`/encoder 在每次 `process_image()` 里重新构造；若在 `homr_runner` 的多页循环里复用同一 session（甚至只复用 Core ML 已编译的 `MLModel`），单页 ~8.6 s 的固定开销会被 193 小节摊平。
   风险：homr 内部 API 非公开，升级会破；建议以 monkeypatch 形式封装在 `core/omr/` 并加版本守卫。
2. **`MLComputeUnits` 调参**
   现在 segnet 用 `CPUAndGPU`（跳过 ANE 特化）。可分别测 `ALL` / `CPUAndGPU` / `CPUOnly`，encoder 也各测一遍；用 `HOMR_COREML_COMPUTE_UNITS` 已可无代码对比。
3. **换更大页面/更高 DPI 的样本**
   当前样例是 5 页、每页 5–9 行。若真实乐谱是 300 DPI 扫描件或总谱（每页 20+ 行），segnet 的 patch 数上升，Core ML 才可能跑赢 CPU。**必须用 `scripts/bench_backends.py --pdf <样本>` 复测，不能凭这两份报告外推。**

只有当 1 或 3 出现 **≥1.2× 加速且输出逐音一致** 时，才把 macOS 的 `auto` 改为 coreml。

---

## 6. 不建议做的事

- 不要自己写一套 Core ML EP 的 provider 选择逻辑覆盖 homr 的：homr 对 segnet/encoder/decoder 的差异化处理（fp16/fp32、MLProgram、decoder 不上 CoreML）是踩过坑的结论，覆盖会引入难查的崩溃。
- 不要把 `transformer_use_gpu=True` 当作"开 CoreML"的开关。
- 不要在 CPU 基线未通过验收的产品版本里默认启用 Core ML。
