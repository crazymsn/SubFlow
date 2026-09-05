from __future__ import annotations

import asyncio
import hashlib
import io
import json
import math
import os
import threading
import wave
from pathlib import Path

import httpx

from bilingual_sub.adapters.tts.base import TtsRequest, TtsUnavailable
from bilingual_sub.core.control import JobControl
from bilingual_sub.core.file_io import staged_path
from bilingual_sub.core.output_guard import validate_outputs

DEFAULT_ENDPOINT = "http://127.0.0.1:9880"
_synthesis_lock = threading.Lock()

# Official api_v2.py languages (v2/v4): zh / en / ja / ko / yue / auto and all_* variants.
_SOVITS_LANG = {
    "zh": "zh",
    "zh-hans": "zh",
    "zh-hant": "zh",
    "zh-cn": "zh",
    "zh-tw": "zh",
    "yue": "yue",
    "en": "en",
    "ja": "ja",
    "jp": "ja",
    "ko": "ko",
    "auto": "auto",
}
# UI subtitle targets that SoVITS cannot dub — refuse instead of silently using auto.
_UNSUPPORTED_DUB_LANGS = frozenset({"es", "ru", "fr", "de"})


def default_endpoint() -> str:
    return (os.environ.get("SUBFLOW_GPTSOVITS_URL", "").strip() or DEFAULT_ENDPOINT).rstrip("/")


def to_sovits_lang(lang: str) -> str:
    raw = (lang or "zh").strip()
    if not raw:
        return "zh"
    key = raw.replace("_", "-").lower()
    if key in {"all-zh", "all-ja", "all-ko", "all-yue", "auto-yue"}:
        return key.replace("-", "_")
    if key in _SOVITS_LANG:
        return _SOVITS_LANG[key]
    fam = key.split("-", 1)[0]
    if fam in _SOVITS_LANG:
        return _SOVITS_LANG[fam]
    if fam in _UNSUPPORTED_DUB_LANGS:
        raise TtsUnavailable(
            f"GPT-SoVITS 不支持配音语种「{lang}」。请改用中文、英文、日文、韩文或粤语。"
        )
    return "auto"


def _error_detail(resp: httpx.Response) -> str:
    text = (resp.text or "")[:400]
    ctype = resp.headers.get("content-type", "")
    if "json" in ctype or text.lstrip().startswith("{"):
        try:
            data = resp.json()
        except Exception:
            return text or f"HTTP {resp.status_code}"
        if isinstance(data, dict):
            msg = data.get("message")
            exc = data.get("Exception") or data.get("detail")
            if exc and (not msg or str(msg) in {"tts failed", "set refer audio failed", "change gpt weight failed", "change sovits weight failed"}):
                return f"{msg}: {exc}" if msg else str(exc)
            return str(msg or exc or text)
    return text or f"HTTP {resp.status_code}"


def _is_audio(content: bytes) -> bool:
    try:
        with wave.open(io.BytesIO(content), "rb") as wav:
            frames = wav.getnframes()
            expected = frames * wav.getnchannels() * wav.getsampwidth()
            return frames > 0 and len(wav.readframes(frames)) == expected
    except (wave.Error, EOFError):
        return False


async def _post_audio(url: str, payload: dict, control: JobControl | None) -> httpx.Response:
    try:
        timeout = float(os.environ.get("SUBFLOW_GPTSOVITS_TIMEOUT", "1800"))
    except ValueError as exc:
        raise TtsUnavailable("SUBFLOW_GPTSOVITS_TIMEOUT 必须是正数秒数") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise TtsUnavailable("SUBFLOW_GPTSOVITS_TIMEOUT 必须是正数秒数")
    async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(timeout, connect=5)) as client:
        task = asyncio.create_task(client.post(url, json=payload))
        try:
            while not task.done():
                if control:
                    control.check()
                await asyncio.wait({task}, timeout=0.1)
            return task.result()
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


class GptSovitsTts:
    name = "gptsovits"

    def __init__(
        self,
        endpoint: str | None = None,
        *,
        ref_audio: str | Path | None = None,
        prompt_text: str = "",
        prompt_lang: str = "",
    ) -> None:
        self.endpoint = (endpoint or default_endpoint()).rstrip("/")
        self.ref_audio = str(ref_audio or os.environ.get("SUBFLOW_GPTSOVITS_REF") or "").strip()
        self.prompt_text = str(prompt_text or os.environ.get("SUBFLOW_GPTSOVITS_PROMPT") or "")
        self.prompt_lang = str(prompt_lang or os.environ.get("SUBFLOW_GPTSOVITS_PROMPT_LANG") or "").strip()

    def available(self) -> bool:
        from bilingual_sub.adapters.tts.gptsovits_runtime import probe_endpoint

        return probe_endpoint(self.endpoint)

    def _ref_path(self) -> Path:
        if not self.ref_audio:
            raise TtsUnavailable("请先选择 GPT-SoVITS 参考音频（3–10 秒清晰人声）")
        path = Path(self.ref_audio).expanduser()
        if not path.is_file():
            raise TtsUnavailable(f"参考音频不存在：{path}")
        return path.resolve()

    def synth(self, req: TtsRequest, *, control: JobControl | None = None) -> Path:
        if control:
            control.check()
        ref = self._ref_path()
        validate_outputs({"配音": req.dest}, [ref])
        if not req.text.strip():
            raise TtsUnavailable("配音文本不能为空")
        text_lang = to_sovits_lang(req.lang)
        # Ref audio is source speech — never fall back to the dub target language.
        prompt_lang = to_sovits_lang(self.prompt_lang) if self.prompt_lang else "auto"
        url = f"{self.endpoint}/tts"
        payload = {
            "text": req.text,
            "text_lang": text_lang,
            "ref_audio_path": str(ref),
            "prompt_text": self.prompt_text,
            "prompt_lang": prompt_lang,
            "text_split_method": "cut5",
            "media_type": "wav",
            "streaming_mode": False,
            "batch_size": 1,
            "speed_factor": 1.0,
        }
        if req.model_revision:
            payload["model_revision"] = req.model_revision
        try:
            # Upstream has shared reference/model state. Serialize preview and dubbing.
            while not _synthesis_lock.acquire(timeout=0.1):
                if control:
                    control.check()
            try:
                resp = asyncio.run(_post_audio(url, payload, control))
            finally:
                _synthesis_lock.release()
        except httpx.ReadTimeout as exc:
            raise TtsUnavailable("GPT-SoVITS 合成等待超时；CPU 推理较慢，可增加 SUBFLOW_GPTSOVITS_TIMEOUT 秒数后重试") from exc
        except httpx.HTTPError as exc:
            raise TtsUnavailable(f"请先启动 GPT-SoVITS 服务（{self.endpoint}）：{exc}") from exc
        body = resp.content or b""
        if req.model_revision and (resp.status_code == 409 or
                (resp.is_success and resp.headers.get("X-SubFlow-Model-Revision") != req.model_revision)):
            from bilingual_sub.adapters.tts.model_identity import ModelChanged

            raise ModelChanged()
        ctype = resp.headers.get("content-type", "")
        audio_ok = _is_audio(body)
        if resp.status_code >= 400 or not audio_ok:
            if body.lstrip().startswith(b"{") or "json" in ctype:
                raise TtsUnavailable(f"GPT-SoVITS 失败：{_error_detail(resp)}")
            raise TtsUnavailable(f"GPT-SoVITS 失败：{resp.status_code} {_error_detail(resp)}")
        req.dest.parent.mkdir(parents=True, exist_ok=True)
        if control:
            control.check()
        with staged_path(req.dest) as part:
            part.write_bytes(body)
            if control:
                control.check()
            part.replace(req.dest)
        return req.dest


def tts_job_fingerprint(
    provider: str,
    *,
    voice: str = "",
    endpoint: str = "",
    ref_audio: str = "",
    prompt_text: str = "",
    prompt_lang: str = "",
) -> str:
    name = (provider or "none").strip().lower() or "none"
    if name in {"", "none"}:
        return "none"
    if name == "gptsovits":
        endpoint = endpoint or default_endpoint()
        ref_audio = ref_audio or os.environ.get("SUBFLOW_GPTSOVITS_REF", "")
        prompt_text = prompt_text or os.environ.get("SUBFLOW_GPTSOVITS_PROMPT", "")
        prompt_lang = prompt_lang or os.environ.get("SUBFLOW_GPTSOVITS_PROMPT_LANG", "")
    ref_digest = ""
    if ref_audio and Path(ref_audio).expanduser().is_file():
        with Path(ref_audio).expanduser().open("rb") as stream:
            ref_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return hashlib.sha256(json.dumps(
        [
            "saturated-pcm-v5",
            name,
            voice or "",
            (endpoint or "").rstrip("/"),
            str(ref_audio or ""),
            prompt_text or "",
            prompt_lang or "",
            ref_digest,
        ], ensure_ascii=False,
    ).encode()).hexdigest()
