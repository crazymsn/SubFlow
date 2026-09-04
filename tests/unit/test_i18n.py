from bilingual_sub.i18n import available_locales, set_locale, tr


REQUIRED = (
    "upload",
    "url_ph",
    "download",
    "api",
    "models",
    "ui_lang",
    "sub_lang",
    "source",
    "target",
    "mode_bi",
    "mode_nf",
    "asr",
    "engine",
    "engine_whisperx",
    "burn",
    "refine",
    "glossary",
    "glossary_gen",
    "dub",
    "tts_provider",
    "tts_voice",
    "tts_endpoint",
    "fallback_whisper",
    "out",
    "browse",
    "start",
    "pause",
    "resume",
    "stop",
    "open",
    "waiting",
)


def test_seven_locales():
    assert available_locales() == ["en", "zh-Hans", "zh-Hant", "ja", "es", "ru", "fr"]


def test_default_matches_chinese_ui():
    set_locale("zh-Hans")
    assert tr("start") == "开始处理"
    assert tr("burn") == "烧录到视频"
    assert tr("browse") == "浏览"
    assert tr("transcribe") == "语音识别"


def test_missing_key_falls_back_to_hans():
    set_locale("en")
    assert tr("start") == "Start"
    assert tr("__no_such_key__") == "__no_such_key__"
    set_locale("zh-Hans")


def test_all_locales_have_required_keys():
    for loc in available_locales():
        set_locale(loc)
        for key in REQUIRED:
            assert tr(key) != key, f"{loc} missing {key}"
    set_locale("zh-Hans")
