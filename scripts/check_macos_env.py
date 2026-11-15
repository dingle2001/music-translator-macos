#!/usr/bin/env python
"""Apple Silicon environment check for music_translator.

Prints one PASS / WARN / FAIL line per requirement and exits non-zero when a
hard requirement is missing.  Run it with the *same* interpreter that runs
``jianpu.py`` (i.e. the venv's python):

    .venv/bin/python scripts/check_macos_env.py

Why a script instead of prose: every one of these checks has bitten us at least
once during the macOS port (PyMuPDF 2.x, LilyPond 2.26, missing ONNX providers,
half-downloaded model weights), and each one produces a different symptom much
later in the pipeline.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

_RESULTS: list[tuple[str, str, str]] = []  # (status, name, detail)


def ok(name: str, detail: str = '') -> None:
    _RESULTS.append(('PASS', name, detail))


def warn(name: str, detail: str = '') -> None:
    _RESULTS.append(('WARN', name, detail))


def fail(name: str, detail: str = '') -> None:
    _RESULTS.append(('FAIL', name, detail))


def _check_platform() -> None:
    machine = platform.machine()
    if machine == 'arm64':
        ok('CPU 架构', f'arm64, macOS {platform.mac_ver()[0]}')
    else:
        fail('CPU 架构', f'{machine}（本项目以 Apple Silicon/arm64 为基线）')
    if sys.version_info < (3, 11):
        fail('Python 版本', f'{platform.python_version()}（homr 0.7 要求 >= 3.11）')
    else:
        ok('Python 版本', f'{platform.python_version()} {platform.machine()} @ {sys.executable}')
    if sys.prefix == sys.base_prefix:
        warn('虚拟环境', '当前不是 venv；依赖可能污染系统 Python')
    else:
        ok('虚拟环境', sys.prefix)


def _check_packages() -> None:
    for mod, minimum, note in [
        ('pymupdf', (1, 24), 'PDF 读写/矢量几何'),
        ('music21', (9, 0), 'MusicXML 解析与乐理'),
        ('homr', (0, 7), 'OMR 推理'),
        ('onnxruntime', (1, 24), 'ONNX 推理后端'),
        ('PIL', (10, 0), '图像处理'),
        ('rich', (13, 0), '终端校对界面'),
    ]:
        try:
            m = __import__(mod)
        except Exception as exc:
            fail(f'依赖 {mod}', f'无法导入: {exc}')
            continue
        ver = getattr(m, '__version__', None) or getattr(m, 'VERSION', '?')
        ok(f'依赖 {mod}', f'{ver} — {note}')
        try:
            parts = tuple(int(x) for x in str(ver).split('.')[:2])
        except Exception:
            continue
        if parts and parts < minimum:
            warn(f'依赖 {mod} 版本', f'{ver} 低于建议值 {".".join(map(str, minimum))}')

    try:
        import pymupdf  # noqa: F401
        ok('PyMuPDF 导入名', 'import pymupdf 可用（不再依赖已弃用的 fitz 别名）')
    except Exception:
        warn('PyMuPDF 导入名', '仅 fitz 可用；PyMuPDF 2.x 会告警，建议 import pymupdf')


def _check_ort_providers() -> None:
    try:
        import onnxruntime as ort
    except Exception as exc:
        fail('ONNX Runtime', f'导入失败: {exc}')
        return
    providers = ort.get_available_providers()
    detail = f'{ort.__version__}: {providers}'
    if 'CPUExecutionProvider' not in providers:
        fail('CPUExecutionProvider', detail)
    else:
        ok('CPUExecutionProvider', detail)
    if 'CoreMLExecutionProvider' in providers:
        ok('CoreMLExecutionProvider', '可用。Apple Silicon 可用 --backend coreml-gpu 或 coreml-ane。')
    else:
        warn('CoreMLExecutionProvider',
             'Core ML 不可用，识谱使用 CPU。Apple Silicon 可检查 Python 和 ONNX Runtime 是否为 arm64。')
    if 'CUDAExecutionProvider' in providers or 'DmlExecutionProvider' in providers:
        ok('CUDA/DirectML', '存在（非 macOS 常规路径，注意 provider 混装）')


def _check_homr_weights() -> None:
    try:
        from homr.transformer import configs
        paths = configs.FilePaths()
    except Exception as exc:
        fail('homr 模型路径', f'无法解析: {exc}')
        return
    try:
        from homr.segmentation import config as segnet_config
        segnet_fp32 = Path(segnet_config.segnet_path_onnx)
        segnet_fp16 = Path(segnet_config.segnet_path_onnx_fp16)
    except Exception:
        segnet_fp32 = segnet_fp16 = Path(configs.workspace) / 'missing.onnx'
    models = {
        'segnet fp32': segnet_fp32,
        'segnet fp16': segnet_fp16,
        'encoder fp32': Path(paths.encoder_path),
        'decoder fp32': Path(paths.decoder_path),
        'encoder fp16': Path(paths.encoder_path_fp16),
    }
    # segnet 文件名带版本哈希，直接扫目录更稳。
    seg = sorted(segnet_fp32.parent.glob('segnet*.onnx')) if segnet_fp32.parent.is_dir() else []
    for label, path in models.items():
        if path.is_file():
            ok(f'模型 {label}', f'{path.name} ({path.stat().st_size // (1024 * 1024)} MB)')
        else:
            hint = '首次 OMR 会自动下载' if 'fp16' in label else '首次 OMR 会自动下载（需联网）'
            warn(f'模型 {label}', f'缺失: {path.name} — {hint}')
    if seg:
        ok('segnet 权重', ', '.join(p.name for p in seg))
    else:
        warn('segnet 权重', '目录中未找到 segnet*.onnx')


def _check_lilypond() -> None:
    exe = os.environ.get('LILYPOND') or shutil.which('lilypond')
    if not exe:
        fail('LilyPond', '未找到：安装 lilypond 2.22+ 或设置 $LILYPOND')
        return
    try:
        out = subprocess.run([exe, '--version'], capture_output=True, text=True, timeout=30).stdout
    except Exception as exc:
        fail('LilyPond', f'{exe} 无法执行: {exc}')
        return
    line = out.splitlines()[0] if out else '?'
    ok('LilyPond', f'{exe} — {line}')
    try:
        minor = int(line.split()[2].split('.')[1])
    except Exception:
        warn('LilyPond 版本', f'无法解析版本行: {line}')
        return
    if minor >= 26:
        patched = (REPO / 'scripts' / 'jianpu-ly.py').is_file() and \
            '(side-axis . ,Y)' in (REPO / 'scripts' / 'jianpu-ly.py').read_text(encoding='utf-8')
        if patched:
            ok('LilyPond 2.26 兼容补丁', 'jianpu-ly.py 已含 side-axis / set-global-fonts 版本门')
        else:
            fail('LilyPond 2.26 兼容补丁',
                 '未打补丁：2.26 移除了 set-global-fonts，且自定义 Script 缺少 side-axis，编译会失败')
    if platform.machine() == 'arm64' and 'arm64' not in line and 'x86' in line:
        warn('LilyPond 架构', '当前为 x86_64 构建（需 Rosetta），建议用 2.26+ arm64 原生包')


def _check_misc() -> None:
    sys.path.insert(0, str(REPO))
    from core.app.runtime_finder import find_audiveris_executable

    font = Path('/Library/Fonts/Arial Unicode.ttf')
    if font.exists():
        ok('Arial Unicode', f'{font} 存在（jianpu-ly 的 macOS 字体回退会生效，2.26 已自动跳过）')
    else:
        ok('Arial Unicode', '不存在（不需要字体回退）')
    audiveris = find_audiveris_executable()
    if audiveris:
        ok('Audiveris', str(audiveris))
    else:
        warn('Audiveris', '可选引擎未安装，安装说明见 docs/macos_setup.md')
    sample = REPO / 'tests' / 'fixtures' / 'sheng.pdf'
    ok('测试样本', f'{sample.name} 存在' if sample.exists() else '缺少 tests/fixtures 样本')


def main() -> int:
    print(f'music_translator macOS 环境检查 — {platform.platform()}\n')
    _check_platform()
    _check_packages()
    _check_ort_providers()
    _check_homr_weights()
    _check_lilypond()
    _check_misc()

    width = max(len(n) for _, n, _ in _RESULTS)
    for status, name, detail in _RESULTS:
        mark = {'PASS': '✓', 'WARN': '!', 'FAIL': '✗'}[status]
        print(f'{mark} {status:4s} {name.ljust(width)}  {detail}')

    fails = sum(1 for s, _, _ in _RESULTS if s == 'FAIL')
    warns = sum(1 for s, _, _ in _RESULTS if s == 'WARN')
    print(f'\n{len(_RESULTS)} 项检查：{fails} 失败 / {warns} 警告')
    if fails:
        print('先修复 FAIL 项，否则 OMR 或排版链路会在更靠后的步骤失败。')
    return 1 if fails else 0


if __name__ == '__main__':
    raise SystemExit(main())
