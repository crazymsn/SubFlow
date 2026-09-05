import json
import wave
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bilingual_sub.adapters.ffmpeg import FfmpegError
from bilingual_sub.cli import main as cli
from bilingual_sub.core import audio
from bilingual_sub.core.control import JobControl, JobStopped
from bilingual_sub.core.resource_claims import claim_resources


def write_wav(path):
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\0\0" * 16000)


@pytest.mark.parametrize("failure", [FfmpegError("encoder failed"), JobStopped()])
def test_extract_failure_preserves_previous_audio(tmp_path, monkeypatch, failure):
    source, dest = tmp_path / "source.wav", tmp_path / "speech.wav"
    write_wav(source)
    dest.write_bytes(b"previous output")
    def fail(args, **kwargs):
        Path(args[-1]).write_bytes(b"partial output")
        raise failure
    monkeypatch.setattr(audio, "run_cmd", fail)
    with pytest.raises(type(failure)):
        audio.extract_wav(source, dest)
    assert dest.read_bytes() == b"previous output"
    assert not list(tmp_path.glob(".subflow-*"))


def test_extract_rejects_truncated_success_output(tmp_path, monkeypatch):
    source, dest = tmp_path / "source.wav", tmp_path / "speech.wav"
    write_wav(source)
    dest.write_bytes(b"previous output")
    def truncated(args, **kwargs):
        pending = Path(args[-1])
        write_wav(pending)
        pending.write_bytes(pending.read_bytes()[:-200])
    monkeypatch.setattr(audio, "run_cmd", truncated)
    with pytest.raises(ValueError):
        audio.extract_wav(source, dest)
    assert dest.read_bytes() == b"previous output"
    assert not list(tmp_path.glob(".subflow-*"))


def test_extract_output_error_is_not_mislabeled_as_missing_audio(tmp_path, monkeypatch):
    error = FfmpegError("Error initializing output file #0: Permission denied")
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(audio, "run_cmd", fail)
    with pytest.raises(FfmpegError) as caught:
        audio.extract_wav(tmp_path / "source.wav", tmp_path / "speech.wav")
    assert caught.value is error


def test_extract_cancellation_after_encoding_preserves_output(tmp_path, monkeypatch):
    source, dest = tmp_path / "source.wav", tmp_path / "speech.wav"
    write_wav(source)
    dest.write_bytes(b"previous output")
    control = JobControl()
    def encoded(args, **kwargs):
        write_wav(Path(args[-1]))
        control.stop()
    monkeypatch.setattr(audio, "run_cmd", encoded)
    with pytest.raises(JobStopped):
        audio.extract_wav(source, dest, control=control)
    assert dest.read_bytes() == b"previous output"


@pytest.mark.parametrize("preview", [0, -1, float("nan"), float("inf")])
def test_extract_invalid_preview_does_not_start_encoder(tmp_path, monkeypatch, preview):
    def unexpected(*args, **kwargs):
        pytest.fail("encoder started for invalid preview")
    monkeypatch.setattr(audio, "run_cmd", unexpected)
    with pytest.raises(ValueError):
        audio.extract_wav(tmp_path / "source.wav", tmp_path / "speech.wav", preview_sec=preview)


@pytest.mark.parametrize("alias", [False, True])
def test_extract_protects_source_and_hardlink(tmp_path, monkeypatch, alias):
    source = tmp_path / "source.wav"
    write_wav(source)
    before = source.read_bytes()
    dest = tmp_path / "alias.wav" if alias else source
    if alias:
        dest.hardlink_to(source)
    def unexpected(*args, **kwargs):
        pytest.fail("encoder started with a source/output collision")
    monkeypatch.setattr(audio, "run_cmd", unexpected)
    with pytest.raises(ValueError):
        audio.extract_wav(source, dest)
    assert source.read_bytes() == before


def test_real_extract_validates_and_publishes_pcm(tmp_path):
    source, dest = tmp_path / "中文 source.wav", tmp_path / "speech.wav"
    write_wav(source)
    before = source.read_bytes()
    dest.write_bytes(b"old output")
    audio.extract_wav(source, dest, preview_sec=0.25)
    with wave.open(str(dest), "rb") as result:
        assert (result.getnchannels(), result.getframerate(), result.getsampwidth()) == (1, 16000, 2)
        assert result.getnframes() == 4000
    assert source.read_bytes() == before
    assert not list(tmp_path.glob(".subflow-*"))


@pytest.fixture
def cli_files(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBFLOW_LOCK_DIR", str(tmp_path / "locks"))
    source = tmp_path / "source.wav"
    write_wav(source)
    out = tmp_path / "out"
    out.mkdir()
    (out / "speech.wav").write_bytes(b"old audio")
    (out / "silences.json").write_bytes(b"old record")
    return source, out


def invoke(source, out):
    return CliRunner().invoke(cli.app, ["extract", str(source), "-o", str(out)])


def assert_old(out):
    assert (out / "speech.wav").read_bytes() == b"old audio"
    assert (out / "silences.json").read_bytes() == b"old record"
    assert sorted(path.name for path in out.iterdir()) == ["silences.json", "speech.wav"]


def test_cli_silence_failure_preserves_complete_output_set(cli_files, monkeypatch):
    source, out = cli_files
    def fail(*args, **kwargs):
        raise FfmpegError("silence failed")
    monkeypatch.setattr(cli, "detect_silences", fail)
    result = invoke(source, out)
    assert result.exit_code != 0 and "silence failed" in str(result.exception)
    assert_old(out)


def test_cli_second_commit_failure_rolls_back_audio(cli_files, monkeypatch):
    source, out = cli_files
    original = Path.replace
    def replace(path, dest):
        if Path(dest) == out / "silences.json" and path.name.startswith(".subflow-output-"):
            raise PermissionError("record is locked")
        return original(path, dest)
    monkeypatch.setattr(Path, "replace", replace)
    result = invoke(source, out)
    assert result.exit_code != 0 and "record is locked" in str(result.exception)
    assert_old(out)


@pytest.mark.parametrize("filename", ["speech.wav", "silences.json"])
def test_cli_protects_input_before_any_extraction(cli_files, monkeypatch, filename):
    _, out = cli_files
    source = out / filename
    def unexpected(*args, **kwargs):
        pytest.fail("extraction started with an input/output collision")
    monkeypatch.setattr(cli, "extract_wav", unexpected)
    result = invoke(source, out)
    assert isinstance(result.exception, ValueError)
    assert_old(out)


def test_cli_respects_other_job_output_claim(cli_files):
    source, out = cli_files
    with claim_resources(reads=[out / "speech.wav"], writes=[]):
        result = invoke(source, out)
    assert result.exit_code != 0
    assert_old(out)


def test_real_cli_extract_publishes_audio_and_silence(cli_files):
    source, out = cli_files
    result = invoke(source, out)
    assert result.exit_code == 0, result.exception
    assert json.loads((out / "silences.json").read_text()) == [[0.0, 1.0]]
    with wave.open(str(out / "speech.wav"), "rb") as stream:
        assert stream.getnframes() == 16000
    assert sorted(path.name for path in out.iterdir()) == ["silences.json", "speech.wav"]
