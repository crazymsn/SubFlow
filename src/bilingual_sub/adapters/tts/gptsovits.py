from __future__ import annotations

import os
from pathlib import Path

import httpx

from bilingual_sub.adapters.tts.base import TtsRequest, TtsUnavailable
from bilingual_sub.core.control import JobControl


class GptSovitsTts:
    name = "gptsovits"

    def __init__(self, endpoint: str | None = None) -> None:
        self.endpoint = (endpoint or os.environ.get("SUBFLOW_GPTSOVITS_URL") or "http://127.0.0.1:9880").rstrip("/")

    def available(self) -> bool:
        try:
            resp = httpx.get(self.endpoint, timeout=2)
            return resp.status_code < 500
        except Exception:
            return False

    def synth(self, req: TtsRequest, *, control: JobControl | None = None) -> Path:
        if control:
            control.check()
        url = f"{self.endpoint}/tts"
        try:
            resp = httpx.post(
                url,
                json={"text": req.text, "text_lang": req.lang, "prompt_lang": req.lang},
                timeout=120,
            )
        except Exception as exc:
            raise TtsUnavailable(f"请先启动 GPT-SoVITS 服务（{self.endpoint}）：{exc}") from exc
        if resp.status_code >= 400:
            raise TtsUnavailable(f"GPT-SoVITS 失败：{resp.status_code} {resp.text[:200]}")
        req.dest.parent.mkdir(parents=True, exist_ok=True)
        req.dest.write_bytes(resp.content)
        return req.dest
