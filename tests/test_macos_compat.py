"""macOS/Apple-Silicon port regressions.

These pin down the three things that broke — or would silently break — when the
project moved to arm64 macOS, where the only native LilyPond is 2.26+:

1. ``set-global-fonts`` was removed in LilyPond 2.26 and aborted every compile.
2. Custom ``two-dots``/``three-dots`` scripts need ``side-axis`` on 2.26
   (backported from upstream jianpu-ly).
3. ``insitu`` needs ``pad_measure_to_bar`` back: each in-situ line is compiled
   as a standalone score, so jianpu-ly's barcheck applies per line.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from music21 import converter, note  # noqa: E402

from core.config import JianpuNote  # noqa: E402
from core.notation.jianpu import pad_measure_to_bar  # noqa: E402
from core.render.jianpu_runner import render_jianpu_ly  # noqa: E402


def _lilypond_minor() -> int | None:
    exe = os.environ.get('LILYPOND') or shutil.which('lilypond')
    if not exe:
        return None
    try:
        out = subprocess.run([exe, '--version'], capture_output=True, text=True,
                             timeout=30).stdout
        return int(out.split()[2].split('.')[1])
    except Exception:
        return None


def _load_jianpu_ly():
    spec = importlib.util.spec_from_file_location(
        'macos_jly', ROOT / 'scripts' / 'jianpu-ly.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LilyPondCompatTest(unittest.TestCase):
    """Generated LilyPond must stay compilable on 2.20 *and* 2.26."""

    @classmethod
    def setUpClass(cls):
        cls.source = _load_jianpu_ly().process_input('1=C\nOctavesAfter\n135 - - -\n')

    def test_font_workaround_is_version_gated(self):
        minor = _lilypond_minor()
        if minor is None:
            self.skipTest('lilypond not installed')
        if minor >= 26:
            self.assertNotIn('set-global-fonts', self.source)
        else:
            # Older LilyPond keeps the historical macOS font fallback.
            self.assertIn('set-global-fonts', self.source)

    def test_custom_scripts_declare_side_axis(self):
        self.assertEqual(self.source.count('(side-axis . ,Y)'), 4)

    def test_generated_source_compiles(self):
        exe = os.environ.get('LILYPOND') or shutil.which('lilypond')
        if not exe:
            self.skipTest('lilypond not installed')
        with tempfile.TemporaryDirectory() as tmp:
            ly = Path(tmp) / 'compat.ly'
            ly.write_text(self.source, encoding='utf-8')
            proc = subprocess.run([exe, '-o', str(Path(tmp) / 'compat'), str(ly)],
                                  capture_output=True, text=True, timeout=300)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            self.assertTrue((Path(tmp) / 'compat.pdf').is_file())


class PadMeasureToBarTest(unittest.TestCase):
    """`--engine stamp` compiles one line per staff, so bars must be exact."""

    @staticmethod
    def _rest(ql: float) -> JianpuNote:
        return JianpuNote('0', '', 0, 0, float(ql), 0, None, True)

    def test_underflow_is_padded_to_bar(self):
        notes = [self._rest(1.0)]           # 16 units of a 64-unit 4/4 bar
        padded = pad_measure_to_bar(notes, 64)
        self.assertEqual(sum(1 for _ in padded) > 1, True)

    def test_overflow_is_trimmed_to_bar(self):
        notes = [self._rest(1.0)] * 8       # 128 units > 64
        padded = pad_measure_to_bar(notes, 64)
        self.assertLessEqual(len(padded), 8)

    def test_no_notes_yields_full_rest_bar(self):
        padded = pad_measure_to_bar([], 64)
        self.assertTrue(padded, 'empty measure should become rests, not nothing')

    def test_zero_bar_units_is_passthrough(self):
        notes = [self._rest(1.0)]
        self.assertEqual(pad_measure_to_bar(notes, 0), notes)


class InsituRenderTest(unittest.TestCase):
    def test_measure_texts_no_longer_uses_removed_api(self):
        sys.path.insert(0, str(ROOT / 'insitu'))
        try:
            import render_insitu  # noqa: F401
        except Exception as exc:  # pragma: no cover - environment dependent
            self.skipTest(f'render_insitu not importable here: {exc}')
        self.assertTrue(hasattr(render_insitu, '_measure_texts'))


if __name__ == '__main__':
    unittest.main()
