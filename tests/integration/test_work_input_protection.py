import pytest

from bilingual_sub import pipeline as p
from bilingual_sub.config import AppSettings
from bilingual_sub.models import JobConfig


def config(tmp_path):
    source = tmp_path / "original.mp4"
    source.write_bytes(b"original video")
    work = tmp_path / "work"
    work.mkdir()
    return JobConfig(source, tmp_path / "out.mp4", tmp_path / "out.srt", work)


@pytest.mark.parametrize("field", ["input_video", "glossary_path", "tts_ref_audio"])
@pytest.mark.parametrize("name", ["job_state.json", ".job.lock", "speech.wav", "subs.ass",
                                  "glossary.merged.yaml", "whisper.log", "tts/ref.wav",
                                  "downloads/source.mp4"])
def test_managed_work_paths_cannot_be_inputs(tmp_path, monkeypatch, field, name):
    cfg = config(tmp_path)
    source = cfg.work_dir / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"keep input intact")
    setattr(cfg, field, source)
    monkeypatch.setattr(p, "_run_in_work", lambda *a: pytest.fail("unsafe task started"))
    with pytest.raises(ValueError, match="工作|覆盖"):
        p.run(cfg, AppSettings())
    assert source.read_bytes() == b"keep input intact"


@pytest.mark.parametrize("field", ["input_video", "glossary_path", "tts_ref_audio"])
def test_state_initialization_does_not_destroy_input(tmp_path, monkeypatch, field):
    cfg = config(tmp_path)
    source = cfg.work_dir / "job_state.json"
    source.write_bytes(b"original input content")
    setattr(cfg, field, source)
    def stop_after_ingest(*args, **kwargs):
        raise ValueError("stop before model processing")
    monkeypatch.setattr(p, "probe_video", stop_after_ingest)
    with pytest.raises(ValueError):
        p.run(cfg, AppSettings())
    assert source.read_bytes() == b"original input content"


@pytest.mark.parametrize("name", ["original.mp4", "source.mp4"])
def test_unreserved_video_in_work_remains_supported(tmp_path, monkeypatch, name):
    cfg = config(tmp_path)
    cfg.input_video = cfg.work_dir / name
    cfg.input_video.write_bytes(b"original video")
    sentinel = object()
    monkeypatch.setattr(p, "_run_in_work", lambda *a: sentinel)
    assert p.run(cfg, AppSettings()) is sentinel
    assert cfg.input_video.read_bytes() == b"original video"


@pytest.mark.parametrize("name", ["job_state.json", "speech.wav", "whisper.log"])
def test_external_input_hardlinked_to_work_output_is_rejected(tmp_path, monkeypatch, name):
    cfg = config(tmp_path)
    (cfg.work_dir / name).hardlink_to(cfg.input_video)
    monkeypatch.setattr(p, "_run_in_work", lambda *a: pytest.fail("unsafe task started"))
    with pytest.raises(ValueError, match="工作|覆盖"):
        p.run(cfg, AppSettings())
    assert cfg.input_video.read_bytes() == b"original video"


def test_default_glossary_is_protected_before_state_write(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    glossary = cfg.work_dir / "job_state.json"
    glossary.write_bytes(b"keep default glossary")
    monkeypatch.setattr(p, "default_glossary_path", lambda: glossary)
    with pytest.raises(ValueError, match="工作文件会覆盖输入"):
        p.run(cfg, AppSettings())
    assert glossary.read_bytes() == b"keep default glossary"


@pytest.mark.parametrize("downloaded", [False, True])
def test_reference_equal_to_work_video_is_safe_only_without_replacement(tmp_path, monkeypatch, downloaded):
    cfg = config(tmp_path)
    cfg.input_video = cfg.work_dir / "source.mp4"
    cfg.input_video.write_bytes(b"reference content")
    cfg.tts_ref_audio = cfg.input_video
    cfg.source_url = "https://example.test/video" if downloaded else None
    sentinel = object()
    monkeypatch.setattr(p, "_run_in_work", lambda *a: sentinel)
    if downloaded:
        with pytest.raises(ValueError, match="工作文件会覆盖输入"):
            p.run(cfg, AppSettings())
    else:
        assert p.run(cfg, AppSettings()) is sentinel
    assert cfg.input_video.read_bytes() == b"reference content"


def test_non_reserved_glossary_and_reference_in_work_are_supported(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    cfg.glossary_path = cfg.work_dir / "user-glossary.yaml"
    cfg.tts_ref_audio = cfg.work_dir / "my-reference.wav"
    cfg.glossary_path.write_bytes(b"custom glossary")
    cfg.tts_ref_audio.write_bytes(b"custom reference")
    sentinel = object()
    monkeypatch.setattr(p, "_run_in_work", lambda *a: sentinel)
    assert p.run(cfg, AppSettings()) is sentinel
