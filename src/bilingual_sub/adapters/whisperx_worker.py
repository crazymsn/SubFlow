"""Standalone WhisperX worker. Inspired by VideoLingo's word-level alignment path."""

from __future__ import annotations

import argparse
import gc
from pathlib import Path

if __package__:
    from .transcript_io import write_transcript
else:
    from transcript_io import write_transcript  # type: ignore[no-redef]


def resolve_device(requested: str) -> str:
    req = (requested or "auto").strip().lower()
    if req in {"cpu", "mps"}:
        if req == "mps":
            print("WhisperX/CTranslate2 does not support MPS; using CPU. Use Whisper for Apple GPU.", flush=True)
        return "cpu"
    try:
        import torch

        if torch.cuda.is_available() and torch.cuda.device_count() > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


def device_failure(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(value in message for value in (
        'out of memory', 'cuda error', 'cublas', 'cudnn', 'cudart',
        'not compiled with cuda', 'no kernel image', 'driver version is insufficient',
    ))


def release_accelerator(device: str) -> None:
    gc.collect()
    if device == 'cuda':
        import torch
        torch.cuda.empty_cache()


def transcribe_audio(whisperx, name, audio, device, language):
    """Reduce GPU batches on memory pressure before falling back to CPU."""
    for attempt_device in ([device, 'cpu'] if device == 'cuda' else ['cpu']):
        model = None
        try:
            model = whisperx.load_model(name, attempt_device,
                compute_type='float16' if attempt_device == 'cuda' else 'int8', language=language,
                asr_options={'condition_on_previous_text': False, 'no_speech_threshold': 0.6})
            print(f'MODEL_LOADED device={attempt_device}', flush=True)
            for batch in ([8, 4, 2, 1] if attempt_device == 'cuda' else [2, 1]):
                try:
                    result = model.transcribe(audio, language=language, batch_size=batch)
                    return result, attempt_device
                except RuntimeError as exc:
                    if 'out of memory' not in str(exc).lower() or batch == 1:
                        raise
                    print(f'WARN memory pressure at batch={batch}; retrying smaller batch', flush=True)
                    release_accelerator(attempt_device)
        except (RuntimeError, OSError) as exc:
            if attempt_device != 'cuda' or not device_failure(exc):
                raise
            print(f'WARN CUDA unavailable for this recognition ({exc}); retrying CPU', flush=True)
        finally:
            del model
            release_accelerator(attempt_device)
    raise RuntimeError('WhisperX did not produce a transcript')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default="small")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    import whisperx

    wav = Path(args.wav)
    out_json = Path(args.out)
    device = resolve_device(args.device)
    lang = None if args.language in {"", "auto"} else args.language
    print(f"START model={args.model} device={device} lang={lang}", flush=True)
    audio = whisperx.load_audio(str(wav))
    result, device = transcribe_audio(whisperx, args.model, audio, device, lang)
    detected = result.get("language") or lang or "zh"
    # Alignment uses a separate model. Release the recognizer first on 6 GB GPUs.
    try:
        align_model, metadata = whisperx.load_align_model(language_code=detected, device=device)
        result = whisperx.align(
            result["segments"],
            align_model,
            metadata,
            audio,
            device,
            return_char_alignments=False,
        )
        print("ALIGNED", flush=True)
    except Exception as exc:
        print(f"ALIGN_FAILED {exc}", flush=True)

    segments = []
    dropped = 0
    for seg in result.get("segments") or []:
        seg_lang = str(seg.get("language") or detected)
        if lang and seg_lang not in {detected, lang}:
            dropped += 1
            continue
        segments.append({"start": seg.get("start"), "end": seg.get("end"),
                         "text": seg.get("text"), "words": seg.get("words") or []})
    if dropped:
        print(f"KEEP_PRIMARY_LANG {detected} dropped={dropped}", flush=True)
    payload = {
        "backend": "whisperx",
        "language": detected,
        "detected_language": detected,
        "segments": segments,
    }
    write_transcript(out_json, payload)
    print(f"OK segments={len(segments)}", flush=True)


if __name__ == "__main__":
    main()
