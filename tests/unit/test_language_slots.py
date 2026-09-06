import pytest

from bilingual_sub.core.langs import screen_line, spoken_line
from bilingual_sub.core.translate import TranslateStats, fill_translated_languages
from bilingual_sub.models import Cue


@pytest.mark.parametrize("source,screen,voice,original", [
    ("zh", "fr", "ja", "大家好"),
    ("zh", "ja", "ko", "大家好"),
    ("en", "es", "ja", "Hello everyone"),
    ("fr", "fr", "ja", "Bonjour à tous"),
])
@pytest.mark.parametrize("reload", [False, True])
def test_independent_screen_and_voice_languages(source, screen, voice, original, reload):
    translations = {"fr": "Bonjour à tous", "ja": "こんにちは", "es": "Hola a todos", "ko": "안녕하세요"}
    def translate(batch, *, source_lang, target_lang):
        assert source_lang == source
        assert batch[0].zh == original
        return [Cue(0, 1, original, translations[target_lang])], TranslateStats(), []
    dests = ([screen] if screen != source else []) + [voice]
    cues, _, _ = fill_translated_languages([Cue(0, 1, original)], dests,
                                           source_lang=source, translator=translate)
    cue = Cue.from_dict(cues[0].to_dict()) if reload else cues[0]
    assert screen_line(cue, "single:" + screen) == (original if screen == source else translations[screen])
    assert spoken_line(cue, voice) == translations[voice]


def test_missing_english_translation_does_not_speak_french_original():
    def translate(batch, **kwargs):
        return batch, TranslateStats(), [batch[0].zh]
    cues, _, missing = fill_translated_languages([Cue(0, 1, "Bonjour à tous")], ["en"],
                                               source_lang="fr", translator=translate)
    assert missing
    assert spoken_line(cues[0], "en") == ""
    assert screen_line(cues[0], "single:en") == ""


@pytest.mark.parametrize("invalid", [None, [], "en", {"en": None}, {1: "Hello"}, {"": "Hello"}])
def test_language_texts_reject_invalid_cache_values(invalid):
    with pytest.raises(ValueError, match="language_texts"):
        Cue.from_dict({"start": 0, "end": 1, "zh": "你好", "language_texts": invalid})


def test_legacy_cue_json_remains_readable_and_maps_do_not_alias():
    legacy = Cue.from_dict({"start": 0, "end": 1, "zh": "你好", "en": "Hello"})
    assert spoken_line(legacy, "en") == "Hello"
    modern = Cue(0, 1, "你好", language_texts={"zh": "你好", "en": "Hello"})
    data = modern.to_dict()
    restored = Cue.from_dict(data)
    data["language_texts"]["en"] = "changed"
    assert spoken_line(modern, "en") == spoken_line(restored, "en") == "Hello"


def test_netflix_projection_keeps_only_display_language_after_reload():
    from bilingual_sub.core.netflix import fit_cues

    source = Cue(0, 4, "大家好", spoken="こんにちは", language_texts={
        "zh": "大家好", "ja": "こんにちは", "fr": "Bonjour à tous, bienvenue dans cette application."})
    fitted = [Cue.from_dict(c.to_dict()) for c in fit_cues([source], "fr")]
    assert all(set(c.language_texts) == {"fr"} for c in fitted)
    text = " ".join(screen_line(c, "single:fr") for c in fitted)
    assert "Bonjour" in text and "application" in text and "こんにちは" not in text


def test_han_conversion_updates_language_texts():
    from bilingual_sub.core.langs import apply_han_to_cues

    cue = Cue(0, 1, "欢迎", language_texts={"zh": "欢迎", "ja": "こんにちは"})
    apply_han_to_cues([cue], "zh-Hant")
    assert screen_line(cue, "single:zh-Hant") == "歡迎"
    assert spoken_line(cue, "ja") == "こんにちは"
