#!/usr/bin/env python
"""Benchmark OMR inference backends (CPU vs Core ML) on macOS Apple Silicon.

Every backend runs in its **own subprocess**, so cold-start costs (ONNX Runtime
session creation, Core ML MLProgram compilation) are measured honestly instead
of being amortised inside one long-lived interpreter.

What is measured
----------------
* wall time of the OMR stage only (PDF → MusicXML; no LilyPond typesetting), and
* peak RSS of that subprocess (``resource.getrusage``), and
* a structural diff of the resulting MusicXML against the reference backend
  (measure count, note/rest count, sounding-pitch sequence).

The diff matters more than the timings: a faster backend that drops or invents a
note is a regression, not an optimisation (see docs/repo_audit.md).

Usage
-----
    # single page, CPU vs Core ML, 2 runs each (2nd run = warm model cache)
    python scripts/bench_backends.py --pdf 曲笛.pdf --page 1 \
        --backends cpu,coreml --repeat 2

    # whole PDF, JSON report for docs
    python scripts/bench_backends.py --pdf 曲笛.pdf --out docs/bench_coreml.json

Notes
-----
* ``cpu``   → fp32 segnet + fp32 transformer, CPUExecutionProvider only.
* ``coreml``→ fp16 segnet on CoreML, fp16 encoder on CoreML, decoder on CPU
  (the decoder cannot run on the Core ML EP: dynamic KV-cache dimension).
* Core ML compiles the encoder to an MLProgram the first time; homr caches it
  next to the model file, so the first ``coreml`` run is expected to be slow.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

_CHILD = r'''
import json, resource, sys, time, traceback
from pathlib import Path
sys.path.insert(0, {repo!r})
from _env import ensure_sumisora  # noqa: E402
ensure_sumisora()
import homr_shim  # noqa: E402
homr_shim.install(verbose=False)
from core.omr.homr_runner import run_homr_batch  # noqa: E402

pdf, out_dir, backend = Path({pdf!r}), Path({out!r}), {backend!r}
t0 = time.perf_counter()
error = None
try:
    res = run_homr_batch(pdf, out_dir, backend=backend)
    if res is None:
        error = "run_homr_batch returned None"
except Exception:
    error = traceback.format_exc(limit=3)
wall = time.perf_counter() - t0
rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
print("__RESULT__" + json.dumps({{"backend": backend, "wall_s": wall,
                                  "peak_rss_mb": rss_mb, "error": error}}))
'''


def _single_page(pdf: Path, page: int, workdir: Path) -> Path:
    """Extract a 1-based *page* into its own PDF so runs are comparable."""
    import pymupdf

    src = pymupdf.open(str(pdf))
    dst = pymupdf.open()
    dst.insert_pdf(src, from_page=page - 1, to_page=page - 1)
    out = workdir / f'{pdf.stem}_p{page}.pdf'
    dst.save(str(out))
    return out


def _run_backend(pdf: Path, backend: str, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    code = _CHILD.format(repo=str(REPO), pdf=str(pdf), out=str(out_dir), backend=backend)
    proc = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        if line.startswith('__RESULT__'):
            return json.loads(line[len('__RESULT__'):])
    return {'backend': backend, 'wall_s': None, 'peak_rss_mb': None,
            'error': (proc.stderr or proc.stdout)[-1500:]}


def _summarise_mxl(mxl: Path) -> dict:
    """Structural fingerprint of a MusicXML file (backend-independent view)."""
    from music21 import converter, chord, note

    score = converter.parse(str(mxl))
    pitches: list[str] = []
    measures = 0
    notes = 0
    rests = 0
    for part in score.parts:
        for m in part.getElementsByClass('Measure'):
            measures += 1
            for el in m.flatten().notesAndRests:
                if isinstance(el, note.Rest):
                    rests += 1
                elif isinstance(el, chord.Chord):
                    notes += 1
                    pitches.append('+'.join(p.nameWithOctave for p in el.pitches))
                else:
                    notes += 1
                    pitches.append(el.pitch.nameWithOctave)
    return {'measures': measures, 'notes': notes, 'rests': rests,
            'pitches': pitches}


def _diff(ref: dict, other: dict) -> dict:
    a, b = ref['pitches'], other['pitches']
    first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None)
    return {
        'measures_delta': other['measures'] - ref['measures'],
        'notes_delta': other['notes'] - ref['notes'],
        'rests_delta': other['rests'] - ref['rests'],
        'pitch_sequence_identical': a == b,
        'first_pitch_mismatch_at': first,
        'first_pitch_mismatch': None if first is None else {'ref': a[first], 'other': b[first]},
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description='Benchmark OMR backends (CPU vs Core ML)')
    ap.add_argument('--pdf', type=Path, required=True)
    ap.add_argument('--page', type=int, default=None, help='只跑第 N 页（1-based）')
    ap.add_argument('--backends', default='cpu,coreml')
    ap.add_argument('--repeat', type=int, default=1, help='每个后端重复次数（取最好一次）')
    ap.add_argument('--out', type=Path, default=None, help='JSON 报告输出路径')
    args = ap.parse_args(argv)

    pdf = args.pdf.resolve()
    if not pdf.is_file():
        ap.error(f'找不到输入: {pdf}')

    workroot = Path(tempfile.mkdtemp(prefix='bench_backends_'))
    try:
        target = _single_page(pdf, args.page, workroot) if args.page else pdf
        backends = [b.strip() for b in args.backends.split(',') if b.strip()]
        report = {'pdf': pdf.name, 'page': args.page, 'python': sys.version.split()[0],
                  'runs': {}, 'rss_note': 'peak RSS of the OMR subprocess only'}

        fingerprints: dict[str, dict] = {}
        for backend in backends:
            runs = []
            for i in range(args.repeat):
                out_dir = workroot / f'{backend}_{i}'
                res = _run_backend(target, backend, out_dir)
                mxl = next(iter(sorted(out_dir.glob('*.musicxml'))), None)
                res['run'] = i + 1
                res['musicxml'] = str(mxl) if mxl else None
                if mxl:
                    try:
                        fp = _summarise_mxl(mxl)
                        res['measures'] = fp['measures']
                        res['notes'] = fp['notes']
                        res['rests'] = fp['rests']
                        fingerprints.setdefault(backend, fp)
                    except Exception as exc:  # pragma: no cover - defensive
                        res['parse_error'] = repr(exc)
                runs.append(res)
                status = 'ok' if not res.get('error') else 'FAILED'
                print(f'[{backend} run {i + 1}] {status} '
                      f'wall={res["wall_s"]:.2f}s rss={res["peak_rss_mb"]:.0f}MB '
                      f'notes={res.get("notes")}', flush=True)
            ok = [r for r in runs if r.get('wall_s') and not r.get('error')]
            report['runs'][backend] = {
                'attempts': runs,
                'best_wall_s': min((r['wall_s'] for r in ok), default=None),
                'peak_rss_mb': max((r['peak_rss_mb'] for r in ok), default=None),
                'notes': ok[0].get('notes') if ok else None,
                'measures': ok[0].get('measures') if ok else None,
            }

        ref = backends[0]
        if ref in fingerprints:
            for backend in backends[1:]:
                if backend in fingerprints:
                    report.setdefault('diffs_vs', {})[backend] = _diff(
                        fingerprints[ref], fingerprints[backend])

        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'\n报告已写入 {args.out}')
        return 0
    finally:
        shutil.rmtree(workroot, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
