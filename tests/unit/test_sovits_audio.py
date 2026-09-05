import importlib.util
import io
import wave
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture
def audio():
    path = Path(__file__).resolve().parents[2] / "third_party/GPT-SoVITS/tools/subflow_audio.py"
    spec = importlib.util.spec_from_file_location("subflow_audio_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("dtype", [np.float16, np.float32, np.float64])
def test_pcm_full_scale_is_monotonic_and_preserves_polarity(audio, dtype):
    values = np.linspace(-1, 1, 2049, dtype=dtype)
    before = values.copy()
    pcm = audio.float_to_pcm16(values)
    assert pcm[0] == -32768 and pcm[-1] == 32767 and pcm[1024] == 0
    assert np.all(np.diff(pcm.astype(np.int32)) >= 0)
    np.testing.assert_array_equal(values, before)
    assert pcm.dtype == np.dtype("<i2")


def test_loud_audio_normalizes_without_mutating_input(audio):
    values = np.array([-4, -2, 0, 2, 4], dtype=np.float32)
    assert audio.float_to_pcm16(values).tolist() == [-32768, -16384, 0, 16384, 32767]
    assert values.tolist() == [-4, -2, 0, 2, 4]


@pytest.mark.parametrize("values", [[], [float("nan")], [float("inf")], [float("-inf")], [[0.5]], 0.5, [1, 2]])
def test_invalid_model_audio_is_not_cast_into_apparent_pcm(audio, values):
    with pytest.raises(audio.InvalidAudioError):
        audio.float_to_pcm16(np.asarray(values))


@pytest.mark.parametrize("rate", [0, -1, True, 24000.5, None])
def test_invalid_sample_rate_is_rejected(audio, rate):
    with pytest.raises(audio.InvalidAudioError):
        audio.validate_sample_rate(rate)


def test_pcm_wav_round_trip_keeps_signed_samples(audio):
    pcm = audio.float_to_pcm16(np.array([-1., -0.5, 0., 0.5, 1.]))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setparams((1, 2, audio.validate_sample_rate(np.int64(24000)), 0, "NONE", "not compressed"))
        wav.writeframes(pcm.tobytes())
    with wave.open(io.BytesIO(buffer.getvalue()), "rb") as wav:
        assert wav.getframerate() == 24000
        assert np.frombuffer(wav.readframes(5), dtype="<i2").tolist() == pcm.tolist()
