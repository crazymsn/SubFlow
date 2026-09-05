from pathlib import Path

import pytest

from bilingual_sub.adapters.ffmpeg import FfmpegError
from bilingual_sub.core.burn import burn_subtitles
from bilingual_sub.core.control import JobStopped


@pytest.mark.parametrize("failure", [FfmpegError("encoder failure"), JobStopped()])
def test_failed_or_cancelled_burn_preserves_existing_export(tmp_path, monkeypatch, failure):
    source, ass, output = tmp_path / "input.mp4", tmp_path / "input.ass", tmp_path / "out.mp4"
    source.write_bytes(b"source")
    ass.write_text("[Script Info]\n", encoding="utf-8")
    output.write_bytes(b"previous complete export")

    def fail(args, **kwargs):
        Path(args[-1]).write_bytes(b"partial output")
        raise failure

    monkeypatch.setattr("bilingual_sub.core.burn.run_cmd", fail)
    with pytest.raises(type(failure)):
        burn_subtitles(source, ass, output, encoder="libx264")
    assert output.read_bytes() == b"previous complete export"
    assert not list(tmp_path.glob(".subflow-*"))
