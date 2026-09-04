"""GUI progress copy: bar always updates, log stays short."""

from __future__ import annotations

STAGE_LABELS = {
    "extract": "抽取音频",
    "silence": "检测静音",
    "transcribe": "语音识别",
    "build_cues": "整理字幕",
    "translate": "翻译",
    "render": "生成字幕",
    "burn": "烧录视频",
    "export": "导出到新路径",
    "done": "完成",
}

BAR_ONLY_STAGES = frozenset({"transcribe", "burn"})


def stage_text(stage: str) -> str:
    return STAGE_LABELS.get(stage, stage)


def should_log_stage(stage: str, last: str | None) -> bool:
    if stage in BAR_ONLY_STAGES or stage == "done":
        return False
    return stage != last
