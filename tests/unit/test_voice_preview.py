import pytest

from bilingual_sub.core.voice_preview import preview_cache_path, preview_sample, synth_voice_preview


def test_preview_sample_follows_target_language():
    assert preview_sample("zh") == "您好，请问有什么能帮您？"
    assert preview_sample("zh-Hans") == "您好，请问有什么能帮您？"
    assert preview_sample("zh-Hant") == "您好，請問有什麼能幫您？"
    assert preview_sample("en").startswith("Hello")
    assert "お手伝い" in preview_sample("ja")
    assert preview_sample("ZH_tw") == preview_sample("zh-Hant")
    assert preview_sample("unknown-xx").startswith("Hello")


def test_preview_cache_is_wav():
    assert preview_cache_path("alloy", "en").suffix == ".wav"


def test_synth_gptsovits_preview_waits_for_runtime(tmp_path, monkeypatch, pcm_wav):
    calls = {"boot": 0}

    class FakeTts:
        def synth(self, req, control=None):
            req.dest.write_bytes(pcm_wav())
            return req.dest

    monkeypatch.setattr(
        "bilingual_sub.adapters.tts.gptsovits_runtime.ensure_running",
        lambda *a, **k: calls.__setitem__("boot", calls["boot"] + 1) or "ready",
    )
    monkeypatch.setattr("bilingual_sub.core.voice_preview.select_tts", lambda provider, **_k: FakeTts())
    dest = tmp_path / "preview.wav"
    synth_voice_preview(provider="gptsovits", voice="", lang="zh", dest=dest)
    assert calls["boot"] == 1


def test_synth_voice_preview_uses_voice_and_sample(tmp_path, monkeypatch, pcm_wav):
    seen: list = []

    class FakeTts:
        def synth(self, req, control=None):
            seen.append(req)
            req.dest.write_bytes(pcm_wav())
            return req.dest

    monkeypatch.setattr("bilingual_sub.core.voice_preview.select_tts", lambda provider, **_k: FakeTts())
    dest = tmp_path / "nova-en.wav"
    path = synth_voice_preview(provider="openai", voice="nova", lang="en", dest=dest)
    assert path == dest
    assert seen[0].voice == "nova"
    assert seen[0].lang == "en"
    assert seen[0].text == preview_sample("en")
    assert dest.read_bytes() == pcm_wav()


def test_synth_voice_preview_reuses_cache(tmp_path, monkeypatch, pcm_wav):
    calls = {"n": 0}

    class FakeTts:
        def synth(self, req, control=None):
            calls["n"] += 1
            req.dest.write_bytes(pcm_wav())
            return req.dest

    monkeypatch.setattr("bilingual_sub.core.voice_preview.select_tts", lambda provider, **_k: FakeTts())
    dest = tmp_path / "alloy-zh.wav"
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
    req = win._preview_request()
    assert req.provider == "qwen3-native"
    assert req.voice == ""
    assert req.lang == "zh"
    assert req.prompt_lang == "zh"
    win.source_lang_combo.setCurrentIndex(win.source_lang_combo.findData("zh"))
    win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData("en"))
    req = win._preview_request()
    assert req.lang == "en"
    assert req.prompt_lang == "zh"
    win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData("ja"))
    win.mode_combo.setCurrentIndex(win.mode_combo.findData("enzh"))
    req = win._preview_request()
    assert req.lang == "ja"
    win.close()
    _ = app


@pytest.mark.parametrize("field", ["endpoint", "ref_audio", "prompt_text", "prompt_lang", "sample_text", "video"])
def test_ready_preview_from_stale_settings_is_not_played(tmp_path, monkeypatch, field):
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.workers import VoicePreviewWorker
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    req = win._preview_request()
    args = {key: getattr(req, key) for key in
            ("provider", "voice", "lang", "endpoint", "ref_audio", "prompt_text", "prompt_lang", "sample_text")}
    if field == "video":
        win.tts_ref_edit.clear()
        args["ref_audio"] = ""
        args["video"] = tmp_path / "old.mp4"
        win._video = tmp_path / "new.mp4"
    else:
        args[field] += "different"
    worker = VoicePreviewWorker(**args)
    win._preview_worker = worker
    worker.ok.connect(win._on_preview_ready)
    worker.fail.connect(win._on_preview_fail)
    monkeypatch.setattr(win, "sender", lambda: worker)
    monkeypatch.setattr(win._preview_player, "play", lambda _: pytest.fail("stale preview must not play"))
    win._on_preview_ready(str(tmp_path / "old.wav"))
    assert not win._preview_player.is_active()
    win.close()
    app.processEvents()


def test_late_worker_error_does_not_replace_current_status(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.workers import VoicePreviewWorker
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    old = VoicePreviewWorker("gptsovits", "", "en")
    win._preview_worker = VoicePreviewWorker("gptsovits", "", "zh")
    win._preview_worker.ok.connect(win._on_preview_ready)
    win._preview_worker.fail.connect(win._on_preview_fail)
    win._set_key_status("current status")
    monkeypatch.setattr(win, "sender", lambda: old)
    win._on_preview_fail("old error")
    assert win.key_status.text() == "current status"
    win.close()
    app.processEvents()


def test_preview_worker_rechecks_source_after_synthesis(tmp_path, monkeypatch, pcm_wav):
    from bilingual_sub.gui.workers import VoicePreviewWorker
    video, output = tmp_path / "video.mp4", tmp_path / "preview.wav"
    video.write_bytes(b"original source")
    monkeypatch.setattr("bilingual_sub.core.voice_preview.preview_cache_dir", lambda: tmp_path)
    monkeypatch.setattr("bilingual_sub.adapters.tts.gptsovits_runtime.ensure_ref_audio", lambda *a, **kw: tmp_path / "reference.wav")
    def synth(**kwargs):
        output.write_bytes(pcm_wav())
        video.write_bytes(b"replacement source")
        return output
    monkeypatch.setattr("bilingual_sub.core.voice_preview.synth_voice_preview", synth)
    worker = VoicePreviewWorker("gptsovits", "", "en", video=video)
    success, errors = [], []
    worker.ok.connect(success.append)
    worker.fail.connect(errors.append)
    worker.run()
    assert not success and len(errors) == 1 and "源视频发生变化" in errors[0]


def test_preview_without_ref_asks_for_clip(monkeypatch):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.styles import app_qss
    from bilingual_sub.i18n import set_locale

    set_locale("zh-Hans")
    monkeypatch.setattr("bilingual_sub.gui.app.get_api_key", lambda: "")
    monkeypatch.setattr(
        "bilingual_sub.gui.app.load_gptsovits_settings",
        lambda: {"endpoint": "", "ref_audio": "", "prompt_text": "", "prompt_lang": ""},
    )
    monkeypatch.setattr("bilingual_sub.gui.app.save_gptsovits_settings", lambda **k: None)
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    win.tts_ref_edit.clear()
    win.tts_combo.setCurrentIndex(win.tts_combo.findData('qwen3'))
    win._video = None
    win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData("en"))
    win.dub_check.setChecked(True)
    app.processEvents()
    win.tts_preview_btn.click()
    app.processEvents()
    assert "参考音频" in win.key_status.text()
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


def test_preview_click_starts_worker_with_current_voice(monkeypatch, tmp_path, pcm_wav):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.styles import app_qss
    from bilingual_sub.i18n import set_locale

    set_locale("zh-Hans")
    monkeypatch.setattr("bilingual_sub.gui.app.get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        "bilingual_sub.gui.app.load_gptsovits_settings",
        lambda: {"endpoint": "", "ref_audio": "", "prompt_text": "", "prompt_lang": ""},
    )
    monkeypatch.setattr("bilingual_sub.gui.app.save_gptsovits_settings", lambda **k: None)
    started: list = []

    class FakeWorker:
        def __init__(self, provider, voice, lang, endpoint="", ref_audio="", prompt_text="", prompt_lang="", sample_text=""):
            self.provider = provider
            self.voice = voice
            self.lang = lang
            self.endpoint = endpoint
            self.ref_audio = ref_audio
            self.prompt_text = prompt_text
            self.prompt_lang = prompt_lang
            self.sample_text = sample_text
            self.ok = _FakeSignal()
            self.fail = _FakeSignal()
            self.progress = _FakeSignal()

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
    win.dub_check.setChecked(True)
    win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData("en"))
    clip = tmp_path / "reference.wav"
    clip.write_bytes(pcm_wav(4))
    win.tts_ref_edit.setText(str(clip))
    app.processEvents()
    win.tts_preview_btn.click()
    app.processEvents()
    assert started[0][0] == "qwen3-native"
    assert started[0][1] == ""
    assert started[0][2] == "en"
    assert started[0][3].endswith(':19882')
    win.close()
    _ = app
