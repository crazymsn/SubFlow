import io
import json
import wave
from pathlib import Path

import pytest

from bilingual_sub.adapters.tts.base import TtsRequest, TtsUnavailable, select_tts
from bilingual_sub.adapters.tts.gptsovits import (
    DEFAULT_ENDPOINT,
    GptSovitsTts,
    to_sovits_lang,
    tts_job_fingerprint,
)
from bilingual_sub.adapters.tts.gptsovits_runtime import probe_endpoint
from bilingual_sub.core.voice_preview import preview_sample, synth_voice_preview


def _pcm_wav(frames: int = 320) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * frames)
    return buf.getvalue()


def test_windows_build_bundles_sovits_runtime_by_default():
    script = Path(__file__).resolve().parents[2] / "scripts" / "build-windows.ps1"
    text = script.read_text(encoding="utf-8")
    assert "bundle-gptsovits.py" in text
    assert 'if ($SourceOnly)' in text
    assert 'throw "GPT-SoVITS bundling failed"' in text


def test_bundled_src_sees_vendored_api():
    from bilingual_sub.adapters.tts.gptsovits_runtime import bundled_src, discover_home

    home = bundled_src() or discover_home()
    assert home is not None
    assert (home / "api_v2.py").is_file()


def test_should_autostart_is_off_under_pytest():
    from bilingual_sub.adapters.tts.gptsovits_runtime import should_autostart

    assert should_autostart() is False


def test_ensure_running_checks_endpoint_under_pytest(monkeypatch):
    from bilingual_sub.adapters.tts import gptsovits_runtime as rt

    calls = []
    monkeypatch.setattr(rt, "probe_endpoint", lambda url: calls.append(url) or True)
    assert rt.ensure_running("http://127.0.0.1:9880", wait_sec=1) == "ready"
    assert calls == ["http://127.0.0.1:9880"]


def test_extract_ref_rejects_missing_video(tmp_path):
    from bilingual_sub.adapters.tts.gptsovits_runtime import extract_ref_audio

    dest = tmp_path / "ref.wav"
    from bilingual_sub.adapters.ffmpeg import FfmpegError
    with pytest.raises(FfmpegError):
        extract_ref_audio(tmp_path / "missing.mp4", dest)
    assert not dest.exists()


def test_error_detail_surfaces_upstream_exception():
    from bilingual_sub.adapters.tts.gptsovits import _error_detail

    class FakeResp:
        status_code = 400
        text = '{"message":"tts failed","Exception":"No module named \'onnxruntime\'"}'
        headers = {"content-type": "application/json"}

        def json(self):
            return {"message": "tts failed", "Exception": "No module named 'onnxruntime'"}

    assert "onnxruntime" in _error_detail(FakeResp())


def test_to_sovits_lang_maps_subflow_codes():
    assert to_sovits_lang("zh") == "zh"
    assert to_sovits_lang("zh-Hans") == "zh"
    assert to_sovits_lang("zh-Hant") == "zh"
    assert to_sovits_lang("en") == "en"
    assert to_sovits_lang("ja") == "ja"
    assert to_sovits_lang("ko") == "ko"
    assert to_sovits_lang("") == "zh"
    with pytest.raises(TtsUnavailable, match="不支持配音语种"):
        to_sovits_lang("es")
    with pytest.raises(TtsUnavailable, match="不支持配音语种"):
        to_sovits_lang("fr")


def test_select_tts_gptsovits_keeps_ref(tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF....WAVE")
    tts = select_tts(
        "gptsovits",
        endpoint="http://127.0.0.1:19880",
        ref_audio=str(ref),
        prompt_text="你好",
        prompt_lang="zh",
    )
    assert isinstance(tts, GptSovitsTts)
    assert isinstance(select_tts("openai"), GptSovitsTts)
    assert isinstance(select_tts("azure"), GptSovitsTts)
    assert tts.endpoint == "http://127.0.0.1:19880"
    assert tts.ref_audio == str(ref)
    assert tts.prompt_text == "你好"


def test_synth_posts_official_payload(tmp_path, monkeypatch):
    ref = tmp_path / "speaker.wav"
    ref.write_bytes(_pcm_wav())
    dest = tmp_path / "out.wav"
    seen: list[dict] = []
    audio = _pcm_wav(640)

    class FakeResp:
        status_code = 200
        content = audio
        headers = {"content-type": "audio/wav"}
        text = ""

    async def fake_post_audio(url, payload, control=None):
        seen.append({"url": url, "json": payload})
        return FakeResp()

    monkeypatch.setattr("bilingual_sub.adapters.tts.gptsovits._post_audio", fake_post_audio)
    tts = GptSovitsTts(
        "http://127.0.0.1:9880",
        ref_audio=str(ref),
        prompt_text="我是参考句。",
        prompt_lang="zh-Hans",
    )
    path = tts.synth(TtsRequest(text="Hello there.", lang="en", voice="", dest=dest))
    assert path == dest
    assert dest.read_bytes().startswith(b"RIFF")
    payload = seen[0]["json"]
    assert seen[0]["url"] == "http://127.0.0.1:9880/tts"
    assert payload["text"] == "Hello there."
    assert payload["text_lang"] == "en"
    assert payload["prompt_lang"] == "zh"
    assert payload["prompt_text"] == "我是参考句。"
    assert payload["ref_audio_path"] == str(ref.resolve())
    assert payload["streaming_mode"] is False
    assert payload["media_type"] == "wav"


def test_synth_blank_prompt_lang_uses_auto_not_target(tmp_path, monkeypatch):
    ref = tmp_path / "speaker.wav"
    ref.write_bytes(_pcm_wav())
    dest = tmp_path / "out.wav"
    seen: list[dict] = []

    class FakeResp:
        status_code = 200
        content = _pcm_wav(640)
        headers = {"content-type": "audio/wav"}
        text = ""

    async def fake_post_audio(url, payload, control=None):
        seen.append(payload)
        return FakeResp()

    monkeypatch.setattr("bilingual_sub.adapters.tts.gptsovits._post_audio", fake_post_audio)
    tts = GptSovitsTts("http://127.0.0.1:9880", ref_audio=str(ref), prompt_text="", prompt_lang="")
    tts.synth(TtsRequest(text="Hello.", lang="en", voice="", dest=dest))
    assert seen[0]["text_lang"] == "en"
    assert seen[0]["prompt_lang"] == "auto"


def test_synth_requires_ref_audio(tmp_path):
    dest = tmp_path / "out.wav"
    tts = GptSovitsTts("http://127.0.0.1:9880")
    with pytest.raises(TtsUnavailable, match="参考音频"):
        tts.synth(TtsRequest(text="hi", lang="en", voice="", dest=dest))


def test_synth_json_error(tmp_path, monkeypatch):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF....WAVE")
    dest = tmp_path / "out.wav"

    class FakeResp:
        status_code = 400
        content = b'{"message":"ref_audio_path is required"}'
        headers = {"content-type": "application/json"}
        text = '{"message":"ref_audio_path is required"}'

        def json(self):
            return json.loads(self.text)

    async def fake_post_audio(*_a, **_k):
        return FakeResp()

    monkeypatch.setattr(
        "bilingual_sub.adapters.tts.gptsovits._post_audio",
        fake_post_audio,
    )
    tts = GptSovitsTts("http://127.0.0.1:9880", ref_audio=str(ref))
    with pytest.raises(TtsUnavailable, match="ref_audio_path is required"):
        tts.synth(TtsRequest(text="hi", lang="zh", voice="", dest=dest))


def test_probe_hits_docs(monkeypatch):
    seen: list[str] = []

    class FakeResp:
        status_code = 200

        def json(self):
            return {
                "paths": {"/tts": {"post": {}}},
                "components": {
                    "schemas": {
                        "TTS_Request": {
                            "properties": {
                                "text": {},
                                "text_lang": {},
                                "ref_audio_path": {},
                                "prompt_lang": {},
                            }
                        }
                    }
                },
            }

    def fake_get(url, timeout=None, trust_env=False):
        seen.append(url)
        return FakeResp()

    monkeypatch.setattr("bilingual_sub.adapters.tts.gptsovits_runtime.httpx.get", fake_get)
    assert probe_endpoint(DEFAULT_ENDPOINT) is True
    assert seen[0].endswith("/openapi.json")


def test_tts_job_fingerprint_changes_with_ref():
    a = tts_job_fingerprint("gptsovits", endpoint="http://127.0.0.1:9880", ref_audio="a.wav")
    b = tts_job_fingerprint("gptsovits", endpoint="http://127.0.0.1:9880", ref_audio="b.wav")
    assert a != b
    assert tts_job_fingerprint("none") == "none"


def test_voice_preview_gptsovits_passes_ref(tmp_path, monkeypatch, mock_sovits_runtime):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF....WAVE")
    dest = tmp_path / "preview.wav"
    seen: list = []

    class FakeTts:
        def synth(self, req, control=None):
            seen.append(req)
            req.dest.write_bytes(_pcm_wav())
            return req.dest

    def fake_select(provider, **kwargs):
        assert provider == "gptsovits"
        assert kwargs["ref_audio"] == str(ref)
        assert kwargs["prompt_text"] == "你好"
        return FakeTts()

    monkeypatch.setattr("bilingual_sub.core.voice_preview.select_tts", fake_select)
    path = synth_voice_preview(
        provider="gptsovits",
        voice="",
        lang="en",
        endpoint="http://127.0.0.1:9880",
        dest=dest,
        ref_audio=str(ref),
        prompt_text="你好",
    )
    assert path == dest
    assert seen[0].text == preview_sample("en")
    assert seen[0].lang == "en"


def test_missing_pretrained_reports_empty_home(tmp_path: Path, monkeypatch):
    from bilingual_sub.adapters.tts.gptsovits_runtime import diagnose_runtime, missing_pretrained
    monkeypatch.setattr("bilingual_sub.adapters.tts.gptsovits_runtime._python_candidates", lambda *a: [])

    home = tmp_path / "GPT-SoVITS"
    home.mkdir()
    (home / "api_v2.py").write_text("# stub\n", encoding="utf-8")
    missing = missing_pretrained(home)
    assert missing
    assert any("pretrained_models" in item for item in missing)
    detail = diagnose_runtime(home)
    assert detail
    assert "权重" in detail


def test_bundled_src_has_api():
    from bilingual_sub.adapters.tts.gptsovits_runtime import bundled_src

    home = bundled_src()
    assert home is not None
    assert (home / "api_v2.py").is_file()


def test_ensure_running_raises_when_child_dies(monkeypatch):
    from bilingual_sub.adapters.tts import gptsovits_runtime as rt
    from bilingual_sub.adapters.tts.base import TtsUnavailable

    monkeypatch.setenv("SUBFLOW_SOVITS_LIVE", "1")
    rt.reset_boot_state()

    class Dead:
        returncode = 1

        def poll(self):
            return 1

    monkeypatch.setattr(rt, "probe_endpoint", lambda *a, **k: False)
    monkeypatch.setattr(rt, "diagnose_runtime", lambda *a, **k: None)
    monkeypatch.setattr(rt, "missing_pretrained", lambda *a, **k: [])
    monkeypatch.setattr(rt, "start_server", lambda *a, **k: Dead())
    monkeypatch.setattr(rt, "_log_tail", lambda limit=30: "ModuleNotFoundError: fastapi")
    with pytest.raises(TtsUnavailable, match="进程已退出"):
        rt.ensure_running("http://127.0.0.1:19880", wait_sec=5)
    rt.reset_boot_state()


def test_ensure_running_reuses_alive_child(monkeypatch):
    from bilingual_sub.adapters.tts import gptsovits_runtime as rt

    monkeypatch.setenv("SUBFLOW_SOVITS_LIVE", "1")
    rt.reset_boot_state()
    started = {"n": 0}

    class Alive:
        def poll(self):
            return None

    def start(*_a, **_k):
        started["n"] += 1
        return Alive()

    probes = {"n": 0}

    def probe(*_a, **_k):
        probes["n"] += 1
        return started["n"] > 0 and probes["n"] > 1

    monkeypatch.setattr(rt, "probe_endpoint", probe)
    monkeypatch.setattr(rt, "diagnose_runtime", lambda *a, **k: None)
    monkeypatch.setattr(rt, "missing_pretrained", lambda *a, **k: [])
    monkeypatch.setattr(rt, "start_server", start)
    assert rt.ensure_running("http://127.0.0.1:19880", wait_sec=5) == "started"
    assert rt.ensure_running("http://127.0.0.1:19880", wait_sec=5) == "ready"
    assert started["n"] == 1
    rt.reset_boot_state()


def test_python_has_sovits_deps_false_on_missing_binary():
    from bilingual_sub.adapters.tts.gptsovits_runtime import _IMPORT_PROBE, python_has_sovits_deps

    assert "soundfile" in _IMPORT_PROBE
    assert "torchaudio" in _IMPORT_PROBE
    assert "onnxruntime" in _IMPORT_PROBE
    assert python_has_sovits_deps([]) is False
    assert python_has_sovits_deps(["definitely-not-a-python-binary-xyz"]) is False
