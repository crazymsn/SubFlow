"""Device helpers shared by the app and standalone inference workers."""
from __future__ import annotations

import gc
import logging
import os

logger = logging.getLogger(__name__)
# Must be set before torch is imported, including in standalone workers.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def mps_available() -> bool:
    try:
        import torch

        backend = getattr(torch.backends, "mps", None)
        return bool(backend and backend.is_built() and backend.is_available())
    except (ImportError, RuntimeError, OSError, AttributeError):
        return False


def select_device(requested: str, *, cuda: bool, mps: bool) -> str:
    req = (requested or "auto").strip().lower()
    if req == "auto" and os.environ.get("SUBFLOW_TORCH_BACKEND", "").lower() == "cpu":
        return "cpu"
    if req in {"auto", "cuda"} and cuda:
        return "cuda"
    if req in {"auto", "mps"} and mps:
        return "mps"
    return "cpu"


def load_whisper_on_device(whisper, name: str, device: str):
    if device != "mps":
        return whisper.load_model(name, device=device)
    # Whisper's sparse alignment buffer cannot be transferred to MPS. It is
    # used only for word alignment, which SubFlow's standard worker disables.
    model = whisper.load_model(name, device="cpu")
    alignment = model.alignment_heads
    model.alignment_heads = alignment.to_dense()
    try:
        model.to("mps")
    finally:
        model.alignment_heads = alignment
    return model


def transcribe_with_fallback(model, device: str, audio: str, **options):
    try:
        return model.transcribe(audio, fp16=device == "cuda", **options), device
    except (RuntimeError, NotImplementedError) as exc:
        if device not in {"mps", "cuda"}:
            raise
        logger.warning("Whisper %s inference failed (%s); retrying on CPU", device, exc)
        model.to("cpu")
        gc.collect()
        import torch

        if device == "cuda":
            torch.cuda.empty_cache()
        else:
            torch.mps.empty_cache()
        return model.transcribe(audio, fp16=False, **options), "cpu"
