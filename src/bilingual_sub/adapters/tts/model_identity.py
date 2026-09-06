"""Bind cached audio to one committed server model generation."""
from __future__ import annotations

import re
import uuid
from functools import wraps

import httpx

from bilingual_sub.adapters.tts.base import TtsUnavailable


class ModelChanged(TtsUnavailable):
    def __init__(self):
        super().__init__("配音模型已变化，请重试；未提交混合模型的音频")


def fetch_model_revision(endpoint: str) -> str | None:
    """Legacy/external APIs without this extension have no reusable identity."""
    try:
        with httpx.Client(trust_env=False, timeout=3) as client:
            response = client.get(endpoint.rstrip("/") + "/subflow/runtime")
        if response.status_code != 200:
            return None
        data = response.json()
        revision = data.get("model_revision") if isinstance(data, dict) else None
        return revision if isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{32}", revision) else None
    except (httpx.HTTPError, ValueError):
        return None


def current_model_revision(endpoint: str = "") -> str | None:
    from bilingual_sub.adapters.tts.gptsovits import default_endpoint

    return fetch_model_revision(endpoint or default_endpoint())


class ModelSnapshot:
    def __init__(self, provider: str, endpoint: str = ""):
        self.endpoint = endpoint
        self.enabled = provider in {"gptsovits", "qwen3", "qwen3-native"}
        self.revision = current_model_revision(endpoint) if self.enabled else ""
        # Unknown backends remain usable, but cannot certify persistent caches.
        self.cache_id = self.revision if self.revision is not None else "unknown:" + uuid.uuid4().hex

    def check(self):
        if self.enabled and self.revision is not None and current_model_revision(self.endpoint) != self.revision:
            raise ModelChanged()


def retry_model_change(operation):
    @wraps(operation)
    def run(*args, **kwargs):
        # CPU fallback may reload once; restart the complete audio operation so
        # every clip is generated under the new generation. Never loop forever.
        for attempt in range(2):
            try:
                return operation(*args, **kwargs)
            except ModelChanged:
                if attempt:
                    raise
    return run
