from __future__ import annotations

import logging
import re
from typing import Any


def redact_api_key(text: str, key: str | None = None) -> str:
    if not text:
        return text
    if key:
        text = text.replace(key, "sk-***")
    return re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-***", text)


class RedactingFormatter(logging.Formatter):
    def __init__(self, *args: Any, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._api_key = api_key

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        return redact_api_key(msg, self._api_key)


def setup_logging(level: int = logging.INFO, api_key: str | None = None) -> None:
    root = logging.getLogger("bilingual_sub")
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            RedactingFormatter("%(levelname)s %(name)s: %(message)s", api_key=api_key)
        )
        root.addHandler(handler)
