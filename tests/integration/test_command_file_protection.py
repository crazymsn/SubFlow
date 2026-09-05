import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from bilingual_sub.cli import main as cli
from bilingual_sub.core.resource_claims import claim_resources


@pytest.fixture
def inputs(tmp_path):
    transcript = tmp_path / "transcript.json"
    transcript.write_text(json.dumps({"segments": [{"start": 0, "end": 1, "text": "你好。"}]}), encoding="utf-8")
    cues = tmp_path / "cues.json"
    cues.write_text(json.dumps([{"start": 0, "end": 1, "zh": "你好。", "en": "Hello."}]), encoding="utf-8")
    silences = tmp_path / "silences.json"
    silences.write_text("[]")
    glossary = tmp_path / "glossary.yaml"
    glossary.write_text("replacements: []\n")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"protected audio")
    return {"transcript": transcript, "cues": cues, "silences": silences, "glossary": glossary, "audio": audio}


def invoke(args):
    return CliRunner().invoke(cli.app, [str(arg) for arg in args])


@pytest.mark.parametrize("protected", ["transcript", "silences", "glossary"])
@pytest.mark.parametrize("hardlink", [False, True])
def test_build_cues_cannot_overwrite_inputs(inputs, tmp_path, protected, hardlink):
    dest = inputs[protected]
    original = dest.read_bytes()
    if hardlink:
        dest = tmp_path / "alias.json"
        dest.hardlink_to(inputs[protected])
    result = invoke(["build-cues", inputs["transcript"], inputs["silences"], "--glossary", inputs["glossary"], "-o", dest])
    assert isinstance(result.exception, ValueError), result.exception
    assert inputs[protected].read_bytes() == original
    assert dest.read_bytes() == original


@pytest.mark.parametrize("output", ["ass", "srt"])
def test_render_cannot_replace_cue_source(inputs, tmp_path, output):
    original = inputs["cues"].read_bytes()
    ass = inputs["cues"] if output == "ass" else tmp_path / "out.ass"
    srt = inputs["cues"] if output == "srt" else tmp_path / "out.srt"
    result = invoke(["render", inputs["cues"], "-o", ass, "--srt", srt])
    assert isinstance(result.exception, ValueError), result.exception
    assert inputs["cues"].read_bytes() == original
    assert not (tmp_path / "out.ass").exists() and not (tmp_path / "out.srt").exists()


@pytest.mark.parametrize("command", ["translate", "transcribe"])
def test_expensive_command_rejects_input_collision_before_work(inputs, monkeypatch, command):
    source = inputs["cues" if command == "translate" else "audio"]
    def unexpected(*args, **kwargs):
        pytest.fail("expensive processing started despite an input collision")
    monkeypatch.setattr(cli, "translate_cues" if command == "translate" else "transcribe", unexpected)
    result = invoke([command, source, "-o", source])
    assert isinstance(result.exception, ValueError), result.exception


@pytest.mark.parametrize("command", ["transcribe", "build-cues", "translate", "render", "burn"])
@pytest.mark.parametrize("claim_kind", ["read_output", "write_input"])
def test_standalone_commands_respect_active_jobs(inputs, tmp_path, monkeypatch, command, claim_kind):
    dest = tmp_path / "output"
    dest.write_bytes(b"old output")
    args = {
        "transcribe": ["transcribe", inputs["audio"], "-o", dest],
        "build-cues": ["build-cues", inputs["transcript"], inputs["silences"], "-o", dest],
        "translate": ["translate", inputs["cues"], "-o", dest],
        "render": ["render", inputs["cues"], "-o", dest],
        "burn": ["burn", inputs["audio"], inputs["cues"], "-o", dest],
    }[command]
    def unexpected(*args, **kwargs):
        pytest.fail("command processing started while another task held its files")
    entry = {"transcribe": "transcribe", "build-cues": "load_transcript", "translate": "load_cues_json",
             "render": "load_cues_json", "burn": "burn_subtitles"}[command]
    monkeypatch.setattr(cli, entry, unexpected)
    reads = [dest] if claim_kind == "read_output" else []
    writes = [Path(args[1])] if claim_kind == "write_input" else []
    with claim_resources(reads=reads, writes=writes):
        result = invoke(args)
    assert isinstance(result.exception, RuntimeError), result.exception
    assert dest.read_bytes() == b"old output"


def test_transcribe_claims_external_log(inputs, tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("transcribe started while the log was in use")
    monkeypatch.setattr(cli, "transcribe", unexpected)
    with claim_resources(reads=[tmp_path / "whisper.log"], writes=[]):
        result = invoke(["transcribe", inputs["audio"], "-o", tmp_path / "out.json"])
    assert isinstance(result.exception, RuntimeError), result.exception


def test_noncolliding_commands_still_publish(inputs, tmp_path, monkeypatch):
    cues = tmp_path / "built.json"
    result = invoke(["build-cues", inputs["transcript"], inputs["silences"], "-o", cues])
    assert result.exit_code == 0, result.exception
    monkeypatch.setattr(cli, "translate_cues", lambda items, **kw: (items, SimpleNamespace(api_calls=0), []))
    translated = tmp_path / "translated.json"
    result = invoke(["translate", cues, "-o", translated])
    assert result.exit_code == 0, result.exception
    result = invoke(["render", translated, "-o", tmp_path / "out.ass"])
    assert result.exit_code == 0, result.exception
    assert (tmp_path / "out.srt").is_file() and (tmp_path / "out.ass").is_file()
