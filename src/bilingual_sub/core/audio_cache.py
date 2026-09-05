"""Verified PCM cache entries, bound to the request that produced them."""
from __future__ import annotations

import json
import wave
from collections.abc import Callable
from pathlib import Path

from bilingual_sub.core.control import JobControl
from bilingual_sub.core.file_io import file_digest, staged_path
from bilingual_sub.core.persistence import write_json


def pcm_duration(path: Path, control: JobControl | None = None) -> float:
    """Read all declared frames in bounded blocks; reject empty/truncated WAVs."""
    try:
        with wave.open(str(path), "rb") as wav:
            remaining = wav.getnframes()
            rate, frame_bytes = wav.getframerate(), wav.getnchannels() * wav.getsampwidth()
            if remaining <= 0 or rate <= 0 or frame_bytes <= 0:
                raise ValueError("配音音频为空或格式无效")
            seconds = remaining / rate
            while remaining:
                if control:
                    control.wait_if_paused()
                frames = min(remaining, 16384)
                if len(wav.readframes(frames)) != frames * frame_bytes:
                    raise ValueError("配音 WAV 内容不完整")
                remaining -= frames
            return seconds
    except (wave.Error, EOFError) as exc:
        raise ValueError("配音文件不是有效 PCM WAV") from exc


def cache_digest(path: Path, key: str, control: JobControl | None = None) -> str | None:
    try:
        record = json.loads(path.with_suffix(path.suffix + ".json").read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("schema") != 1 or record.get("key") != key:
            return None
        digest = file_digest(path, checkpoint=control.wait_if_paused if control else None)
        return digest if digest == record.get("sha256") else None
    except (OSError, ValueError):
        return None


def produce_audio(path: Path, key: str, produce: Callable[[Path], object],
                  control: JobControl | None = None) -> str:
    """Validate before replacement; a mismatched manifest forces regeneration."""
    with staged_path(path, suffix=".wav") as pending:
        produce(pending)
        pcm_duration(pending, control)
        digest = file_digest(pending, checkpoint=control.wait_if_paused if control else None)
        if control:
            control.wait_if_paused()
        pending.replace(path)
        write_json(path.with_suffix(path.suffix + ".json"), {"schema": 1, "key": key, "sha256": digest})
    return digest
