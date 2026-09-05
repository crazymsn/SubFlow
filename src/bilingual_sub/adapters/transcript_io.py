"""Validated, atomic ASR interchange; also imported by standalone workers."""
from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Callable
from pathlib import Path


def timestamp(value, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid ASR {label}: expected a finite timestamp") from exc
    if isinstance(value, bool) or not math.isfinite(number) or number < 0:
        raise ValueError(f"Invalid ASR {label}: expected a non-negative finite timestamp")
    return number


def normalize_transcript(data) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("segments"), list):
        raise ValueError("Invalid ASR transcript: expected an object with a segments list")
    clean = {key: data[key] for key in ("language", "detected_language", "backend") if key in data}
    for key, value in clean.items():
        if value is not None and not isinstance(value, str):
            raise ValueError(f"Invalid ASR {key}: expected text")
    segments = []
    previous = -1.0
    for index, seg in enumerate(data["segments"]):
        if not isinstance(seg, dict) or not isinstance(seg.get("text"), str):
            raise ValueError(f"Invalid ASR segment {index}: expected text")
        text = seg["text"].strip()
        if not text:
            continue
        start = timestamp(seg.get("start"), f"segment {index} start")
        end = timestamp(seg.get("end"), f"segment {index} end")
        if end <= start or start < previous:
            raise ValueError(f"Invalid ASR segment {index}: reversed or unordered interval")
        previous = start
        words = []
        raw_words = seg.get("words") or []
        try:
            if not isinstance(raw_words, (list, tuple)):
                raise ValueError("invalid alignment list")
            word_start = start
            word_end = start
            for raw in raw_words:
                if not isinstance(raw, dict):
                    raise ValueError("invalid alignment word")
                word = raw.get("word", raw.get("text"))
                if not isinstance(word, str) or not word.strip():
                    raise ValueError("invalid alignment text")
                a, b = timestamp(raw.get("start"), "word start"), timestamp(raw.get("end"), "word end")
                if a < word_start or b <= a or b > end or b < word_end:
                    raise ValueError("invalid alignment interval")
                word_start = a
                word_end = b
                score = raw.get("score")
                if score is not None:
                    score = timestamp(score, "word score")
                words.append({"start": a, "end": b, "text": word.strip(), "score": score})
        except (TypeError, ValueError, OverflowError):
            # Alignment is optional. Never discard the recognized sentence
            # or manufacture timestamps for a word that was not aligned.
            words = []
        segments.append({"start": start, "end": end, "text": text, "words": words})
    clean["segments"] = segments
    return clean


def read_transcript(path: Path) -> dict:
    return normalize_transcript(json.loads(path.read_text(encoding="utf-8")))


def write_transcript(path: Path, data, *, before_commit: Callable[[], None] | None = None) -> dict:
    clean = normalize_transcript(data)
    encoded = json.dumps(clean, ensure_ascii=False, indent=2, allow_nan=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".transcript-", suffix=".json", delete=False) as stream:
            pending = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if before_commit:
            before_commit()
        pending.replace(path)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
    return clean
