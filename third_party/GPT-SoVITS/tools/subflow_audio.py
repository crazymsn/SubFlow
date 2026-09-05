"""Explicit normalized-waveform to signed little-endian PCM conversion."""
from numbers import Integral

import numpy as np


class InvalidAudioError(ValueError):
    pass


def validate_sample_rate(rate):
    if isinstance(rate, bool) or not isinstance(rate, Integral) or rate <= 0:
        raise InvalidAudioError("Audio sample rate must be a positive integer")
    return int(rate)


def float_to_pcm16(audio):
    values = np.asarray(audio)
    if values.ndim != 1 or not values.size or values.dtype.kind != "f":
        raise InvalidAudioError("Expected a nonempty mono floating-point waveform")
    if not np.isfinite(values).all():
        raise InvalidAudioError("Audio contains NaN or infinite samples")
    # Promote float16 before multiplication, and never normalize caller memory.
    values = values.astype(np.result_type(values.dtype, np.float32), copy=True)
    peak = np.abs(values).max()
    if peak > 1:
        values /= peak
    # +32768 is outside int16; saturate before casting to avoid sign reversal.
    return np.clip(np.rint(values * 32768), -32768, 32767).astype("<i2")
