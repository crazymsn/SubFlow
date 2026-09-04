from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bilingual_sub.core.control import JobControl


class TtsUnavailable(RuntimeError):
    pass


@dataclass
class TtsRequest:
    text: str
    lang: str
    voice: str
    dest: Path


class TtsProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def synth(self, req: TtsRequest, *, control: JobControl | None = None) -> Path: ...


def select_tts(provider: str) -> TtsProvider:
    name = (provider or "none").lower()
    if name == "openai":
        from bilingual_sub.adapters.tts.openai_tts import OpenAiTts

        return OpenAiTts()
    if name == "azure":
        from bilingual_sub.adapters.tts.azure_tts import AzureTts

        return AzureTts()
    if name == "gptsovits":
        from bilingual_sub.adapters.tts.gptsovits import GptSovitsTts

        return GptSovitsTts()
    raise TtsUnavailable(f"未知配音引擎：{provider}")
