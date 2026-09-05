from bilingual_sub.i18n import available_locales, set_locale, tr


REQUIRED = (
    "url_ph",
    "download",
    "api",
    "models",
    "ui_lang",
    "source",
    "target",
    "mode_bi",
    "mode_enzh",
    "mode_nf",
    "asr",
    "engine",
    "engine_whisperx",
    "burn",
    "sub_color",
    "zh_color",
    "en_color",
    "refine",
    "dub",
    "tts_provider",
    "tts_voice",
    "tts_voice_alloy",
    "tts_preview",
    "tts_previewing",
    "tts_preview_ok",
    "tts_preview_fail",
    "tts_endpoint",
    "out",
    "browse",
    "start",
    "pause",
    "resume",
    "stop",
    "open",
    "waiting",
    "source_file",
    "source_url",
    "theme_light",
    "theme_dark",
    "more",
    "asr_help",
    "tts_help",
    "save_token",
    "clear_token",
    "token_cleared",
    "api_portal",
    "github",
    "log_ph",
    "token_ph",
    "token_kept",
    "model_ph",
    "out_ph",
    "need_url",
    "need_video",
    "need_token",
    "need_model",
    "need_out",
    "select_video",
    "select_out",
    "fail",
    "starting",
)


def test_seven_locales():
    assert available_locales() == ["zh-Hans", "zh-Hant", "en", "ja", "es", "ru", "fr", "de"]


def test_default_matches_chinese_ui():
    set_locale("zh-Hans")
    assert tr("start") == "开始处理"
    assert tr("burn") == "烧录到视频"
    assert tr("browse") == "浏览"
    assert tr("transcribe") == "语音识别"
    assert tr("source") == "源语种"
    assert tr("target") == "目标语种"
    assert tr("mode") == "字幕样式"
    assert tr("mode_bi") == "中英字幕"
    assert tr("mode_enzh") == "英中字幕"


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
