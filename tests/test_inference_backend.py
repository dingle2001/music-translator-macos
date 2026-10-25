"""Inference-backend selection (CPU / Core ML / CUDA) on Apple Silicon.

The port must never *claim* a backend it is not actually running: on macOS the
only accelerator is the Core ML EP, and only segnet + the transformer encoder can
use it (the decoder cannot — dynamic KV-cache dimension). These tests pin the
flag mapping and the graceful fallback, without requiring a model run.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.omr import homr_runner  # noqa: E402


def _providers(*names: str):
    return mock.patch.object(homr_runner, '_available_providers',
                             return_value=set(names))


class BackendResolutionTest(unittest.TestCase):
    def test_cpu_never_uses_accelerator(self):
        with _providers('CPUExecutionProvider', 'CoreMLExecutionProvider'):
            bk = homr_runner._resolve_inference_backend('cpu')
        self.assertEqual(bk['name'], 'cpu')
        self.assertFalse(bk['segnet_gpu'])
        self.assertFalse(bk['transformer_gpu'])
        self.assertFalse(bk['coreml_encoder'])

    def test_coreml_keeps_decoder_on_cpu(self):
        with _providers('CPUExecutionProvider', 'CoreMLExecutionProvider'):
            bk = homr_runner._resolve_inference_backend('coreml')
        self.assertEqual(bk['name'], 'coreml')
        self.assertTrue(bk['segnet_gpu'])
        self.assertFalse(bk['transformer_gpu'],
                         'decoder cannot run on the Core ML EP; transformer must stay CPU')
        self.assertTrue(bk['coreml_encoder'])

    def test_auto_prefers_coreml_on_mac(self):
        with _providers('CPUExecutionProvider', 'CoreMLExecutionProvider'):
            self.assertEqual(homr_runner._resolve_inference_backend('auto')['name'], 'coreml')

    def test_auto_prefers_cuda_when_present(self):
        with _providers('CPUExecutionProvider', 'CUDAExecutionProvider'):
            bk = homr_runner._resolve_inference_backend('auto')
        self.assertEqual(bk['name'], 'cuda')
        self.assertTrue(bk['transformer_gpu'])

    def test_unavailable_backend_degrades_to_cpu(self):
        with _providers('CPUExecutionProvider'):
            for requested in ('coreml', 'cuda'):
                with self.subTest(requested=requested):
                    bk = homr_runner._resolve_inference_backend(requested)
                    self.assertEqual(bk['name'], 'cpu',
                                     'must report what actually runs, not what was asked for')

    def test_unknown_backend_is_auto(self):
        with _providers('CPUExecutionProvider'):
            self.assertEqual(
                homr_runner._resolve_inference_backend('tensorrt')['name'], 'cpu')

    def test_env_var_is_honoured(self):
        with _providers('CPUExecutionProvider', 'CoreMLExecutionProvider'), \
                mock.patch.dict(os.environ, {'HOMR_BACKEND': 'cpu'}):
            self.assertEqual(homr_runner._resolve_inference_backend()['name'], 'cpu')

    def test_legacy_gpu_flag_still_means_cpu_when_off(self):
        with _providers('CPUExecutionProvider', 'CoreMLExecutionProvider'):
            self.assertEqual(homr_runner._backend_from_flags(False)['name'], 'cpu')
            self.assertEqual(homr_runner._backend_from_flags(True)['name'], 'coreml')

    def test_real_machine_never_raises(self):
        # Whatever this machine exposes, resolution must succeed and agree with ORT.
        bk = homr_runner._resolve_inference_backend('auto')
        self.assertIn(bk['name'], ('cpu', 'coreml', 'cuda'))
        if bk['name'] == 'coreml':
            self.assertIn('CoreMLExecutionProvider', homr_runner._available_providers())


if __name__ == '__main__':
    unittest.main()
