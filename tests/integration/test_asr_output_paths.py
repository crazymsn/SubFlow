import sys
from pathlib import Path

import pytest

from bilingual_sub.adapters import whisper_backend as wb
from bilingual_sub.adapters import whisperx_backend as wx


@pytest.mark.parametrize("backend", ["whisper", "whisperx"])
@pytest.mark.parametrize("collision", ["audio_result", "audio_log", "result_log", "script_result", "script_log", "python_result"])
def test_asr_worker_rejects_colliding_paths_before_launch(tmp_path, monkeypatch, backend, collision):
    wav, out = tmp_path / "audio.wav", tmp_path / "out.json"
    script, python = tmp_path / "worker.py", tmp_path / "python"
    for path in (wav, script, python):
        path.write_bytes(b"protected input")
    log = tmp_path / f"{backend}.log"
    if collision == "audio_result":
        out = wav
    elif collision == "audio_log":
        log.hardlink_to(wav)
    elif collision == "result_log":
        out = log
    elif collision == "script_result":
        out = script
    elif collision == "script_log":
        log.hardlink_to(script)
    else:
        out = python
    def unexpected(*args, **kwargs):
        pytest.fail("worker started with a conflicting output")
    monkeypatch.setattr(wb, "owned_process", unexpected)
    with pytest.raises(ValueError):
        wb.run_asr_worker(python, script, wav, model_name="tiny", language="zh", device="cpu", out_json=out, backend=backend)
    for path in (wav, script, python):
        assert path.read_bytes() == b"protected input"


@pytest.mark.parametrize("backend", ["whisper", "whisperx"])
def test_public_asr_rejects_output_alias_before_preparation(tmp_path, monkeypatch, backend):
    wav, out = tmp_path / "audio.wav", tmp_path / "out.json"
    wav.write_bytes(b"audio")
    out.hardlink_to(wav)
    def unexpected(*args, **kwargs):
        pytest.fail("ASR preparation started for colliding paths")
    if backend == "whisper":
        monkeypatch.setattr(wb, "_explicit_whisper_python", unexpected)
    else:
        monkeypatch.setattr(wx, "find_whisperx_python", unexpected)
    with pytest.raises(ValueError):
        if backend == "whisper":
            wb.transcribe(wav, out_json=out)
        else:
            wx.WhisperXBackend().transcribe(wav, model_name="tiny", language="zh", device="cpu", out_json=out)


def test_real_asr_worker_preserves_input_and_publishes_separate_files(tmp_path):
    wav, out, script = tmp_path / "audio.wav", tmp_path / "out.json", tmp_path / "worker.py"
    wav.write_bytes(b"source fixture")
    script.write_text('import json,sys\nfrom pathlib import Path\np=Path(sys.argv[sys.argv.index("--out")+1])\np.write_text(json.dumps({"language":"zh","segments":[{"start":0,"end":1,"text":"hello"}]}))\nprint("worker finished")\n')
    result = wb.run_asr_worker(Path(sys.executable), script, wav, model_name="tiny", language="zh", device="cpu", out_json=out, backend="whisper")
    assert result["segments"][0]["text"] == "hello"
    assert wav.read_bytes() == b"source fixture"
    assert out.is_file() and "worker finished" in (tmp_path / "whisper.log").read_text()
