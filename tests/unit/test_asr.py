from bilingual_sub.core.asr import load_transcript, probe_whisper, transcribe


def test_asr_facade_exports():
    assert callable(transcribe)
    assert callable(load_transcript)
    assert callable(probe_whisper)
