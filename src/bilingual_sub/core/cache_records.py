"""Content identities for pipeline artifacts, committed with stage completion."""
from __future__ import annotations

import re
from pathlib import Path

from bilingual_sub.core.file_io import Checkpoint, file_digest
from bilingual_sub.models import STAGES

FILES = {
    "extract": ("speech.wav",),
    "silence": ("silences.json",),
    "transcribe": ("transcript.json",),
    "build_cues": ("cues.zh.json", "cues.source.json"),
    "glossary": ("glossary.generated.yaml", "glossary.merged.yaml"),
    "translate": ("cues.bilingual.json",),
    "fit_subs": ("cues.fitted.json",),
    "render": ("subs.ass",),
    "burn": ("burned.mp4",),
    "dub": ("dubbed.mp4",),
}


class InvalidCache(ValueError):
    pass


def completed_artifacts(work: Path, previous: dict, completed: str,
                        produced: dict[str, list[str]] | None, *, checkpoint: Checkpoint = None) -> dict:
    old = previous.get("artifacts", {})
    if not isinstance(old, dict):
        old = {}
    limit = STAGES.index(completed) if completed in STAGES else 0
    result = {stage: record for stage, record in old.items()
              if stage in FILES and STAGES.index(stage) <= limit}
    for stage, names in (produced or {}).items():
        if stage not in FILES or any(name not in FILES[stage] for name in names):
            raise ValueError("未知缓存产物")
        result[stage] = {name: file_digest(work / name, checkpoint=checkpoint) for name in names}
    return result


def verify_artifacts(work: Path, state: dict, stage: str, *, checkpoint: Checkpoint = None) -> dict:
    records = state.get("artifacts")
    record = records.get(stage) if isinstance(records, dict) else None
    invalid = f"{stage} 阶段缓存缺失或内容已改变；请从 {stage} 重新处理"
    if state.get("artifact_schema") != 1 or not isinstance(record, dict):
        raise InvalidCache(invalid)
    allowed = FILES[stage]
    # Empty optional records mean no output was produced, even if stale files remain.
    complete = set(record) == set(allowed)
    optional_empty = stage in {"glossary", "burn"} and not record
    if not (complete or optional_empty) or any(
        name not in allowed or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
        for name, digest in record.items()
    ):
        raise InvalidCache(invalid)
    for name, expected in record.items():
        try:
            if file_digest(work / name, checkpoint=checkpoint) != expected:
                raise InvalidCache(invalid)
        except OSError as exc:
            raise InvalidCache(invalid) from exc
    return record
