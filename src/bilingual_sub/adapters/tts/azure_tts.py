from __future__ import annotations

import os
from pathlib import Path

from bilingual_sub.adapters.tts.base import TtsRequest, TtsUnavailable
from bilingual_sub.core.control import JobControl
from bilingual_sub.core.langs import AZURE_LOCALE


class AzureTts:
    name = "azure"

    def available(self) -> bool:
        return bool(os.environ.get("SUBFLOW_AZURE_SPEECH_KEY") and os.environ.get("SUBFLOW_AZURE_SPEECH_REGION"))

    def synth(self, req: TtsRequest, *, control: JobControl | None = None) -> Path:
        if control:
            control.check()
        key = os.environ.get("SUBFLOW_AZURE_SPEECH_KEY")
        region = os.environ.get("SUBFLOW_AZURE_SPEECH_REGION")
        if not key or not region:
            raise TtsUnavailable("未配置 SUBFLOW_AZURE_SPEECH_KEY / SUBFLOW_AZURE_SPEECH_REGION")
        import httpx

        locale = AZURE_LOCALE.get(req.lang, "en-US")
        voice = req.voice or "en-US-JennyNeural"
        ssml = (
            f"<speak version='1.0' xml:lang='{locale}'>"
            f"<voice name='{voice}'>{req.text}</voice></speak>"
        )
        url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-16khz-32kbitrate-mono-mp3",
        }
        resp = httpx.post(url, content=ssml.encode("utf-8"), headers=headers, timeout=60)
        if resp.status_code >= 400:
            raise TtsUnavailable(f"Azure TTS 失败：{resp.status_code}")
        req.dest.parent.mkdir(parents=True, exist_ok=True)
        req.dest.write_bytes(resp.content)
        return req.dest
