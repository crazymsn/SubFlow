import array
import math
import wave

import pytest

from bilingual_sub.core.audio_cache import pcm_duration
from bilingual_sub.core.dub import fit_clip


def test_short_speech_is_not_stretched_and_dense_speech_completes(tmp_path):
    raw = tmp_path / 'tone.wav'
    with wave.open(str(raw), 'wb') as w:
        w.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        w.writeframes(array.array('h', [int(4000*math.sin(2*math.pi*440*i/16000)) for i in range(16000)]).tobytes())
    out = tmp_path / 'fit.wav'
    fit_clip(raw, out, 3)
    assert pcm_duration(out) == pytest.approx(1, abs=.03)
    fit_clip(raw, out, 1 / 1.45)
    assert pcm_duration(out) == pytest.approx(1 / 1.45, abs=.03)
    fit_clip(raw, out, .9)
    assert pcm_duration(out) == pytest.approx(.9, abs=.03)
