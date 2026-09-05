from __future__ import annotations

import logging

from bilingual_sub.adapters.meding import MedingAuthError, MedingClient, MedingServiceError
from bilingual_sub.core.control import JobStopped
from bilingual_sub.core.glossary import Glossary
from bilingual_sub.core.langs import prompt_name
from bilingual_sub.core.prompts import PROMPT_GLOSSARY
from bilingual_sub.models import Cue

logger = logging.getLogger(__name__)


def extract_glossary(
    cues: list[Cue],
    *,
    model: str,
    source_lang: str,
    target_lang: str,
    client: MedingClient,
    limit_chars: int = 8000,
) -> Glossary:
    blob = "\n".join(c.source for c in cues if c.source)[:limit_chars]
    if not blob.strip():
        return Glossary()
    try:
        data = client.chat_json(
            model=model,
            system=PROMPT_GLOSSARY.format(
                source_name=prompt_name(source_lang),
                target_name=prompt_name(target_lang),
            ),
            user=blob,
        )
    except (MedingAuthError, MedingServiceError, JobStopped):
        raise
    except Exception as exc:
        logger.warning("glossary AI skipped: %s", exc)
        return Glossary()
    terms = data.get("terms") if isinstance(data, dict) else None
    if not isinstance(terms, list):
        return Glossary()
    return Glossary.from_terms([t for t in terms if isinstance(t, dict)][:40])
