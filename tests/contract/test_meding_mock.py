from unittest.mock import MagicMock

from bilingual_sub.adapters.meding import MEDING_BASE_URL
from bilingual_sub.core.translate import translate_cues
from bilingual_sub.models import Cue


def test_meding_base_url_fixed():
    assert MEDING_BASE_URL == "https://api.meding.site"


def test_translate_cues_with_mock_client():
    mock = MagicMock()
    mock.translate_batch.return_value = ["Hello everyone."]

    cues = [Cue(1.0, 2.0, "大家好")]
    out, stats, missing = translate_cues(cues, client=mock, cache_enabled=False, api_key="dummy")
    assert out[0].en == "Hello everyone."
    assert not missing
    assert stats.api_calls == 1


def test_translate_missing_on_failure():
    mock = MagicMock()
    mock.translate_batch.side_effect = Exception("fail")

    from bilingual_sub.adapters.meding import MedingError

    mock.translate_batch.side_effect = MedingError("fail")
    cues = [Cue(1.0, 2.0, "测试")]
    out, _, missing = translate_cues(cues, client=mock, cache_enabled=False, api_key="x")
    assert missing
