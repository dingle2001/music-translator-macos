# 版本日志

## 2026-11-15 · macOS 硬件加速与低内存适配

- Mac 窗口、单文件命令和批处理新增 Core ML GPU 与 Apple 神经网络引擎（ANE）选择。自动模式检测可用的推理后端与内存，内存紧张时使用 CPU。
- 同一份多页谱复用 SegNet Core ML 会话。8 GB 及以下的 Mac 默认限制 SegNet 批大小，内存越紧张，批大小越低。加速执行失败时可使用小批次 CPU 重试，回退结果可继续导出。
- 转换日志增加所选计算单元、Core ML 会话激活、跨页复用与回退信息。可启用 Core ML 计算计划诊断，查看算子的首选设备。
- Mac 应用按当前架构构建。Intel 路径可用 x86_64 的依赖和 LilyPond 将已有 MusicXML/MXL 转成简谱。已在 Rosetta 验证导入和导出，完整的 Intel Homr 环境仍受依赖轮子限制。
- 实测 M5 Max 的五页《曲笛》识谱耗时，CPU 20.71 秒、Core ML GPU 14.94 秒、Core ML ANE 20.87 秒。三种模式的音高、起点、时值及休止序列一致。批大小为 1 的模式也通过样谱验证。测试范围与复现命令见 [macOS 安装与使用](docs/macos_setup.md#7-硬件加速与低内存设置)。
