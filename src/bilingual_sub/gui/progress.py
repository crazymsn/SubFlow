"""GUI progress copy: bar always updates, log stays short."""

from __future__ import annotations

from bilingual_sub.i18n import tr


STAGE_LABELS = {
    "ingest": "下载视频",
    "extract": "抽取音频",
    "silence": "检测静音",
    "transcribe": "语音识别",
    "build_cues": "整理字幕",
    "glossary": "术语",
    "translate": "翻译",
    "fit_subs": "字幕规范",
    "render": "生成字幕",
    "burn": "烧录视频",
    "dub": "配音",
    "export": "导出到新路径",
    "done": "完成",
}

BAR_ONLY_STAGES = frozenset({"transcribe", "burn"})


def stage_text(stage: str) -> str:
    mapped = {
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
    key = mapped.get(stage)
    if key:
        text = tr(key)
        if text != key:
            return text
    return STAGE_LABELS.get(stage, stage)


def should_log_stage(stage: str, last: str | None) -> bool:
    if stage in BAR_ONLY_STAGES or stage == "done":
        return False
    return stage != last
