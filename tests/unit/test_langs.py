from bilingual_sub.core.langs import (
    SINGLE_SUB_MODES,
    SOURCE_LANGS,
    SUB_LANGS,
    UI_LOCALES,
    coerce_requested_tts,
    convert_han,
    display_name,
    drop_target_if_unneeded,
    effective_target_lang,
    effective_tts_provider,
    has_distinct_target_line,
    is_valid_subtitle_mode,
    job_needs_dub,
    job_needs_translation,
    job_translation_langs,
    output_stem_suffix,
    prompt_name,
    screen_line,
    should_dub,
    spoken_translation_needed,
    token_required_for_job,
    translation_needed,
    wants_spoken_target,
    whisper_language,
)


def test_ui_locales_seven():
    codes = [c for c, _ in UI_LOCALES]
    assert codes == ["zh-Hans", "zh-Hant", "en", "ja", "es", "ru", "fr", "de"]


def test_whisper_maps_hant_to_zh():
    assert whisper_language("zh-Hant") == "zh"
    assert whisper_language("ja") == "ja"
    assert whisper_language("auto") == "auto"


def test_source_has_auto():
    assert SOURCE_LANGS[0][0] == "auto"
    assert "en" in {c for c, _ in SUB_LANGS}


def test_prompt_and_display():
    assert "Chinese" in prompt_name("zh")
    assert display_name("zh") == "简体中文"


def test_screen_han_follows_target_then_style():
    from bilingual_sub.core.langs import apply_han_to_cues, screen_han_lang
    from bilingual_sub.models import Cue

    assert screen_han_lang("zh", "zh", "bilingual") == "zh"
    assert screen_han_lang("zh", "zh-Hant", "bilingual") == "zh-Hant"
    assert screen_han_lang("en", "zh", "bilingual") == "zh"
    assert screen_han_lang("zh-Hant", "zh", "bilingual") == "zh"
    assert screen_han_lang("zh-Hant", "en", "bilingual") == "zh-Hant"
    assert screen_han_lang("zh", "en", "single:zh") == "zh"
    assert screen_han_lang("zh", "zh", "single:zh-Hant") == "zh-Hant"
    from bilingual_sub.core.langs import spoken_han_lang

    assert spoken_han_lang("zh-Hant") == "zh-Hant"
    assert spoken_han_lang("zh") == "zh"
    assert spoken_han_lang("en") is None
    assert spoken_han_lang("ja") is None
    assert spoken_han_lang("zh-Hant") != screen_han_lang("zh", "zh-Hant", "single:zh")
    cues = [Cue(0.0, 1.0, "歡迎回來", "Welcome back")]
    apply_han_to_cues(cues, "zh")
    assert cues[0].zh == "欢迎回来"
    assert cues[0].en == "Welcome back"
    assert spoken_han_lang("ja") is None
    assert spoken_han_lang("en") is None


def test_convert_han_t2s_for_simplified():
    text = convert_han("歡迎回來", "zh")
    assert text == "欢迎回来"
    assert convert_han("简体", "zh-Hant") in {"简体", "簡體"}


def test_single_subtitle_modes():
    assert [code for code, _label in SINGLE_SUB_MODES] == [
        "single:en",
        "single:zh",
        "single:zh-Hant",
        "single:ja",
        "single:es",
        "single:ru",
        "single:fr",
        "single:de",
    ]
    assert is_valid_subtitle_mode("bilingual")
    assert is_valid_subtitle_mode("enzh")
    assert is_valid_subtitle_mode("single:ja")
    assert is_valid_subtitle_mode("single:de")
    assert not is_valid_subtitle_mode("single:it")
    assert effective_target_lang("zh", "en", "single:ja") == "en"
    assert effective_target_lang("zh", "en", "bilingual") == "en"
    assert translation_needed("zh", "en", "bilingual") is True
    assert translation_needed("zh", "zh", "bilingual") is True
    assert translation_needed("zh", "zh", "enzh") is True
    assert translation_needed("zh-Hant", "zh", "bilingual") is True
    assert translation_needed("zh", "zh", "single:zh") is False
    assert translation_needed("zh", "ja", "single:ja") is True
    assert translation_needed("auto", "zh", "single:zh") is False
    assert job_needs_translation("zh", "en", "single:zh") is True
    assert job_needs_translation("zh", "zh", "single:zh") is False
    assert spoken_translation_needed("zh", "en") is True
    assert spoken_translation_needed("zh", "zh") is False
    assert wants_spoken_target("zh", "en") is True
    assert wants_spoken_target("zh", "zh") is False
    assert wants_spoken_target("zh", "zh-Hant") is False
    assert wants_spoken_target("auto", "en") is True
    assert wants_spoken_target("auto", "zh") is False
    assert wants_spoken_target("zh", "de") is True
    assert whisper_language("de") == "de"
    assert prompt_name("de") == "German"
    from bilingual_sub.core.langs import (
        assign_pair_fields,
        pair_cues_polluted,
        pair_display_texts,
        pair_translate_lang,
        spoken_family,
        spoken_line,
        text_family,
    )
    from bilingual_sub.models import Cue

    assert text_family("Hello everyone") == "en"
    assert text_family("大家好") == "zh"
    assert text_family("这是 API 接口") == "zh"
    assert text_family("今日は良い天気です") == "ja"
    assert text_family("안녕하세요") == "ko"
    assert spoken_family([Cue(0.0, 1.0, "今日は良い天気です")], "zh") == "ja"
    assert spoken_line(Cue(0.0, 1.0, "大家好", "今日は良い天気です"), "ja") == "今日は良い天気です"
    assert spoken_line(Cue(0.0, 1.0, "大家好", "Hello", spoken="今日は良い天気です"), "ja") == "今日は良い天気です"
    assert spoken_line(Cue(0.0, 1.0, "大家好", "Hello", spoken="Hola a todos"), "es") == "Hola a todos"
    assert screen_line(Cue(0.0, 1.0, "大家好", "Hello"), "single:zh") == "大家好"
    assert screen_line(Cue(0.0, 1.0, "大家好", "Hello"), "single:en") == "Hello"
    assert screen_line(Cue(0.0, 1.0, "大家好", "Hello", spoken="今日は良い天気です"), "single:ja") == "今日は良い天気です"
    assert job_translation_langs("ja", "zh", "single:en", enable_dub=True, tts_provider="gptsovits") == ["en", "zh"]
    assert job_translation_langs("zh", "ja", "bilingual") == ["en", "ja"]
    assert token_required_for_job("auto", "zh", "bilingual") is True
    assert token_required_for_job("auto", "zh", "single:zh") is False
    assert token_required_for_job("auto", "zh", "single:zh", enable_dub=True, tts_provider="gptsovits") is False
    assert token_required_for_job("zh", "zh", "single:zh", enable_dub=True, tts_provider="gptsovits") is False
    assert spoken_family([Cue(0.0, 1.0, "Hello everyone")], "zh") == "en"
    assert spoken_family([Cue(0.0, 1.0, "大家好")], "en") == "zh"
    assert pair_cues_polluted([Cue(0.0, 1.0, "Hello everyone", "Hello")]) is True
    assert pair_cues_polluted([Cue(0.0, 1.0, "大家好", "Hello")]) is False
    assert pair_display_texts(Cue(0.0, 1.0, "Hello everyone", "Hello")) == ("", "Hello everyone")
    assert pair_display_texts(Cue(0.0, 1.0, "大家好", "Hello")) == ("大家好", "Hello")

    assert pair_translate_lang("zh") == "en"
    assert pair_translate_lang("en") == "zh"
    leftover = [Cue(0.0, 1.0, "你好", "Hello")]
    assert has_distinct_target_line(leftover) is True
    drop_target_if_unneeded(leftover, "zh", "zh", "bilingual")
    assert leftover[0].en == "Hello"
    drop_target_if_unneeded(leftover, "zh", "zh", "single:zh")
    assert leftover[0].en is None
    dubbed = [Cue(0.0, 1.0, "你好", "Hello")]
    drop_target_if_unneeded(dubbed, "zh", "en", "single:zh")
    assert dubbed[0].en == "Hello"
    assert has_distinct_target_line(leftover) is False
    english_src = [Cue(0.0, 1.0, "Hello", "你好")]
    assign_pair_fields(english_src, "en")
    assert english_src[0].zh == "你好"
    assert english_src[0].en == "Hello"
    assert spoken_line(english_src[0], "en") == "Hello"
    assert spoken_line(english_src[0], "zh") == "你好"
    assert spoken_line(Cue(0.0, 1.0, "大家好", None), "en") == ""
    assert spoken_line(Cue(0.0, 1.0, "Hello everyone", None), "en") == "Hello everyone"
    assert spoken_line(Cue(0.0, 1.0, "Hello everyone", "大家好"), "en") == "Hello everyone"
    assert spoken_line(Cue(0.0, 1.0, "大家好", "大家好"), "en") == ""
    assert should_dub("zh", "zh", "en") is True
    assert should_dub("zh", "en", "en") is True
    assert should_dub("zh", "en", "zh") is True
    assert should_dub("zh", "zh", "zh") is False
    assert should_dub("en", "en", "en") is False
    assert should_dub("en", "en", "en", cues=[Cue(0.0, 1.0, "大家好")]) is True
    assert should_dub("en", "en", "en", cues=[Cue(0.0, 1.0, "Hello everyone")]) is False
    assert job_needs_dub("zh", "zh", "zh", enable_dub=True, tts_provider="openai") is False
    assert job_needs_dub("zh", "zh", "zh", enable_dub=True, tts_provider="gptsovits") is False
    assert job_needs_dub("zh", "zh", "zh", enable_dub=False, tts_provider="gptsovits") is False
    assert job_needs_dub("zh", "zh", "en", enable_dub=False, tts_provider="none") is True
    assert effective_tts_provider("zh", "zh", "en") == "gptsovits"
    assert effective_tts_provider("zh", "zh", "en", tts_provider="openai") == "gptsovits"
    assert effective_tts_provider("zh", "zh", "zh") == "none"
    assert effective_tts_provider("zh", "zh", "zh", enable_dub=True, tts_provider="gptsovits") == "none"
    assert effective_tts_provider("zh", "en", "zh") == "gptsovits"
    assert effective_tts_provider("zh", "zh", "zh", enable_dub=True, tts_provider="none") == "none"
    assert coerce_requested_tts("none", enable_dub=True) == "gptsovits"
    assert coerce_requested_tts("openai", enable_dub=False) == "gptsovits"
    assert coerce_requested_tts("none", enable_dub=False) == "none"
    assert (
        effective_tts_provider(
            "zh",
            "zh",
            "zh",
            enable_dub=True,
            tts_provider=coerce_requested_tts("none", enable_dub=True),
        )
        == "none"
    )
    assert output_stem_suffix("bilingual") == "-中英字幕"
    assert output_stem_suffix("enzh") == "-英中字幕"
    assert output_stem_suffix("single:en") == "-English"
    assert output_stem_suffix("netflix_single") == "-单行字幕"


def test_translate_pair_fills_japanese_source():
    from bilingual_sub.core.translate import TranslateStats, translate_pair_cues
    from bilingual_sub.models import Cue

    cues = [Cue(0.0, 1.0, "今日は良い天気です")]

    def fake(batch, *, source_lang, target_lang, **_k):
        out = []
        for cue in batch:
            text = "今天天气很好" if target_lang == "zh" else "The weather is nice today."
            out.append(Cue(cue.start, cue.end, cue.zh, text))
        return out, TranslateStats(), []

    out, _stats, _missing = translate_pair_cues(cues, translator=fake)
    assert out[0].zh == "今天天气很好"
    assert "weather" in (out[0].en or "").lower()


def test_fill_translated_languages_puts_third_lang_on_spoken():
    from bilingual_sub.core.translate import TranslateStats, fill_translated_languages
    from bilingual_sub.models import Cue

    cues = [Cue(0.0, 1.0, "大家好")]

    def fake(batch, *, source_lang, target_lang, **_k):
        text = "Hello" if target_lang == "en" else "今日は良い天気です"
        return [Cue(c.start, c.end, c.zh, text) for c in batch], TranslateStats(), []

    out, _stats, _missing = fill_translated_languages(
        cues, ["en", "ja"], translator=fake, source_lang="zh"
    )
    assert out[0].en == "Hello"
    assert out[0].spoken == "今日は良い天気です"
    assert out[0].zh == "大家好"


def test_english_translation_precedes_latin_source():
    from bilingual_sub.core.langs import spoken_line
    from bilingual_sub.models import Cue

    cue = Cue(0, 1, "Bonjour à tous", "Hello everyone")
    assert spoken_line(cue, "en") == "Hello everyone"
    assert screen_line(cue, "single:en") == "Hello everyone"


def test_pair_groups_scripts_and_keeps_originals_for_mutating_translator():
    from bilingual_sub.core.translate import TranslateStats, translate_pair_cues
    from bilingual_sub.models import Cue

    originals = {"ja": "こんにちは", "ru": "Добрый день"}
    calls = []
    def translate(batch, *, source_lang, target_lang):
        calls.append((source_lang, target_lang, batch[0].zh))
        batch[0].zh = "mutated source"
        batch[0].en = "你好" if target_lang == "zh" else "Hello"
        return batch, TranslateStats(), []
    cues = [Cue(i, i + 1, text) for i, text in enumerate(originals.values())]
    out, _, _ = translate_pair_cues(cues, translator=translate, source_lang="ja")
    assert len(calls) == 4
    assert all(text == originals[src] for src, _target, text in calls)
    assert all(c.zh == "你好" and c.en == "Hello" for c in out)


def test_missing_pair_translation_does_not_display_foreign_source_as_english():
    from bilingual_sub.core.translate import TranslateStats, translate_pair_cues
    from bilingual_sub.models import Cue

    def translate(batch, **kwargs):
        return batch, TranslateStats(), [c.zh for c in batch]
    out, _, missing = translate_pair_cues([Cue(0, 1, "Bonjour")], translator=translate, source_lang="fr")
    assert missing == ["Bonjour"] and not out[0].zh and not out[0].en
