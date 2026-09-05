from __future__ import annotations

from pathlib import Path

from bilingual_sub.adapters.tts.base import TtsRequest, TtsUnavailable
from bilingual_sub.core.control import JobControl


class OpenAiTts:
    """Deprecated stub. Product dubbing uses built-in GPT-SoVITS only."""

    name = "openai"

    def available(self) -> bool:
        return False

    def synth(self, req: TtsRequest, *, control: JobControl | None = None) -> Path:
        raise TtsUnavailable(
            "配音已改为内置 GPT-SoVITS，不再使用 OpenAI tts-1。"
            "请使用最新客户端，并确认旁路目录存在 GPT-SoVITS。"
        )
