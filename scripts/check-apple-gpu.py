"""Probe the installed runtimes; --require-gpu rejects a GPU-less build VM."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def worker(kind: str) -> dict:
    import torch

    built = torch.backends.mps.is_built()
    available = torch.backends.mps.is_available()
    result = {"kind": kind, "torch": torch.__version__, "mps_built": built,
              "mps_available": available, "gpu_checks": []}
    if sys.platform == "darwin" and not built:
        raise RuntimeError("The installed PyTorch wheel lacks MPS support")
    if not available:
        return result
    a = torch.ones((16, 16), device="mps")
    assert torch.allclose((a @ a).cpu(), torch.full((16, 16), 16.0))
    checks = ["metal_matmul"]
    if kind == "asr":
        from whisper.model import ModelDimensions, Whisper

        from bilingual_sub.adapters.torch_device import load_whisper_on_device

        model = Whisper(ModelDimensions(n_mels=4, n_audio_ctx=8, n_audio_state=8,
            n_audio_head=2, n_audio_layer=1, n_vocab=32, n_text_ctx=8,
            n_text_state=8, n_text_head=2, n_text_layer=1))
        shim = SimpleNamespace(load_model=lambda *a, **k: model)
        model = load_whisper_on_device(shim, "synthetic", "mps")
        with torch.no_grad():
            logits = model(torch.zeros((1, 4, 16), device="mps"),
                           torch.tensor([[1, 2]], device="mps"))
        assert str(logits.device).startswith("mps") and torch.isfinite(logits).all()
        assert model.alignment_heads.is_sparse and model.alignment_heads.device.type == "cpu"
        checks.append("whisper_encoder_decoder_and_sparse_buffer")
    else:
        sys.path.insert(0, str(ROOT / "third_party" / "GPT-SoVITS" / "GPT_SoVITS"))
        from module.mel_processing import spectrogram_torch

        spec = spectrogram_torch(torch.zeros((1, 4096), device="mps"), 512, 32000, 128, 512)
        assert spec.device.type == "mps" and torch.isfinite(spec).all()
        checks.append("sovits_spectrogram_cpu_gpu_transfer")
    torch.mps.synchronize()
    result["gpu_checks"] = checks
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=["asr", "gptsovits"])
    parser.add_argument("--report", type=Path, default=Path("apple-gpu-report.json"))
    parser.add_argument("--require-gpu", action="store_true")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.worker)))
        return
    from bilingual_sub.adapters.runtime_bootstrap import ensure_python_env, inference_env

    results = []
    for kind in ("asr", "gptsovits"):
        python = ensure_python_env(kind)
        result = subprocess.run([str(python), str(Path(__file__).resolve()), "--worker", kind],
            env=inference_env(), capture_output=True, text=True, encoding="utf-8", timeout=180)
        if result.returncode:
            raise RuntimeError(result.stderr[-5000:] or result.stdout[-5000:])
        results.append(json.loads(result.stdout.strip().splitlines()[-1]))
    report = {"runtimes": results, "gpu_verified": all(r["gpu_checks"] for r in results)}
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if args.require_gpu and not report["gpu_verified"]:
        raise SystemExit("No usable Apple GPU; GPU acceptance was not performed")


if __name__ == "__main__":
    main()
