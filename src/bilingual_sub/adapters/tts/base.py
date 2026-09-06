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
    model_revision: str = ""


class TtsProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def synth(self, req: TtsRequest, *, control: JobControl | None = None) -> Path: ...


def select_tts(
    provider: str,
    *,
    endpoint: str = "",
    ref_audio: str = "",
    prompt_text: str = "",
    prompt_lang: str = "",
) -> TtsProvider:
    name = (provider or "none").lower()
    if name in {"openai", "azure"}:
        name = "gptsovits"
    if name == "qwen3":
        from bilingual_sub.adapters.tts.qwen import QwenTts

        return QwenTts(endpoint or None, ref_audio=ref_audio, prompt_text=prompt_text, prompt_lang=prompt_lang)
    if name == 'qwen3-native':
        from bilingual_sub.adapters.tts.qwen import QwenNativeTts

        return QwenNativeTts(endpoint or None)
    if name == "gptsovits":
        from bilingual_sub.adapters.tts.gptsovits import GptSovitsTts

        return GptSovitsTts(
            endpoint or None,
            ref_audio=ref_audio,
            prompt_text=prompt_text,
            prompt_lang=prompt_lang,
        )
    raise TtsUnavailable(f"未知配音引擎：{provider}")
