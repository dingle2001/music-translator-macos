#!/usr/bin/env python3
"""Batch-regenerate all 20 吹管 scores (OMR -> reconcile -> per-measure blank render).

Each 曲子 subdirectory is its own batch.py invocation, mirroring the existing
output layout output_fixed/吹管/<曲子>/.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GROUPS = ['小河淌水', '渔歌', '雨夜花', '黑走马']


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'input' / '吹管')
    parser.add_argument('--output', type=Path, default=ROOT / 'output_fixed' / '吹管')
    parser.add_argument('--backend', choices=('auto', 'cpu', 'coreml', 'cuda'), default='auto')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / 'batch_20_run.log').open('w', encoding='utf-8') as log:
        return run_groups(args, log)


def run_groups(args, log) -> int:
    def emit(msg: str) -> None:
        line = f'[{time.strftime("%F %T")}] {msg}'
        print(line, flush=True)
        log.write(line + '\n')
        log.flush()

    emit('start batch (20 scores)')
    failed_groups = 0
    total_start = time.time()
    for group in GROUPS:
        in_dir = args.input / group
        out_dir = args.output / group
        emit(f'=== group {group} ===')
        cmd = [
            sys.executable, '-u', str(ROOT / 'batch.py'), str(in_dir.resolve()),
            '-o', str(out_dir.resolve()),
            '--mode', 'both', '--layout', 'single',
            '--pitch-mode', 'fixed', '--fixed-tonic', 'C', '--backend', args.backend,
        ]
        g0 = time.time()
        proc = subprocess.run(cmd, cwd=str(ROOT), stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True)
        log.write(proc.stdout)
        log.flush()
        emit(f'group {group} finished rc={proc.returncode} ({time.time()-g0:.0f}s)')
        if proc.returncode != 0:
            failed_groups += 1

    emit(f'DONE. groups_failed={failed_groups} total={time.time()-total_start:.0f}s')
    emit('--- generated insitu PDFs ---')
    for p in sorted(args.output.glob('*/*.insitu.pdf')):
        emit(f'  {p.relative_to(args.output)}  ({p.stat().st_size} bytes)')
    return int(bool(failed_groups))


if __name__ == '__main__':
    raise SystemExit(main())
