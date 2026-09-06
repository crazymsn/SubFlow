"""Select a local voice-cloning engine for the requested language pair."""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from functools import wraps

_engine_lock = threading.RLock()

QWEN_LANGS = {"zh": "Chinese", "en": "English", "ja": "Japanese", "ko": "Korean",
              "es": "Spanish", "ru": "Russian", "fr": "French", "de": "German",
              "pt": "Portuguese", "it": "Italian"}
EXTRA_LANGS = frozenset({"es", "ru", "fr", "de", "pt", "it"})


def family(lang: str) -> str:
    return (lang or "").strip().lower().replace("_", "-").split("-", 1)[0]


def resolve_provider(provider: str, target: str, source: str = "") -> str:
    name = (provider or "none").strip().lower()
    if name in {"openai", "azure"}:
        name = "gptsovits"
    if name == "gptsovits" and (family(target) in EXTRA_LANGS or family(source) in EXTRA_LANGS):
        return "qwen3"
    return name


def provider_endpoint(provider: str, configured: str = "") -> str:
    if provider == 'qwen3-native':
        return (os.environ.get('SUBFLOW_QWEN_NATIVE_URL', '').strip() or 'http://127.0.0.1:19882').rstrip('/')
    if provider == "qwen3":
        return (os.environ.get("SUBFLOW_QWEN_TTS_URL", "").strip() or "http://127.0.0.1:9881").rstrip("/")
    from bilingual_sub.adapters.tts.gptsovits import default_endpoint

    return configured or default_endpoint()


def ensure_running(provider: str, endpoint: str = "", **kwargs):
    with engine_session(provider, kwargs.get("control")):
        if provider.startswith("qwen3"):
            from bilingual_sub.adapters.tts.qwen_runtime import ensure_running as boot
            if provider == 'qwen3-native':
                kwargs['native'] = True
        else:
            from bilingual_sub.adapters.tts.gptsovits_runtime import ensure_running as boot
        return boot(endpoint or None, **kwargs)


@contextmanager
def engine_session(provider: str, control=None):
    # Hold the engine for the entire preview/job, including gaps between cues.
    # Switching models must not evict another operation in this client.
    while not _engine_lock.acquire(timeout=0.1):
        if control:
            control.wait_if_paused()
    try:
        if control:
            control.wait_if_paused()
        if provider.startswith("qwen3"):
            from bilingual_sub.adapters.tts.gptsovits_runtime import release_idle_servers
            from bilingual_sub.adapters.tts.qwen_runtime import (
                release_idle_servers as release_other_qwen,
            )

            release_other_qwen(keep_engine=provider)
        else:
            from bilingual_sub.adapters.tts.qwen_runtime import release_idle_servers
        release_idle_servers()
        yield
    finally:
        _engine_lock.release()


def preview_engine_session(operation):
    @wraps(operation)
    def wrapped(*args, **kwargs):
        provider = resolve_provider(kwargs.get("provider", "gptsovits"), kwargs.get("lang", "zh"),
                                    kwargs.get("prompt_lang", ""))
        with engine_session(provider, kwargs.get("control")):
            return operation(*args, **kwargs)
    return wrapped
