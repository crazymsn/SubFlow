import threading
import time
from unittest.mock import patch

import pytest

from bilingual_sub.adapters.tts.base import TtsRequest
from bilingual_sub.adapters.tts.qwen import QwenTts
from bilingual_sub.adapters.tts.routing import engine_session, provider_endpoint, resolve_provider
from bilingual_sub.core.control import JobControl, JobStopped
from bilingual_sub.core.dub import dub_cues
from bilingual_sub.core.dub_progress import DubProgress
from bilingual_sub.gui.progress import should_log_stage, stage_text
from bilingual_sub.models import Cue, JobConfig
from bilingual_sub.pipeline import _resolved_tts_provider, _tts_endpoint


@pytest.mark.parametrize("lang", ["zh", "zh-Hant", "en", "ja", "es", "ru", "fr", "de"])
def test_all_ui_targets_route_to_a_capable_engine(lang):
    selected = resolve_provider("gptsovits", lang, "zh")
    assert selected == ("qwen3" if lang in {"es", "ru", "fr", "de"} else "gptsovits")
    if selected == "qwen3":
        assert QwenTts().language(lang) != "Auto"


def test_source_and_locale_variants_and_disabled_engine():
    assert resolve_provider("gptsovits", "en-US", "zh-Hant") == "gptsovits"
    assert resolve_provider("gptsovits", "en", "en") == "gptsovits"
    assert resolve_provider("gptsovits", "en", "fr-FR") == "qwen3"
    assert resolve_provider("azure", "de_DE", "zh") == "qwen3"
    assert resolve_provider("none", "es", "zh") == "none"
    assert QwenTts().language("zh_TW") == "Chinese"


@pytest.mark.parametrize("target", ["zh", "zh-Hant"])
def test_chinese_video_keeps_original_voice(tmp_path, target):
    config = JobConfig(input_video=tmp_path / "in.mp4", output_video=tmp_path / "out.mp4",
                       output_srt=tmp_path / "out.srt", work_dir=tmp_path / "work",
                       source_lang="zh", target_lang=target, enable_dub=True, tts_provider="gptsovits")
    assert _resolved_tts_provider(config, detected_spoken="zh") == "none"


def test_pipeline_uses_separate_multilingual_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBFLOW_QWEN_TTS_URL", "http://127.0.0.1:19881")
    config = JobConfig(input_video=tmp_path / "in.mp4", output_video=tmp_path / "out.mp4",
                       output_srt=tmp_path / "out.srt", work_dir=tmp_path / "work",
                       source_lang="zh", target_lang="es", enable_dub=True, tts_provider="gptsovits",
                       tts_endpoint="http://127.0.0.1:9880")
    assert _resolved_tts_provider(config, detected_spoken="zh") == "qwen3"
    assert _tts_endpoint(config, "zh") == "http://127.0.0.1:19881"
    assert config.tts_endpoint == "http://127.0.0.1:9880"


def test_progress_pulses_without_inventing_completed_work():
    events = []
    with DubProgress(lambda s, p: events.append((s, p)), interval=.01) as progress:
        progress.set("synth", 2, 5, .2)
        time.sleep(.05)
    size = len(events)
    time.sleep(.03)
    assert len(events) == size and size >= 2
    assert all(p == .2 and s.startswith("dub|synth|2|5|") for s, p in events)
    assert not any(t.name == "subflow-dub-progress" for t in threading.enumerate())
    assert "2/5" in stage_text("dub|synth|2|5|67")
    assert "01:07" in stage_text("dub|synth|2|5|67")
    assert "0/0" not in stage_text("dub|prepare|0|0|12")
    assert not should_log_stage("dub|synth|2|5|67", "dub|synth|2|5|66")
    assert should_log_stage("dub|synth|3|5|0", "dub|synth|2|5|67")


def test_pulse_cleanup_when_operation_stops():
    with pytest.raises(JobStopped), DubProgress(lambda s, p: None, interval=.01):
        raise JobStopped()
    assert not any(t.name == "subflow-dub-progress" for t in threading.enumerate())


def test_job_progress_counts_only_spoken_cues_and_cache_hits(tmp_path, pcm_wav):
    class Tts:
        name = "fake"
        calls = 0
        def synth(self, req, **kw):
            self.calls += 1
            req.dest.write_bytes(pcm_wav())
    provider = Tts()
    events = []
    cues = [Cue(0, 1, "", "Hello"), Cue(1, 2, "", ""), Cue(2, 3, "", "Goodbye")]
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video")
    def mix(video, clips, dest, *args, **kwargs):
        assert len(clips) == 2
        dest.write_bytes(b"mixed")
    with patch("bilingual_sub.core.dub.fit_clip", side_effect=lambda src, dst, *a, **k: dst.write_bytes(src.read_bytes())), \
         patch("bilingual_sub.core.dub.mix_timeline", side_effect=mix):
        for _ in range(2):
            events.clear()
            dub_cues(cues, video=video, work=tmp_path, output=tmp_path / "out.mp4", provider=provider,
                     lang="en", voice="", duration=3, on_progress=lambda s, p: events.append((s, p)))
            assert [s.split("|")[2] for s, p in events if "|synth|" in s] == ["1", "2"]
            assert events[-1] == ("dub|complete|2|2|0", 1)
            assert [p for s, p in events] == sorted(p for s, p in events)
    assert provider.calls == 2


def test_engine_lease_cannot_evict_an_active_job(monkeypatch):
    monkeypatch.setattr("bilingual_sub.adapters.tts.qwen_runtime.release_idle_servers", lambda: None)
    released = []
    monkeypatch.setattr("bilingual_sub.adapters.tts.gptsovits_runtime.release_idle_servers", lambda: released.append(True))
    ctl = JobControl()
    cancelled = []
    def competing():
        try:
            with engine_session("qwen3", ctl):
                pytest.fail("Must not acquire while GPT job holds the lease")
        except JobStopped:
            cancelled.append(True)
    with engine_session("gptsovits"):
        worker = threading.Thread(target=competing)
        worker.start()
        time.sleep(.03)
        ctl.stop()
        worker.join(1)
        assert cancelled and not released and not worker.is_alive()


def test_multilingual_payload_keeps_source_transcript(tmp_path, monkeypatch, pcm_wav):
    import httpx

    from bilingual_sub.adapters.tts import gptsovits

    ref = tmp_path / "ref.wav"
    ref.write_bytes(pcm_wav(4))
    seen = []
    async def post(url, payload, control):
        seen.append(payload)
        return httpx.Response(200, content=pcm_wav(), headers={"Content-Type": "audio/wav"})
    monkeypatch.setattr(gptsovits, "_post_audio", post)
    engine = QwenTts(ref_audio=ref, prompt_text="参考音频原文", prompt_lang="zh")
    engine.synth(TtsRequest("Bonjour.", "fr", "", tmp_path / "out.wav"))
    assert seen[0]["text_lang"] == "French" and seen[0]["prompt_lang"] == "Chinese"
    assert seen[0]["prompt_text"] == "参考音频原文"
    assert engine.endpoint == provider_endpoint("qwen3")
