from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from bilingual_sub.models import Segment

logger = logging.getLogger(__name__)


def resolve_device(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def transcribe(
    wav: Path,
    *,
    model_name: str = "medium",
    language: str = "zh",
    device: str = "auto",
    out_json: Path | None = None,
) -> list[Segment]:
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError(
            "openai-whisper not installed. Run: pip install bilingual-sub[cuda]"
        ) from exc

    dev = resolve_device(device)
    logger.info("loading whisper model=%s device=%s", model_name, dev)
    model = whisper.load_model(model_name, device=dev)
    result: dict[str, Any] = model.transcribe(
        str(wav),
        language=language,
        fp16=dev == "cuda",
        word_timestamps=True,
        verbose=False,
        condition_on_previous_text=True,
        no_speech_threshold=0.4,
    )

    segments: list[Segment] = []
    clean: dict[str, Any] = {"language": result.get("language"), "segments": []}
    for seg in result.get("segments") or []:
        text = (seg.get("text") or "").strip()
        start = float(seg.get("start") or 0)
        end = float(seg.get("end") or 0)
        segments.append(Segment(start=start, end=end, text=text))
        clean["segments"].append(
            {
                "start": start,
                "end": end,
                "text": text,
                "words": seg.get("words") or [],
            }
        )

    if out_json:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("transcribed %d segments", len(segments))
    return segments


def load_transcript(path: Path) -> list[Segment]:
    data = json.loads(path.read_text(encoding="utf-8"))
    segs = []
    for seg in data.get("segments") or []:
        segs.append(
            Segment(
                start=float(seg["start"]),
                end=float(seg["end"]),
                text=str(seg.get("text") or "").strip(),
            )
        )
    return segs


def probe_whisper(model_name: str = "tiny", device: str = "auto") -> bool:
    try:
        import whisper

        dev = resolve_device(device)
        whisper.load_model(model_name, device=dev)
        return True
    except Exception as exc:
        logger.warning("whisper probe failed: %s", exc)
        return False
