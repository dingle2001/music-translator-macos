"""Select Apple inference settings for one Homr recognition job."""

from contextvars import ContextVar
from threading import Lock

PROVIDER = 'CoreMLExecutionProvider'
COMPUTE_UNITS = {'CPUAndGPU', 'CPUAndNeuralEngine', 'ALL', 'CPUOnly'}
COREML_MODES = {'coreml-gpu': 'CPUAndGPU', 'coreml-ane': 'CPUAndNeuralEngine'}
BACKEND_CHOICES = ('auto', 'cpu', 'coreml', *COREML_MODES, 'cuda')

_active_run = ContextVar('homr_coreml_run', default=None)
_hooks_lock = Lock()


class AppleInferenceRun:
    def __init__(self, compute_units=None, profile=False, batch_size=None):
        self.compute_units = compute_units
        self.profile = profile
        self.batch_size = batch_size
        self.segnet = None

    def process(self, process_image, *args):
        # This runs inside the inference worker. Other jobs and CPU retries
        # have their own context and never share the mutable I/O bindings.
        token = _active_run.set(self)
        try:
            process_image(*args)
        finally:
            _active_run.reset(token)


def install_coreml_hooks():
    """Keep Homr's session construction and model cache, selecting units per job."""
    from homr.segmentation import inference_segnet
    from homr.transformer import encoder_inference

    with _hooks_lock:
        original_options = getattr(inference_segnet, 'coreml_mlprogram_providers', None)
        if original_options is None:
            return
        if getattr(original_options, '_music_translator_coreml', False):
            return
        original_segnet = inference_segnet.Segnet
        original_inference = inference_segnet.inference

        def session_providers(model_path, compute_units='ALL'):
            providers = original_options(model_path, compute_units=compute_units)
            run = _active_run.get()
            if run is not None and run.compute_units is not None:
                for name, options in providers:
                    if name == PROVIDER:
                        options['MLComputeUnits'] = run.compute_units
                        if run.profile:
                            options['ProfileComputePlan'] = '1'
            return providers

        def segnet(use_gpu_inference):
            run = _active_run.get()
            if run is None or run.compute_units is None or not use_gpu_inference:
                return original_segnet(use_gpu_inference)
            if run.segnet is None:
                model = original_segnet(use_gpu_inference)
                if PROVIDER not in model.model.get_providers():
                    raise RuntimeError('Core ML SegNet session did not activate its execution provider')
                run.segnet = model
            return run.segnet

        def inference(image_org, use_gpu_inference, batch_size, step_size, win_size):
            # Homr 0.7 does not expose the batch size in ProcessingConfig.
            run = _active_run.get()
            if run is not None and run.batch_size is not None:
                batch_size = min(batch_size, run.batch_size)
            return original_inference(image_org, use_gpu_inference, batch_size, step_size, win_size)

        session_providers._music_translator_coreml = True
        inference_segnet.coreml_mlprogram_providers = session_providers
        encoder_inference.coreml_mlprogram_providers = session_providers
        inference_segnet.Segnet = segnet
        inference_segnet.inference = inference
