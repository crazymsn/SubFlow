from bilingual_sub.core.langs import (
    SINGLE_SUB_MODES,
    SOURCE_LANGS,
    SUB_LANGS,
    UI_LOCALES,
    convert_han,
    display_name,
    drop_target_if_unneeded,
    effective_target_lang,
    has_distinct_target_line,
    is_valid_subtitle_mode,
    output_stem_suffix,
    prompt_name,
    should_dub,
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
    cues = [Cue(0.0, 1.0, "歡迎回來", "Welcome back")]
    apply_han_to_cues(cues, "zh")
    assert cues[0].zh == "欢迎回来"
    assert cues[0].en == "Welcome back"


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
    assert has_distinct_target_line(leftover) is False
    english_src = [Cue(0.0, 1.0, "Hello", "你好")]
    assign_pair_fields(english_src, "en")
    assert english_src[0].zh == "你好"
    assert english_src[0].en == "Hello"
    assert spoken_line(english_src[0], "en") == "Hello"
    assert spoken_line(english_src[0], "zh") == "你好"
    assert spoken_line(Cue(0.0, 1.0, "大家好", None), "en") == ""
    assert spoken_line(Cue(0.0, 1.0, "Hello everyone", None), "en") == "Hello everyone"
    assert should_dub("zh", "zh", "en") is True
    assert should_dub("zh", "en", "en") is True
    assert should_dub("zh", "en", "zh") is True
    assert should_dub("zh", "zh", "zh") is False
    assert should_dub("en", "en", "en") is False
    assert output_stem_suffix("bilingual") == "-中英字幕"
    assert output_stem_suffix("enzh") == "-英中字幕"
    assert output_stem_suffix("single:en") == "-English"
    assert output_stem_suffix("netflix_single") == "-单行字幕"
