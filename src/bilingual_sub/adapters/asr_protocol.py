from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from bilingual_sub.core.control import JobControl
from bilingual_sub.models import Segment


class AsrResult:
    def __init__(
        self,
        language: str,
        segments: list[Segment],
        detected_language: str | None = None,
        backend: str = "whisper",
    ) -> None:
        self.language = language
        self.detected_language = detected_language
        self.segments = segments
        self.backend = backend


class AsrBackend(Protocol):
    name: str

    def available(self) -> bool: ...

    def transcribe(
        self,
        wav: Path,
        *,
        model_name: str,
        language: str,
        device: str,
        out_json: Path,
        on_progress: Callable[[str, float], None] | None = None,
        control: JobControl | None = None,
    ) -> AsrResult: ...
