from __future__ import annotations

import math
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
    spoken: str | None = None
    language_texts: dict[str, str] = field(default_factory=dict)

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
            "spoken": self.spoken,
            "language_texts": dict(self.language_texts),
            "source": self.zh,
            "target": self.en,
            "words": [
                {"start": w.start, "end": w.end, "text": w.text, "score": w.score} for w in self.words
            ],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Cue:
        if not isinstance(d, dict):
            raise ValueError("字幕条目必须是对象")
        def text(value, name):
            if value is not None and not isinstance(value, str):
                raise ValueError(f"字幕 {name} 必须是文本")
            return value
        def time(value):
            try:
                result = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("字幕时间必须是有限非负数") from exc
            if isinstance(value, bool) or not math.isfinite(result) or result < 0:
                raise ValueError("字幕时间必须是有限非负数")
            return result
        src = text(d.get("source"), "source") or text(d.get("zh"), "zh") or ""
        tgt = d.get("target") if "target" in d else d.get("en")
        tgt = text(tgt, "target")
        spoken = text(d.get("spoken"), "spoken")
        language_texts = d.get("language_texts", {})
        if not isinstance(language_texts, dict) or any(
            not isinstance(lang, str) or not lang or not isinstance(value, str)
            for lang, value in language_texts.items()
        ):
            raise ValueError("字幕 language_texts 必须是语言到文本的映射")
        start, end = time(d.get("start")), time(d.get("end"))
        if end <= start:
            raise ValueError("字幕结束时间必须大于开始时间")
        words: list[WordSpan] = []
        raw_words = d.get("words") or []
        if not isinstance(raw_words, list):
            raise ValueError("字幕 words 必须是列表")
        for raw in raw_words:
            if not isinstance(raw, dict):
                raise ValueError("字幕词条必须是对象")
            a, b = time(raw.get("start")), time(raw.get("end"))
            if b < a:
                raise ValueError("字幕词结束时间不能早于开始时间")
            words.append(
                WordSpan(
                    start=a,
                    end=b,
                    text=text(raw.get("text"), "word") or "",
                    score=time(raw["score"]) if raw.get("score") is not None else None,
                )
            )
        return cls(
            start=start,
            end=end,
            zh=src,
            en=tgt,
            words=words,
            spoken=spoken,
            language_texts=dict(language_texts),
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
    device: Literal["auto", "cuda", "mps", "cpu"] = "auto"
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
    tts_ref_audio: str = ""
    tts_prompt_text: str = ""
    tts_prompt_lang: str = ""
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
