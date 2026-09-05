from pathlib import Path

from bilingual_sub.gui.output_path import (
    copy_finished_outputs,
    default_output_mp4,
    next_output_path,
    refresh_output_path,
    relocate_output,
    resolve_output_mp4,
    sidecar_ass,
    sidecar_srt,
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


def test_copy_finished_outputs_renames_sidecars(tmp_path: Path):
    src_dir = tmp_path / "old"
    src_dir.mkdir()
    src_mp4 = src_dir / "talk-中英字幕.mp4"
    src_srt = src_dir / "talk-中英字幕.bilingual.srt"
    src_ass = src_dir / "talk-中英字幕.bilingual.ass"
    src_mp4.write_bytes(b"mp4-bytes")
    src_srt.write_text("srt", encoding="utf-8")
    src_ass.write_text("ass", encoding="utf-8")
    dest = tmp_path / "exports" / "final.mp4"
    copied = copy_finished_outputs(dest, src_mp4=src_mp4, src_srt=src_srt, src_ass=src_ass)
    assert dest.read_bytes() == b"mp4-bytes"
    assert sidecar_srt(dest).read_text(encoding="utf-8") == "srt"
    assert sidecar_ass(dest).read_text(encoding="utf-8") == "ass"
    assert copied["mp4"] == dest


def test_next_output_refreshes_when_still_on_auto_default():
    prev = Path(r"C:\media\one.mp4")
    nxt = Path(r"C:\media\two.mp4")
    got = next_output_path(str(default_output_mp4(prev)), prev, nxt)
    assert got == default_output_mp4(nxt)


def test_enzh_stem_is_not_chinese_english_label():
    video = Path(r"C:\media\lecture.mp4")
    assert default_output_mp4(video, "enzh") == Path(r"C:\media\lecture-英中字幕.mp4")
    assert default_output_mp4(video, "bilingual") == Path(r"C:\media\lecture-中英字幕.mp4")
    switched = refresh_output_path(str(default_output_mp4(video, "bilingual")), video, "enzh")
    assert switched == Path(r"C:\media\lecture-英中字幕.mp4")
    custom = refresh_output_path(r"D:\exports\final.mp4", video, "enzh")
    assert custom == Path(r"D:\exports\final.mp4")
    resolved = resolve_output_mp4(r"C:\media\lecture-中英字幕.mp4", video, mode="enzh")
    assert resolved == Path(r"C:\media\lecture-英中字幕.mp4")
