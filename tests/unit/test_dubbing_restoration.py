import pytest

from bilingual_sub.adapters.tts.base import TtsUnavailable
from bilingual_sub.adapters.tts.gptsovits import GptSovitsTts
from bilingual_sub.core.voice_preview import synth_voice_preview
from bilingual_sub.gui.workers import VoicePreviewWorker


@pytest.mark.parametrize("custom_reference", [False, True])
def test_preview_transcript_belongs_only_to_explicit_reference(tmp_path, monkeypatch, pcm_wav, custom_reference):
    source, ref = tmp_path / "source.wav", tmp_path / "reference.wav"
    source.write_bytes(pcm_wav(4))
    ref.write_bytes(pcm_wav(4))
    monkeypatch.setattr("bilingual_sub.core.voice_preview.preview_cache_dir", lambda: tmp_path)
    monkeypatch.setattr("bilingual_sub.adapters.tts.gptsovits_runtime.ensure_ref_audio", lambda *a, **k: ref)
    received = []
    def synth(**kwargs):
        received.append(kwargs)
        return ref
    monkeypatch.setattr("bilingual_sub.core.voice_preview.synth_voice_preview", synth)
    worker = VoicePreviewWorker("gptsovits", "", "en", video=source,
        ref_audio=str(ref) if custom_reference else "", prompt_text="您好，请问有什么能帮您？",
        sample_text="Hello, how can I help you?")
    errors = []
    worker.fail.connect(errors.append)
    worker.run()
    assert not errors and len(received) == 1
    assert received[0]["prompt_text"] == (worker.prompt_text if custom_reference else "")
    assert received[0]["sample_text"] == worker.sample_text


def test_explicit_empty_transcript_cannot_inherit_environment(monkeypatch):
    monkeypatch.setenv("SUBFLOW_GPTSOVITS_PROMPT", "unrelated old transcript")
    assert GptSovitsTts(prompt_text="").prompt_text == ""
    assert GptSovitsTts().prompt_text == "unrelated old transcript"


def test_missing_reference_fails_before_starting_models(tmp_path, monkeypatch):
    monkeypatch.setattr("bilingual_sub.adapters.tts.routing.ensure_running",
                        lambda *a, **k: pytest.fail("Invalid reference must not trigger installation"))
    with pytest.raises(TtsUnavailable, match="参考音频不存在"):
        synth_voice_preview(provider="gptsovits", voice="", lang="en", ref_audio=str(tmp_path / "missing.wav"))


def test_custom_qwen_endpoint_is_used_for_preview(tmp_path, monkeypatch, pcm_wav):
    from bilingual_sub.adapters.tts import qwen_runtime
    from bilingual_sub.adapters.tts.qwen import QwenTts
    ref = tmp_path / "ref.wav"
    ref.write_bytes(pcm_wav(4))
    seen = []
    monkeypatch.setattr(qwen_runtime, "ensure_running", lambda endpoint, **k: seen.append(endpoint))
    monkeypatch.setattr(QwenTts, "synth", lambda self, req, **k: req.dest.write_bytes(pcm_wav()))
    endpoint = "http://127.0.0.1:19999"
    result = synth_voice_preview(provider="qwen3", voice="", lang="fr", endpoint=endpoint,
                                 ref_audio=str(ref), dest=tmp_path / "out.wav")
    assert result.is_file() and seen == [endpoint]
