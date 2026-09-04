from bilingual_sub.core.langs import (
    SOURCE_LANGS,
    SUB_LANGS,
    UI_LOCALES,
    convert_han,
    display_name,
    prompt_name,
    whisper_language,
)


def test_ui_locales_seven():
    codes = [c for c, _ in UI_LOCALES]
    assert codes == ["en", "zh-Hans", "zh-Hant", "ja", "es", "ru", "fr"]


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


def test_convert_han_passthrough_without_opencc():
    text = convert_han("简体", "zh-Hant")
    assert isinstance(text, str)
    assert text
