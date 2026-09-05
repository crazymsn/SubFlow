from __future__ import annotations

import logging
from pathlib import Path

from bilingual_sub.adapters.meding import MEDING_BASE_URL
from bilingual_sub.adapters.tts.base import TtsRequest, TtsUnavailable
from bilingual_sub.core.control import JobControl
from bilingual_sub.secrets.store import get_api_key

logger = logging.getLogger(__name__)


class OpenAiTts:
    name = "openai"

    def available(self) -> bool:
        return bool(get_api_key())

    def synth(self, req: TtsRequest, *, control: JobControl | None = None) -> Path:
        if control:
            control.check()
        key = get_api_key()
        if not key:
            raise TtsUnavailable("请先保存 API 令牌")
        from openai import OpenAI

        client = OpenAI(api_key=key, base_url=f"{MEDING_BASE_URL}/v1")
        voice = req.voice or "alloy"
        fmt = "wav" if req.dest.suffix.lower() in {".wav", ".wave"} else "mp3"
        try:
            try:
                resp = client.audio.speech.create(
                    model="tts-1",
                    voice=voice,
                    input=req.text,
                    response_format=fmt,
                )
            except TypeError:
                resp = client.audio.speech.create(model="tts-1", voice=voice, input=req.text)
        except Exception as exc:
            detail = str(exc)
            if "model_not_found" in detail or "No available channel" in detail:
                raise TtsUnavailable("当前令牌未开通语音模型（tts-1），无法试听或配音") from exc
            raise TtsUnavailable(f"令牌通道未开放 TTS：{exc}") from exc
        req.dest.parent.mkdir(parents=True, exist_ok=True)
        req.dest.write_bytes(resp.read() if hasattr(resp, "read") else bytes(resp))
        return req.dest
