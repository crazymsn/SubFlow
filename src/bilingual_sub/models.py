from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class WordSpan:
    start: float
    end: float
    text: str
    score: float | None = None


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str
    words: tuple[WordSpan, ...] = ()


@dataclass
class Cue:
    start: float
    end: float
    zh: str
    en: str | None = None
    words: list[WordSpan] = field(default_factory=list)

    @property
    def source(self) -> str:
        return self.zh

    @source.setter
    def source(self, value: str) -> None:
        self.zh = value

    @property
    def target(self) -> str | None:
        return self.en

    @target.setter
    def target(self, value: str | None) -> None:
        self.en = value

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "zh": self.zh,
            "en": self.en,
            "source": self.zh,
            "target": self.en,
            "words": [
                {"start": w.start, "end": w.end, "text": w.text, "score": w.score} for w in self.words
            ],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Cue:
        src = str(d.get("source") or d.get("zh") or "")
        tgt = d.get("target") if "target" in d else d.get("en")
        words: list[WordSpan] = []
        for raw in d.get("words") or []:
            words.append(
                WordSpan(
                    start=float(raw["start"]),
                    end=float(raw["end"]),
                    text=str(raw.get("text") or ""),
                    score=float(raw["score"]) if raw.get("score") is not None else None,
                )
            )
        return cls(
            start=float(d["start"]),
            end=float(d["end"]),
            zh=src,
            en=None if tgt is None else str(tgt),
            words=words,
        )


@dataclass
class JobConfig:
    input_video: Path
    output_video: Path | None
    output_srt: Path
    work_dir: Path
    glossary_path: Path | None = None
    style_preset: str = "no-plate-large"
    subtitle_zh_color: str = "#FFFFFF"
    subtitle_en_color: str = "#F2F2F2"
    whisper_model: str = "medium"
    device: Literal["auto", "cuda", "cpu"] = "auto"
    burn: bool = True
    resume_from: str | None = None
    preview_minutes: float | None = None
    translate_model: str = "gpt-4o-mini"
    translate_batch_size: int = 30
    source_lang: str = "zh"
    target_lang: str = "zh"
    subtitle_mode: str = "bilingual"
    asr_backend: Literal["whisper", "whisperx"] = "whisper"
    refine_translate: bool = False
    source_url: str | None = None
    glossary_generate: bool = False
    enable_dub: bool = False
    tts_provider: Literal["none", "openai", "azure", "gptsovits"] = "none"
    tts_voice: str = ""
    tts_endpoint: str = ""
    ui_locale: str = "zh-Hans"


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
    reused: bool = False
    output_dub: Path | None = None
    translated: bool = False


STAGES = (
    "init",
    "ingest",
    "extract",
    "silence",
    "transcribe",
    "build_cues",
    "glossary",
    "translate",
    "fit_subs",
    "render",
    "burn",
    "dub",
    "done",
)
