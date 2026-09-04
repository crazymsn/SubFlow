from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass
class Cue:
    start: float
    end: float
    zh: str
    en: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "zh": self.zh, "en": self.en}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Cue:
        return cls(
            start=float(d["start"]),
            end=float(d["end"]),
            zh=str(d["zh"]),
            en=d.get("en"),
        )


@dataclass
class JobConfig:
    input_video: Path
    output_video: Path | None
    output_srt: Path
    work_dir: Path
    glossary_path: Path | None = None
    style_preset: str = "no-plate-large"
    whisper_model: str = "medium"
    device: Literal["auto", "cuda", "cpu"] = "auto"
    burn: bool = True
    resume_from: str | None = None
    preview_minutes: float | None = None
    translate_model: str = "gpt-4o-mini"
    translate_batch_size: int = 30


@dataclass
class JobResult:
    job_id: str
    output_mp4: Path | None
    output_srt: Path
    output_ass: Path
    cue_count: int
    missing_en: list[str]
    duration_sec: float
    report_path: Path
    elapsed_sec: float = 0.0
    translate_cache_hits: int = 0
    translate_api_calls: int = 0
    stages: dict[str, float] = field(default_factory=dict)


STAGES = (
    "init",
    "extract",
    "silence",
    "transcribe",
    "build_cues",
    "translate",
    "render",
    "burn",
    "done",
)
