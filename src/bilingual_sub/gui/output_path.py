"""Resolve and refresh the GUI output MP4 path."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from bilingual_sub.core.langs import output_stem_suffix, output_stem_suffixes

DEFAULT_STEM_SUFFIX = "-中英字幕"
VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".m4v", ".webm"}


def default_output_mp4(video: Path, mode: str = "bilingual") -> Path:
    return video.with_name(video.stem + output_stem_suffix(mode) + ".mp4")


def replace_auto_stem(name: str, mode: str) -> str:
    path = Path(name)
    stem = path.stem
    ext = path.suffix if path.suffix.lower() in VIDEO_SUFFIXES else ".mp4"
    wanted = output_stem_suffix(mode)
    for old in sorted(output_stem_suffixes(), key=len, reverse=True):
        if stem.endswith(old):
            return stem[: -len(old)] + wanted + ext
    return path.name if path.suffix.lower() in VIDEO_SUFFIXES else stem + ext


def refresh_output_path(raw: str, video: Path | None, mode: str) -> Path:
    text = _strip_wrap(raw)
    if not text:
        if video is not None:
            return default_output_mp4(video, mode)
        return Path(f"output{output_stem_suffix(mode)}.mp4")
    path = Path(text).expanduser()
    if path.exists() and path.is_dir():
        return path / current_filename("", video, mode)
    if path.suffix.lower() not in VIDEO_SUFFIXES:
        path = path.with_suffix(".mp4")
    refreshed = path.with_name(replace_auto_stem(path.name, mode))
    return refreshed


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
        os.path.normpath(str(right))
    )


def _strip_wrap(raw: str) -> str:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text


def current_filename(raw: str, video: Path | None, mode: str = "bilingual") -> str:
    text = _strip_wrap(raw)
    if text:
        path = Path(text).expanduser()
        if path.suffix.lower() in VIDEO_SUFFIXES:
            return replace_auto_stem(path.name, mode)
        if path.suffix:
            return replace_auto_stem(path.with_suffix(".mp4").name, mode)
        if path.name:
            return replace_auto_stem(path.name + ".mp4", mode)
    if video is not None:
        return default_output_mp4(video, mode).name
    return f"output{output_stem_suffix(mode)}.mp4"


def relocate_output(raw: str, new_dir: Path, video: Path | None, mode: str = "bilingual") -> Path:
    return Path(new_dir).expanduser() / current_filename(raw, video, mode)


def resolve_output_mp4(raw: str, video: Path | None, mode: str = "bilingual") -> Path:
    text = _strip_wrap(raw)
    if not text:
        if video is None:
            raise ValueError("empty output path")
        return default_output_mp4(video, mode)
    path = Path(text).expanduser()
    if path.exists() and path.is_dir():
        return path / current_filename("", video, mode)
    if path.suffix.lower() not in VIDEO_SUFFIXES:
        path = path.with_suffix(".mp4")
    return path.with_name(replace_auto_stem(path.name, mode))


def sidecar_srt(dest_mp4: Path) -> Path:
    return dest_mp4.with_name(dest_mp4.stem + ".bilingual.srt")


def sidecar_ass(dest_mp4: Path) -> Path:
    return sidecar_srt(dest_mp4).with_suffix(".ass")


def sidecar_dub(dest_mp4: Path) -> Path:
    return dest_mp4.with_name(dest_mp4.stem + "-dub.mp4")


def resolve_dub_sidecar(output_video: Path | None, output_srt: Path) -> Path:
    """No-burn dub next to the intended MP4 stem, never `*.bilingual-dub.mp4`."""
    if output_video is not None:
        return sidecar_dub(output_video)
    stem = output_srt.stem
    if stem.endswith(".bilingual"):
        stem = stem[: -len(".bilingual")]
    return output_srt.with_name(stem + "-dub.mp4")


def _copy_if_needed(src: Path | None, dest: Path) -> Path | None:
    if src is None or not src.is_file():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return dest


def copy_finished_outputs(
    dest_mp4: Path,
    *,
    src_mp4: Path | None,
    src_srt: Path | None,
    src_ass: Path | None,
    src_dub: Path | None = None,
) -> dict[str, Path]:
    """Copy an already-finished job to a new folder/name. No ASR or translate."""
    dest_mp4.parent.mkdir(parents=True, exist_ok=True)
    copied: dict[str, Path] = {}
    mp4 = _copy_if_needed(src_mp4, dest_mp4)
    if mp4 is not None:
        copied["mp4"] = mp4
    srt = _copy_if_needed(src_srt, sidecar_srt(dest_mp4))
    if srt is not None:
        copied["srt"] = srt
    ass = _copy_if_needed(src_ass, sidecar_ass(dest_mp4))
    if ass is not None:
        copied["ass"] = ass
    dub = _copy_if_needed(src_dub, sidecar_dub(dest_mp4))
    if dub is not None:
        copied["dub"] = dub
    return copied


def next_output_path(
    current: str,
    previous_video: Path | None,
    new_video: Path,
    mode: str = "bilingual",
) -> Path:
    auto_new = default_output_mp4(new_video, mode)
    text = _strip_wrap(current)
    if not text:
        return auto_new
    cur = Path(text).expanduser()
    if previous_video is not None:
        autos = [default_output_mp4(previous_video, item) for item in _auto_modes()]
        if any(_same_path(cur, auto) for auto in autos):
            return auto_new
    return cur


def _auto_modes() -> tuple[str, ...]:
    from bilingual_sub.core.langs import SINGLE_SUB_MODES

    return ("bilingual", "enzh", "netflix_single") + tuple(code for code, _label in SINGLE_SUB_MODES)
