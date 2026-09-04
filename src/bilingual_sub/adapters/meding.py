from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Protocol

from openai import APIStatusError, OpenAI

try:
    import json_repair
except ImportError:  # pragma: no cover
    json_repair = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Fixed endpoint — not user-configurable (product requirement)
MEDING_BASE_URL = "https://api.meding.site"


class MedingError(RuntimeError):
    pass


class MedingAuthError(MedingError):
    pass


class MedingClient(Protocol):
    def healthcheck(self) -> bool: ...
    def list_models(self) -> list[str]: ...
    def translate_batch(
        self,
        texts: list[str],
        *,
        model: str,
        max_en_chars: int,
        source_lang: str = "zh",
        target_lang: str = "en",
        glossary_block: str = "",
    ) -> list[str]: ...

    def chat_json(self, *, model: str, system: str, user: str) -> dict: ...


def parse_model_ids(payload: Any) -> list[str]:
    """Normalize OpenAI-style or vendor-specific model list payloads."""
    if payload is None:
        return []
    data = getattr(payload, "data", None)
    if data is None and isinstance(payload, dict):
        data = payload.get("data") or payload.get("models") or payload.get("items")
    if data is None and isinstance(payload, list):
        data = payload
    ids: list[str] = []
    for item in data or []:
        if isinstance(item, str) and item.strip():
            ids.append(item.strip())
            continue
        if isinstance(item, dict):
            mid = item.get("id") or item.get("name") or item.get("model")
            if mid:
                ids.append(str(mid).strip())
            continue
        mid = getattr(item, "id", None) or getattr(item, "name", None)
        if mid:
            ids.append(str(mid).strip())
    seen: set[str] = set()
    out: list[str] = []
    for mid in ids:
        if mid and mid not in seen:
            seen.add(mid)
            out.append(mid)
    return out


SYSTEM_PROMPT = """You translate {source_name} spoken subtitles to {target_name}. Rules:
- One line only, no quotes
- Spoken/casual tone, not literary
- Keep product names unchanged (RTX, Prefill, Decode, KV cache, Token, etc.)
- Honor terminology when provided
- Do not add explanations
- Max length: {max_en_chars} characters
{glossary}"""


class OpenAIMedingClient:
    def __init__(self, api_key: str) -> None:
        # SDK paths are relative to .../v1 (see docs/api-meding.md)
        self._client = OpenAI(api_key=api_key, base_url=f"{MEDING_BASE_URL}/v1")

    def healthcheck(self) -> bool:
        try:
            self._client.models.list()
            return True
        except APIStatusError as exc:
            if exc.status_code == 401:
                raise MedingAuthError("Invalid API key") from exc
            logger.warning("healthcheck failed: %s", exc)
            return False
        except Exception as exc:
            logger.warning("healthcheck failed: %s", exc)
            return False

    def list_models(self) -> list[str]:
        try:
            resp = self._client.models.list()
            ids = parse_model_ids(resp)
            if ids:
                return ids
        except APIStatusError as exc:
            if exc.status_code == 401:
                raise MedingAuthError("Invalid API key") from exc
            logger.warning("models.list failed: %s", exc)
        except Exception as exc:
            logger.warning("models.list failed: %s", exc)
        return []

    def chat_json(self, *, model: str, system: str, user: str) -> dict:
        resp = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
        content = (resp.choices[0].message.content or "").strip()
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            if json_repair is None:
                raise MedingError("JSON parse failed and json_repair is not installed")
            data = json_repair.loads(content)
        if not isinstance(data, dict):
            raise MedingError("chat_json did not return an object")
        return data

    def translate_batch(
        self,
        texts: list[str],
        *,
        model: str,
        max_en_chars: int,
        source_lang: str = "zh",
        target_lang: str = "en",
        glossary_block: str = "",
    ) -> list[str]:
        if not texts:
            return []
        from bilingual_sub.core.langs import prompt_name

        numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
        user_msg = (
            f"Translate each numbered {prompt_name(source_lang)} subtitle line to {prompt_name(target_lang)}.\n"
            "Return ONLY the translations, one per line, same order, same count.\n\n"
            f"{numbered}"
        )
        gloss = f"Terminology:\n{glossary_block}" if glossary_block else ""
        delays = [1.0, 2.0, 4.0]
        last_exc: Exception | None = None
        for attempt, delay in enumerate([0.0] + delays):
            if delay:
                time.sleep(delay)
            try:
                resp = self._client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": SYSTEM_PROMPT.format(
                                max_en_chars=max_en_chars,
                                source_name=prompt_name(source_lang),
                                target_name=prompt_name(target_lang),
                                glossary=gloss,
                            ),
                        },
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.3,
                )
                content = (resp.choices[0].message.content or "").strip()
                lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
                # strip leading "1. " numbering if model adds it
                cleaned = []
                for ln in lines:
                    if len(ln) > 2 and ln[0].isdigit() and ln[1] in ".)":
                        ln = ln.split(" ", 1)[-1] if " " in ln else ln[2:]
                    elif len(ln) > 3 and ln[:2].isdigit() and ln[2] in ".)":
                        ln = ln.split(" ", 1)[-1] if " " in ln else ln[3:]
                    cleaned.append(ln.strip())
                if len(cleaned) != len(texts):
                    # fallback: single-line mode per text
                    if len(texts) == 1 and cleaned:
                        return [" ".join(cleaned)[:max_en_chars]]
                    raise MedingError(
                        f"batch size mismatch: expected {len(texts)}, got {len(cleaned)}"
                    )
                return [c[:max_en_chars] for c in cleaned]
            except APIStatusError as exc:
                last_exc = exc
                if exc.status_code == 401:
                    raise MedingAuthError("Invalid API key") from exc
                if exc.status_code not in (429, 500, 502, 503, 504):
                    raise MedingError(str(exc)) from exc
            except MedingAuthError:
                raise
            except Exception as exc:
                last_exc = exc
        raise MedingError(f"translation failed after retries: {last_exc}")


def cache_db_path() -> Path:
    base = Path.home() / ".cache" / "bilingual-sub"
    base.mkdir(parents=True, exist_ok=True)
    return base / "translations.db"


def _cache_key(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\0{text}".encode()).hexdigest()


class TranslationCache:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or cache_db_path()
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS translations "
                "(key TEXT PRIMARY KEY, en TEXT NOT NULL, created_at REAL)"
            )

    def get(self, model: str, zh: str) -> str | None:
        key = _cache_key(model, zh)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT en FROM translations WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set(self, model: str, zh: str, en: str) -> None:
        key = _cache_key(model, zh)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO translations (key, en, created_at) VALUES (?,?,?)",
                (key, en, time.time()),
            )


def create_client(api_key: str) -> OpenAIMedingClient:
    return OpenAIMedingClient(api_key)
