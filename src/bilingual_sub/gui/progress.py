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
    if stage.startswith("dub|"):
        parts = stage.split("|")
        if len(parts) == 5 and all(p.isdigit() for p in parts[2:]):
            _, phase, current, total, seconds = parts
            elapsed = int(seconds)
            return tr("dub_progress" if int(total) else "dub_progress_wait").format(phase=tr("dub_phase_" + phase), current=current,
                                            total=total, elapsed=f"{elapsed // 60:02d}:{elapsed % 60:02d}")
    return tr(_STAGE_KEYS.get(stage, stage))


def format_pct(shown: int) -> str:
    value = max(0, min(100, int(shown)))
    return f"{value}%"


def should_log_stage(stage: str, last: str | None) -> bool:
    if stage.startswith("dub|"):
        # Elapsed-time heartbeats update the UI without filling the job log.
        return stage.rsplit("|", 1)[0] != (last or "").rsplit("|", 1)[0]
    if stage in BAR_ONLY_STAGES or stage == "done":
        return False
    return stage != last
