"""Resolve and refresh the GUI output MP4 path."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_STEM_SUFFIX = "-中英字幕"
VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".m4v", ".webm"}


def default_output_mp4(video: Path) -> Path:
    return video.with_name(video.stem + DEFAULT_STEM_SUFFIX + ".mp4")


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
        os.path.normpath(str(right))
    )


def _strip_wrap(raw: str) -> str:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text


def resolve_output_mp4(raw: str, video: Path | None) -> Path:
    text = _strip_wrap(raw)
    if not text:
        if video is None:
            raise ValueError("empty output path")
        return default_output_mp4(video)
    path = Path(text).expanduser()
    if path.exists() and path.is_dir():
        name = default_output_mp4(video).name if video else f"output{DEFAULT_STEM_SUFFIX}.mp4"
        path = path / name
    elif path.suffix.lower() not in VIDEO_SUFFIXES:
        path = path.with_suffix(".mp4")
    return path


def next_output_path(current: str, previous_video: Path | None, new_video: Path) -> Path:
    auto_new = default_output_mp4(new_video)
    text = _strip_wrap(current)
    if not text:
        return auto_new
    cur = Path(text).expanduser()
    if previous_video is not None and _same_path(cur, default_output_mp4(previous_video)):
        return auto_new
    parent = cur.parent if cur.suffix else cur
    return parent / auto_new.name
