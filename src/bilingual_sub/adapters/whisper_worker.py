"""Standalone Whisper worker for the packaged client (external Python + Torch)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

if __package__:
    from .torch_device import (
        load_whisper_on_device,
        mps_available,
        select_device,
        transcribe_with_fallback,
    )
else:
    from torch_device import (  # type: ignore[no-redef]
        load_whisper_on_device,
        mps_available,
        select_device,
        transcribe_with_fallback,
    )


def resolve_device(requested: str) -> str:
    req = (requested or "auto").strip().lower()
    if req == "cpu":
        return "cpu"
    try:
        import torch

        cuda_ok = bool(torch.cuda.is_available() and torch.cuda.device_count() > 0)
    except Exception:
        cuda_ok = False
    if req == "cuda" and not cuda_ok:
        print("WARN CUDA unavailable; using CPU", flush=True)
        return "cpu"
    return select_device(req, cuda=cuda_ok, mps=mps_available())


def load_model(name: str, device: str):
    import whisper

    try:
        return load_whisper_on_device(whisper, name, device), device
    except Exception as exc:
        if device in {"cuda", "mps"}:
            print(f"WARN {device} load failed ({exc}); using CPU", flush=True)
            return whisper.load_model(name, device="cpu"), "cpu"
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default="small")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    wav = Path(args.wav)
    out_json = Path(args.out)
    dev = resolve_device(args.device)
    print(f"START model={args.model} device={dev} wav={wav}", flush=True)
    model, dev = load_model(args.model, dev)
    print(f"MODEL_LOADED device={dev}", flush=True)
    lang = None if (args.language or "").strip().lower() in {"", "auto"} else args.language
    result, dev = transcribe_with_fallback(
        model, dev, str(wav),
        language=lang,
        word_timestamps=False,
        verbose=False,
        condition_on_previous_text=True,
        no_speech_threshold=0.4,
    )
    clean = {"language": result.get("language"), "segments": []}
    for seg in result.get("segments") or []:
        clean["segments"].append(
            {
                "start": float(seg.get("start") or 0),
                "end": float(seg.get("end") or 0),
                "text": (seg.get("text") or "").strip(),
                "words": seg.get("words") or [],
            }
        )
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK segments={len(clean['segments'])} device={dev}", flush=True)


if __name__ == "__main__":
    main()
