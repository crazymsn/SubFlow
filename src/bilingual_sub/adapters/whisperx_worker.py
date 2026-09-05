"""Standalone WhisperX worker. Inspired by VideoLingo's word-level alignment path."""

from __future__ import annotations

import argparse
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
    model = whisperx.load_model(args.model, device, compute_type="float16" if device == "cuda" else "int8")
    audio = whisperx.load_audio(str(wav))
    try:
        result = model.transcribe(
            audio,
            language=lang,
            batch_size=8,
            asr_options={
                "condition_on_previous_text": False,
                "no_speech_threshold": 0.6,
            },
        )
    except TypeError:
        result = model.transcribe(audio, language=lang, batch_size=8)
    detected = result.get("language") or lang or "zh"
    print("MODEL_LOADED", flush=True)
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
