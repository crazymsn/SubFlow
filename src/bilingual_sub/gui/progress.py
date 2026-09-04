"""GUI progress copy: bar always updates, log stays short."""

from __future__ import annotations

from bilingual_sub.i18n import tr


BAR_ONLY_STAGES = frozenset({"transcribe", "burn"})

_STAGE_KEYS = {
    "ingest": "ingest",
    "extract": "extract",
    "silence": "silence",
    "transcribe": "transcribe",
    "build_cues": "build_cues",
    "glossary": "glossary_stage",
    "translate": "translate",
    "fit_subs": "fit_subs",
    "render": "render",
    "burn": "burn_stage",
    "dub": "dub_stage",
    "export": "export",
    "done": "done",
}


def stage_text(stage: str) -> str:
    return tr(_STAGE_KEYS.get(stage, stage))


def format_pct(shown: int) -> str:
    value = max(0, min(100, int(shown)))
    return f"{value}%"


def should_log_stage(stage: str, last: str | None) -> bool:
    if stage in BAR_ONLY_STAGES or stage == "done":
        return False
    return stage != last
