"""Qwen3-TTS uses the same transactional WAV transport as GPT-SoVITS."""
from __future__ import annotations

from dataclasses import dataclass

from bilingual_sub.adapters.tts.base import TtsUnavailable
from bilingual_sub.adapters.tts.gptsovits import GptSovitsTts
from bilingual_sub.adapters.tts.routing import QWEN_LANGS, family, provider_endpoint


class QwenTts(GptSovitsTts):
    name = "qwen3"
    display_name = "Qwen3-TTS"

    def __init__(self, endpoint=None, **kwargs):
        super().__init__(endpoint or provider_endpoint(self.name), **kwargs)

    def available(self) -> bool:
        from bilingual_sub.adapters.tts.qwen_runtime import probe_endpoint

        return probe_endpoint(self.endpoint, native=self.name == 'qwen3-native')

    def language(self, lang: str) -> str:
        code = family(lang)
        if code in {"", "auto"}:
            return "Auto"
        if code not in QWEN_LANGS:
            raise TtsUnavailable(f"Qwen3-TTS 不支持语种「{lang}」")
        return QWEN_LANGS[code]


def native_speaker(lang: str) -> str:
    if family(lang) in {'es', 'fr', 'de', 'ru'}:
        return f'SubFlow_{family(lang)}_female'
    return {'zh': 'Serena', 'ja': 'Ono_Anna', 'ko': 'Sohee'}.get(family(lang), 'Aiden')


@dataclass(frozen=True)
class VoicePreset:
    name: str
    gender: str
    language: str
    origin: str
    designed: bool = False


# Actual CustomVoice speaker IDs and profiles from the pinned model's card.
# All nine can be used across supported languages; origin is not a language lock.
STANDARD_VOICES = (
    VoicePreset('Aiden', 'male', 'en', 'en'),
    VoicePreset('Ryan', 'male', 'en', 'en'),
    VoicePreset('Serena', 'female', 'zh', 'zh'),
    VoicePreset('Vivian', 'female', 'zh', 'zh'),
    VoicePreset('Uncle_Fu', 'male', 'zh', 'zh'),
    VoicePreset('Dylan', 'male', 'zh', 'beijing'),
    VoicePreset('Eric', 'male', 'zh', 'sichuan'),
    VoicePreset('Ono_Anna', 'female', 'ja', 'ja'),
    VoicePreset('Sohee', 'female', 'ko', 'ko'),
)

DESIGNED_VOICES = tuple(
    VoicePreset(f'SubFlow_{language}_{gender}', gender, language, language, True)
    for language in ('zh', 'en', 'ja', 'es', 'fr', 'de', 'ru')
    for gender in ('female', 'male')
)


def standard_voices(lang: str) -> tuple[VoicePreset, ...]:
    return tuple(sorted(STANDARD_VOICES + DESIGNED_VOICES,
                        key=lambda voice: voice.language != family(lang)))


class QwenNativeTts(QwenTts):
    name = 'qwen3-native'
    display_name = 'Qwen3-TTS 标准音色'
    requires_reference = False

    def __init__(self, endpoint=None, **kwargs):
        super().__init__(endpoint, **kwargs)
        self.ref_audio = self.prompt_text = self.prompt_lang = ''
