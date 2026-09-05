from pathlib import Path

from bilingual_sub.core.voice_preview import preview_cache_path, preview_sample, synth_voice_preview


def test_preview_sample_follows_target_language():
    assert preview_sample("zh") == "你好，这是配音音色试听。"
    assert preview_sample("zh-Hans") == "你好，这是配音音色试听。"
    assert preview_sample("zh-Hant") == "你好，這是配音音色試聽。"
    assert preview_sample("en").startswith("Hello")
    assert "試聴" in preview_sample("ja")
    assert preview_sample("unknown-xx").startswith("Hello")


def test_preview_cache_is_wav():
    assert preview_cache_path("alloy", "en").suffix == ".wav"


def test_synth_voice_preview_uses_voice_and_sample(tmp_path, monkeypatch):
    seen: list = []

    class FakeTts:
        def synth(self, req, control=None):
            seen.append(req)
            req.dest.write_bytes(b"ID3fake")
            return req.dest

    monkeypatch.setattr("bilingual_sub.core.voice_preview.select_tts", lambda provider: FakeTts())
    dest = tmp_path / "nova-en.mp3"
    path = synth_voice_preview(provider="openai", voice="nova", lang="en", dest=dest)
    assert path == dest
    assert seen[0].voice == "nova"
    assert seen[0].lang == "en"
    assert seen[0].text == preview_sample("en")
    assert dest.read_bytes().startswith(b"ID3")


def test_synth_voice_preview_reuses_cache(tmp_path, monkeypatch):
    calls = {"n": 0}

    class FakeTts:
        def synth(self, req, control=None):
            calls["n"] += 1
            req.dest.write_bytes(b"cached-audio-bytes" * 8)
            return req.dest

    monkeypatch.setattr("bilingual_sub.core.voice_preview.select_tts", lambda provider: FakeTts())
    dest = tmp_path / "alloy-zh.mp3"
    first = synth_voice_preview(provider="openai", voice="alloy", lang="zh", dest=dest)
    second = synth_voice_preview(provider="openai", voice="alloy", lang="zh", dest=dest)
    assert first == second
    assert calls["n"] == 1


def test_preview_request_uses_target_not_subtitle_style():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.styles import app_qss
    from bilingual_sub.i18n import set_locale

    set_locale("zh-Hans")
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    win.mode_combo.setCurrentIndex(win.mode_combo.findData("single:en"))
    win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData("zh"))
    provider, voice, lang, endpoint = win._preview_request()
    assert provider == "openai"
    assert voice == "alloy"
    assert lang == "zh"
    assert endpoint == ""
    win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData("ja"))
    win.mode_combo.setCurrentIndex(win.mode_combo.findData("enzh"))
    _provider, _voice, lang, _endpoint = win._preview_request()
    assert lang == "ja"
    win.tts_voice_edit.setCurrentIndex(win.tts_voice_edit.findData("onyx"))
    _provider, voice, _lang, _endpoint = win._preview_request()
    assert voice == "onyx"
    win.close()
    _ = app


def test_preview_without_token_asks_for_key(monkeypatch):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.styles import app_qss
    from bilingual_sub.i18n import set_locale

    set_locale("zh-Hans")
    monkeypatch.setattr("bilingual_sub.gui.app.get_api_key", lambda: "")
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    win.more_btn.setChecked(True)
    win.dub_check.setChecked(True)
    app.processEvents()
    win.tts_preview_btn.click()
    app.processEvents()
    assert "令牌" in win.key_status.text()
    assert win._preview_worker is None or not win._preview_busy()
    win.close()
    _ = app


def test_preview_fail_keeps_token_error_separate():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.styles import app_qss
    from bilingual_sub.i18n import set_locale

    set_locale("zh-Hans")
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    win._on_preview_fail("当前令牌未开通语音模型（tts-1），无法试听或配音")
    assert "未开通语音模型" in win.key_status.text()
    assert win.key_status.text() != "请先填写并保存 API 令牌"
    win._on_preview_fail("请先保存 API 令牌")
    assert win.key_status.text() == "请先填写并保存 API 令牌"
    win.close()
    _ = app


def test_preview_click_starts_worker_with_current_voice(monkeypatch):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.styles import app_qss
    from bilingual_sub.i18n import set_locale

    set_locale("zh-Hans")
    monkeypatch.setattr("bilingual_sub.gui.app.get_api_key", lambda: "test-key")
    started: list = []

    class FakeWorker:
        def __init__(self, provider, voice, lang, endpoint=""):
            self.provider = provider
            self.voice = voice
            self.lang = lang
            self.endpoint = endpoint
            self.ok = _FakeSignal()
            self.fail = _FakeSignal()

        def start(self):
            started.append((self.provider, self.voice, self.lang, self.endpoint))

        def isRunning(self):
            return False

    class _FakeSignal:
        def connect(self, _cb):
            return None

        def disconnect(self):
            return None

    monkeypatch.setattr("bilingual_sub.gui.app.VoicePreviewWorker", FakeWorker)
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    win.more_btn.setChecked(True)
    win.dub_check.setChecked(True)
    win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData("en"))
    win.tts_voice_edit.setCurrentIndex(win.tts_voice_edit.findData("nova"))
    app.processEvents()
    win.tts_preview_btn.click()
    app.processEvents()
    assert started == [("openai", "nova", "en", "")]
    win.close()
    _ = app
