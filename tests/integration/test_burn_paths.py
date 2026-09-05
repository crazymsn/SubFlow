import shutil

import pytest
from PIL import Image

from bilingual_sub.adapters.ffmpeg import find_ffmpeg, probe_video, run_cmd
from bilingual_sub.config import bundled_fonts_dir, load_style_preset
from bilingual_sub.core.burn import burn_subtitles
from bilingual_sub.core.render import write_subtitles
from bilingual_sub.models import Cue


def test_real_burn_accepts_quoted_unicode_paths(tmp_path, monkeypatch):
    root = tmp_path / "O'Connor [中文]; clip,=one"
    root.mkdir()
    fonts = root / "font's [中文]"
    shutil.copytree(bundled_fonts_dir(), fonts)
    monkeypatch.setattr("bilingual_sub.core.burn.bundled_fonts_dir", lambda: fonts)
    source, output = root / "source's.mp4", root / "finished's.mp4"
    ass, srt = root / "subtitle's.ass", root / "subtitle's.srt"
    run_cmd([find_ffmpeg(), "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=0.8",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=0.8", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source)])
    write_subtitles([Cue(0.05, 0.7, "你好", "Hello")], load_style_preset("no-plate-large"),
                    ass, srt, play_res=(320, 180))
    burn_subtitles(source, ass, output, encoder="libx264")
    meta = probe_video(output)
    assert meta["width"] == 320 and meta["has_audio"]
    assert meta["duration"] == pytest.approx(0.8, abs=0.2)
    frame = root / "burned-frame.png"
    run_cmd([find_ffmpeg(), "-y", "-ss", "0.3", "-i", str(output), "-frames:v", "1", str(frame)])
    with Image.open(frame) as im:
        # The generated source is solid blue. White glyph pixels prove that
        # libass actually rendered subtitles, beyond a successful encode.
        assert sum(r > 200 and g > 200 and b > 200 for r, g, b in im.convert("RGB").getdata()) > 30
