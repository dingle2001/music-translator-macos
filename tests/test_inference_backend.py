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
from core.omr.apple_coreml import AppleInferenceRun, install_coreml_hooks  # noqa: E402


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

    def test_coreml_encoder_is_opt_in(self):
        with _providers('CPUExecutionProvider', 'CoreMLExecutionProvider'):
            self.assertFalse(homr_runner._resolve_inference_backend('coreml')['coreml_encoder'],
                             'segnet-only is the faster shipped default')
        with _providers('CPUExecutionProvider', 'CoreMLExecutionProvider'), \
                mock.patch.dict(os.environ, {'HOMR_COREML_ENCODER': '1'}):
            self.assertTrue(homr_runner._resolve_inference_backend('coreml')['coreml_encoder'])

    def test_auto_accelerates_on_mac(self):
        with (_providers('CPUExecutionProvider', 'CoreMLExecutionProvider'),
              mock.patch.object(homr_runner.sys, 'platform', 'darwin'),
              mock.patch.object(homr_runner.platform, 'machine', return_value='arm64')):
            self.assertEqual(homr_runner._resolve_inference_backend('auto', available_memory_mb=6000)['name'], 'coreml')
            self.assertEqual(homr_runner._resolve_inference_backend('auto', available_memory_mb=1600)['name'], 'cpu')
            ane = homr_runner._resolve_inference_backend('coreml-ane', available_memory_mb=1600)
            self.assertEqual(ane['compute_units'], 'CPUAndNeuralEngine')

    def test_explicit_gpu_mode_overrides_environment_and_intel_auto_uses_cpu(self):
        with (_providers('CPUExecutionProvider', 'CoreMLExecutionProvider'),
              mock.patch.object(homr_runner.sys, 'platform', 'darwin'),
              mock.patch.object(homr_runner.platform, 'machine', return_value='x86_64'),
              mock.patch.dict(os.environ, {'HOMR_COREML_COMPUTE_UNITS': 'ALL'})):
            self.assertEqual(homr_runner._resolve_inference_backend('auto', available_memory_mb=6000)['name'], 'cpu')
            self.assertEqual(homr_runner._resolve_inference_backend('coreml-ane')['name'], 'cpu')
            self.assertEqual(homr_runner._resolve_inference_backend('coreml-gpu')['compute_units'], 'CPUAndGPU')
            self.assertEqual(homr_runner._resolve_inference_backend('coreml')['compute_units'], 'ALL')

    def test_8gb_mac_caps_segnet_batch_and_reduces_it_under_pressure(self):
        with (mock.patch.object(homr_runner.sys, 'platform', 'darwin'),
              mock.patch.object(homr_runner.os, 'sysconf', side_effect=lambda key: {
                  'SC_PHYS_PAGES': 524288, 'SC_PAGE_SIZE': 16384}[key], create=True),
              mock.patch.dict(os.environ, {'HOMR_SEGNET_BATCH_SIZE': ''})):
            self.assertEqual(homr_runner._compute_segnet_batch_size(5000), 4)
            self.assertEqual(homr_runner._compute_segnet_batch_size(1500), 2)
            self.assertEqual(homr_runner._compute_segnet_batch_size(900), 1)

    def test_auto_prefers_cuda_when_present(self):
        with _providers('CPUExecutionProvider', 'CUDAExecutionProvider'):
            bk = homr_runner._resolve_inference_backend('auto')
        self.assertEqual(bk['name'], 'cuda')
        self.assertTrue(bk['transformer_gpu'])

    def test_unavailable_backend_degrades_to_cpu(self):
        with _providers('CPUExecutionProvider'):
            for requested in ('coreml', 'coreml-gpu', 'coreml-ane', 'cuda'):
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

    def test_legacy_gpu_flag(self):
        with (_providers('CPUExecutionProvider', 'CoreMLExecutionProvider'),
              mock.patch.object(homr_runner.platform, 'machine', return_value='arm64'),
              mock.patch.object(homr_runner, '_get_available_memory_mb', return_value=6000)):
            self.assertEqual(homr_runner._backend_from_flags(False)['name'], 'cpu')
            # --gpu on means "use the accelerator that exists" -> Core ML on macOS
            self.assertEqual(homr_runner._backend_from_flags(True)['name'], 'coreml')

    def test_real_machine_never_raises(self):
        # Whatever this machine exposes, resolution must succeed and agree with ORT.
        bk = homr_runner._resolve_inference_backend('auto')
        self.assertIn(bk['name'], ('cpu', 'coreml', 'cuda'))
        if bk['name'] == 'coreml':
            self.assertIn('CoreMLExecutionProvider', homr_runner._available_providers())


class AppleInferenceRunTest(unittest.TestCase):
    def test_selection_and_model_reuse_are_scoped_to_each_job(self):
        from homr.segmentation import inference_segnet
        from homr.transformer import encoder_inference

        accelerator = mock.Mock()
        accelerator.model.get_providers.return_value = ['CoreMLExecutionProvider', 'CPUExecutionProvider']
        cpu_fallback = mock.Mock()
        cpu_fallback.model.get_providers.return_value = ['CPUExecutionProvider']
        constructor = mock.Mock(side_effect=[accelerator, accelerator, cpu_fallback])
        original_options = lambda path, compute_units: [('CoreMLExecutionProvider', {'MLComputeUnits': compute_units})]
        inference = mock.Mock()
        with (mock.patch.object(inference_segnet, 'Segnet', constructor),
              mock.patch.object(inference_segnet, 'inference', inference),
              mock.patch.object(inference_segnet, 'coreml_mlprogram_providers', original_options),
              mock.patch.object(encoder_inference, 'coreml_mlprogram_providers', original_options)):
            install_coreml_hooks()

            def process_page(expected_units, profile=False):
                options = inference_segnet.coreml_mlprogram_providers('segnet.onnx', 'CPUAndGPU')[0][1]
                self.assertEqual(options['MLComputeUnits'], expected_units)
                self.assertEqual(options.get('ProfileComputePlan'), '1' if profile else None)
                inference_segnet.inference('page', True, 8, 160, 320)
                inference_segnet.Segnet(True)

            gpu = AppleInferenceRun('CPUAndGPU', batch_size=4)
            gpu.process(process_page, 'CPUAndGPU')
            gpu.process(process_page, 'CPUAndGPU')
            self.assertEqual(constructor.call_count, 1)
            inference.assert_called_with('page', True, 4, 160, 320)

            ane = AppleInferenceRun('CPUAndNeuralEngine', profile=True, batch_size=1)
            ane.process(process_page, 'CPUAndNeuralEngine', True)
            inference.assert_called_with('page', True, 1, 160, 320)
            self.assertEqual(constructor.call_count, 2)
            with self.assertRaisesRegex(RuntimeError, 'did not activate'):
                AppleInferenceRun('CPUAndGPU').process(inference_segnet.Segnet, True)


if __name__ == '__main__':
    unittest.main()
