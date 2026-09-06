import pytest

from bilingual_sub.core import voice_preview as preview


def test_target_switch_updates_sample_without_changing_audio_transcript(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.i18n import set_locale

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.tts_combo.setCurrentIndex(win.tts_combo.findData('qwen3'))
    win.tts_prompt_edit.setText("这是参考音频的原句。")
    stopped = []
    monkeypatch.setattr(win._preview_player, "stop", lambda: stopped.append(True))
    for language in ("en", "zh-Hant", "ja", "es", "ru", "fr", "de", "zh"):
        index = win.target_lang_combo.findData(language)
        assert index >= 0
        win.target_lang_combo.setCurrentIndex(index)
        assert win.tts_sample_edit.text() == preview.preview_sample(language)
        request = win._preview_request()
        assert request.lang == language and request.sample_text == preview.preview_sample(language)
        assert request.prompt_text == "这是参考音频的原句。"
    assert stopped
    win.tts_sample_edit.setText("请朗读这一句。")
    set_locale("en")
    win.retranslateUi()
    assert win._preview_request().sample_text == "请朗读这一句。"
    win.close()
    app.processEvents()


def test_editing_sample_invalidates_cache_but_preserves_reference_prompt(tmp_path, monkeypatch, pcm_wav):
    seen, prompts = [], []
    class Tts:
        def synth(self, request, control=None):
            seen.append((request.lang, request.text))
            request.dest.write_bytes(pcm_wav())
    def select(provider, **kwargs):
        prompts.append(kwargs["prompt_text"])
        return Tts()
    monkeypatch.setattr(preview, "select_tts", select)
    args = dict(provider="gptsovits", voice="", lang="en", dest=tmp_path / "sample.wav",
                prompt_text="参考音频原句", prompt_lang="zh")
    for text in ("Welcome.", "Welcome.", "Good morning.", " "):
        preview.synth_voice_preview(**args, sample_text=text)
    assert seen == [("en", "Welcome."), ("en", "Good morning."), ("en", preview.preview_sample("en"))]
    assert all(text == "参考音频原句" for text in prompts)


def test_worker_forwards_sample_and_reference_text_separately(tmp_path, monkeypatch):
    from bilingual_sub.gui.workers import VoicePreviewWorker

    seen = []
    monkeypatch.setattr(preview, "synth_voice_preview", lambda **kwargs: seen.append(kwargs) or tmp_path / "sample.wav")
    worker = VoicePreviewWorker("gptsovits", "", "ja", ref_audio="reference.wav",
                                prompt_text="中文原句", prompt_lang="zh", sample_text=preview.preview_sample("ja"))
    worker.run()
    assert seen[0]["lang"] == "ja" and seen[0]["sample_text"] == preview.preview_sample("ja")
    assert seen[0]["prompt_text"] == "中文原句" and seen[0]["prompt_lang"] == "zh"


@pytest.mark.parametrize("lang", ["zh", "zh-Hant", "en", "ja", "es", "ru", "fr", "de"])
def test_all_targets_have_distinct_localized_greetings(lang):
    assert preview.preview_sample(lang) == preview.PREVIEW_SAMPLES[lang]
