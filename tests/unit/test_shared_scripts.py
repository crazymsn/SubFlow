import pytest

from bilingual_sub.core.langs import should_dub, spoken_family, spoken_line
from bilingual_sub.core.translate import TranslateStats, translate_pair_cues
from bilingual_sub.models import Cue


@pytest.mark.parametrize("text,language", [("東京都交通局", "ja"), ("à", "fr"), ("Ö", "de")])
def test_shared_scripts_use_language_metadata_for_pair_translation(text, language):
    calls = []
    def translate(batch, *, source_lang, target_lang):
        calls.append((source_lang, target_lang, batch[0].zh))
        return [Cue(0, 1, batch[0].zh, "中文译文" if target_lang == "zh" else "English translation")], TranslateStats(), []
    out, _, missing = translate_pair_cues([Cue(0, 1, text)], source_lang=language, translator=translate)
    assert calls == [(language, "zh", text), (language, "en", text)]
    assert not missing
    assert spoken_line(out[0], "en") == "English translation"
    assert out[0].zh == "中文译文"


def test_japanese_kanji_to_chinese_requires_translation_and_dub():
    cues = [Cue(0, 1, "東京都交通局")]
    assert spoken_family(cues, "auto", asr_language="ja") == "ja"
    assert should_dub("auto", "ja", "zh", cues=cues)


def test_explicit_asr_language_overrides_declared_shared_script():
    cues = [Cue(0, 1, "東京都交通局")]
    assert spoken_family(cues, "zh", asr_language="ja") == "ja"
    assert spoken_family(cues, "ja", asr_language="zh") == "zh"
