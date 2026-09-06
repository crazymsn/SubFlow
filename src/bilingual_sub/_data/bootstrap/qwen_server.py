"""Local Qwen3 voice-cloning service, run only in its isolated Python runtime."""
from __future__ import annotations

import asyncio
import gc
import hashlib
import io
import json
import logging
import os
import subprocess
import threading
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from qwen_tts import Qwen3TTSModel
from transformers import StoppingCriteria, StoppingCriteriaList

logger = logging.getLogger("subflow.qwen")
app = FastAPI(title="SubFlow Qwen3-TTS")
lock = asyncio.Lock()
model = None
model_home: Path
device = "cpu"
revision = uuid.uuid4().hex
prompt_key = None
prompt_cache = None
native_voice = False
clone_home: Path | None = None
active_home: Path | None = None
designed_voice = False
voice_bank = {}


def choose_device() -> str:
    requested = os.environ.get("SUBFLOW_TORCH_BACKEND", "auto").strip().lower() or 'auto'
    if requested not in {'auto', 'cuda', 'mps', 'cpu'}:
        raise ValueError('SUBFLOW_TORCH_BACKEND must be auto, cuda, mps or cpu')
    if requested in {"auto", "cuda"} and torch.cuda.is_available():
        return "cuda:0"
    if requested in {"auto", "mps"} and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_model(target: str, home: Path | None = None, *, preserve_revision=False):
    global model, device, revision, prompt_key, prompt_cache, active_home
    model = prompt_cache = prompt_key = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()
    dtype = (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16) if target.startswith("cuda") else torch.float32
    active_home = home or active_home or model_home
    model = Qwen3TTSModel.from_pretrained(str(active_home), device_map=target, dtype=dtype,
                                         attn_implementation="sdpa", local_files_only=True)
    device = target
    if not preserve_revision:
        revision = uuid.uuid4().hex
    logger.warning("Qwen3-TTS loaded on %s (%s)", device, dtype)


def accelerator_error(exc: Exception, target: str) -> bool:
    text = str(exc).lower()
    return target != "cpu" and isinstance(exc, (RuntimeError, NotImplementedError)) and any(
        word in text for word in ("cuda", "cublas", "cudnn", "mps", "out of memory", "not implemented"))


class Payload(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    text_lang: str
    ref_audio_path: str = ""
    prompt_text: str = ""
    model_revision: str = ""
    speaker: str = "Aiden"


class Cancelled(RuntimeError):
    pass


class StopGeneration(StoppingCriteria):
    def __init__(self, cancelled):
        self.cancelled = cancelled
        self.steps = 0

    def __call__(self, input_ids, scores, **kwargs):
        self.steps += 1
        if self.cancelled.is_set():
            raise Cancelled("Synthesis cancelled")
        if self.steps >= 2048:
            raise RuntimeError("合成超出单句长度上限，请拆分过长的字幕后重试")
        return False


def synthesize(payload: Payload, cancelled: threading.Event) -> bytes:
    global prompt_key, prompt_cache, designed_voice
    if cancelled.is_set():
        raise Cancelled()
    designed_voice = native_voice and payload.speaker in voice_bank
    if native_voice:
        if payload.speaker.startswith('SubFlow_') and not designed_voice:
            raise ValueError('设计音色资源不存在，请重新安装完整客户端')
        wanted = clone_home if designed_voice else model_home
        if wanted is None:
            raise ValueError('设计音色需要内置 Qwen Base 模型，请更新完整客户端')
        if active_home != wanted:
            # The public revision identifies this service's fixed pair of models.
            # Switching timbre unloads the other model to stay within laptop VRAM.
            load_model(device, wanted, preserve_revision=True)
        if not designed_voice:
            return generate_audio(payload, cancelled)
        entry = voice_bank[payload.speaker]
        payload = payload.model_copy(update={
            'ref_audio_path': str(Path(__file__).with_name('voices') / entry['file']),
            'prompt_text': entry['text'],
        })
    path = Path(payload.ref_audio_path).expanduser()
    if not path.is_file():
        raise ValueError(f"参考音频不存在：{path}")
    # Only local files, never fetch URLs or interpret base64 supplied as paths.
    content = path.read_bytes()
    if designed_voice and hashlib.sha256(content).hexdigest() != voice_bank[payload.speaker]['sha256']:
        raise ValueError('内置设计音色校验失败，请重新安装完整客户端')
    try:
        audio, sr = sf.read(io.BytesIO(content), dtype="float32", always_2d=True)
    except (RuntimeError, sf.LibsndfileError):
        # Match the desktop's MP3/M4A/AAC reference picker using bundled FFmpeg.
        options = {"creationflags": 0x08000000} if os.name == "nt" else {}
        with subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-t", "11", "-vn",
                "-ac", "1", "-ar", "24000", "-f", "wav", "pipe:1"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options) as proc:
            try:
                while True:
                    if cancelled.is_set():
                        raise Cancelled()
                    try:
                        decoded, error = proc.communicate(timeout=.1)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if proc.returncode:
                    raise ValueError("参考音频无法解码：" + error.decode("utf-8", errors="replace")[-300:])
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
        audio, sr = sf.read(io.BytesIO(decoded), dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    if not 3 <= len(audio) / sr <= 10 or not np.isfinite(audio).all() or np.max(np.abs(audio)) < 1e-5:
        raise ValueError("参考音频需要 3–10 秒清晰人声，不能是静音或损坏的音频")
    key = (hashlib.sha256(content).hexdigest(), payload.prompt_text, revision)
    assert model is not None
    if key != prompt_key:
        prompt_cache = model.create_voice_clone_prompt(ref_audio=(audio, sr),
            ref_text=payload.prompt_text or None, x_vector_only_mode=not bool(payload.prompt_text.strip()))
        prompt_key = key
    return generate_audio(payload, cancelled)


def generate_audio(payload: Payload, cancelled: threading.Event) -> bytes:
    assert model is not None
    # qwen-tts 0.1.1 drops unknown generation kwargs in its outer model.
    # Install cancellation on the actual autoregressive talker for this request.
    talker = model.model.talker
    generate = talker.generate
    stop = StopGeneration(cancelled)
    def cancellable_generate(*args, **kwargs):
        kwargs["stopping_criteria"] = StoppingCriteriaList([stop])
        return generate(*args, **kwargs)
    talker.generate = cancellable_generate
    try:
        torch.manual_seed(42)
        if native_voice and not designed_voice:
            wavs, rate = model.generate_custom_voice(text=payload.text, language=payload.text_lang,
                speaker=payload.speaker, max_new_tokens=2048)
        else:
            wavs, rate = model.generate_voice_clone(text=payload.text, language=payload.text_lang,
                voice_clone_prompt=prompt_cache, max_new_tokens=2048)
    finally:
        talker.generate = generate
    if cancelled.is_set():
        raise Cancelled()
    if not wavs or len(wavs[0]) == 0 or not np.isfinite(wavs[0]).all():
        raise RuntimeError("模型没有生成有效音频")
    result = io.BytesIO()
    sf.write(result, np.clip(wavs[0], -1, 1), rate, format="WAV", subtype="PCM_16")
    return result.getvalue()


@app.get("/subflow/runtime")
async def runtime():
    return {"engine": "qwen3-native" if native_voice else "qwen3", "device": device,
            "model_revision": revision, "busy": lock.locked()}


@app.post("/tts")
async def tts(payload: Payload, request: Request):
    # Reject web-page requests to the local file-reading service.
    if request.headers.get("origin"):
        raise HTTPException(403, "Browser origins are not allowed")
    cancelled = threading.Event()
    async with lock:
        if await request.is_disconnected():
            raise HTTPException(499, "Client disconnected")
        if payload.model_revision and payload.model_revision != revision:
            raise HTTPException(409, "Model changed")
        task = asyncio.create_task(asyncio.to_thread(synthesize, payload, cancelled))
        try:
            while not task.done():
                if await request.is_disconnected():
                    cancelled.set()
                await asyncio.wait({task}, timeout=0.1)
            return Response(task.result(), media_type="audio/wav", headers={"X-SubFlow-Model-Revision": revision})
        except Cancelled:
            raise HTTPException(499, "Synthesis cancelled") from None
        except Exception as exc:
            fallback = accelerator_error(exc, device)
            logger.exception("Qwen3-TTS synthesis failed")
            # Release exception frames holding GPU tensors before loading CPU.
            detail = f"{type(exc).__name__}: {exc}"
            exc.__traceback__ = None
            if not fallback:
                raise HTTPException(500, detail) from None
        finally:
            cancelled.set()
            if not task.done():
                await task
        await asyncio.to_thread(load_model, "cpu")
        raise HTTPException(409, "GPU unavailable; reloaded on CPU, retry under the new model revision")


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--clone-model", type=Path)
    args = parser.parse_args()
    model_home = args.model
    native_voice = args.native
    clone_home = args.clone_model
    if native_voice:
        bank = Path(__file__).with_name('voices') / 'voices.json'
        if bank.is_file():
            entries = json.loads(bank.read_text(encoding='utf-8'))['voices']
            for entry in entries:
                filename = entry['file']
                if Path(filename).name != filename or not filename.endswith('.wav'):
                    raise ValueError('Invalid bundled voice path')
                voice_bank[entry['id']] = entry
    torch.set_num_threads(max(1, min(8, (os.cpu_count() or 4) // 2)))
    target = choose_device()
    try:
        load_model(target)
    except Exception as error:
        if not accelerator_error(error, target):
            raise
        logger.exception("GPU model initialization failed; switching to CPU")
        error.__traceback__ = None
    if model is None:
        load_model("cpu")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
