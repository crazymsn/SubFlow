from pathlib import Path

from bilingual_sub.gui.output_path import (
    default_output_mp4,
    next_output_path,
    relocate_output,
    resolve_output_mp4,
)


def test_default_output_sits_beside_video():
    video = Path(r"C:\media\lecture.mp4")
    assert default_output_mp4(video) == Path(r"C:\media\lecture-中英字幕.mp4")


def test_resolve_uses_typed_path():
    video = Path(r"C:\media\lecture.mp4")
    out = resolve_output_mp4(r"D:\exports\final.mp4", video)
    assert out == Path(r"D:\exports\final.mp4")


def test_resolve_directory_appends_default_name():
    video = Path(r"C:\media\lecture.mp4")
    parent = Path.cwd()
    out = resolve_output_mp4(str(parent), video)
    assert out == parent / "lecture-中英字幕.mp4"


def test_resolve_strips_quotes_and_adds_suffix():
    video = Path(r"C:\media\lecture.mp4")
    out = resolve_output_mp4(r'"D:\out\cut"', video)
    assert out.name == "cut.mp4"


def test_relocate_keeps_filename_and_swaps_folder():
    video = Path(r"C:\media\lecture.mp4")
    got = relocate_output(r"C:\media\lecture-中英字幕.mp4", Path(r"D:\exports"), video)
    assert got == Path(r"D:\exports\lecture-中英字幕.mp4")


def test_relocate_keeps_custom_filename():
    video = Path(r"C:\media\lecture.mp4")
    got = relocate_output(r"D:\old\final.mp4", Path(r"E:\out"), video)
    assert got == Path(r"E:\out\final.mp4")


def test_next_output_keeps_custom_path_when_video_changes():
    prev = Path(r"C:\media\one.mp4")
    nxt = Path(r"C:\media\two.mp4")
    got = next_output_path(r"D:\exports\final.mp4", prev, nxt)
    assert got == Path(r"D:\exports\final.mp4")


def test_next_output_refreshes_when_still_on_auto_default():
    prev = Path(r"C:\media\one.mp4")
    nxt = Path(r"C:\media\two.mp4")
    got = next_output_path(str(default_output_mp4(prev)), prev, nxt)
    assert got == default_output_mp4(nxt)
