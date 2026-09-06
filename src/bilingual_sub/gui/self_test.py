"""Packaged-client smoke check used by release CI."""
import json
import os
import tempfile
import threading
from pathlib import Path


def run(report: Path) -> None:
    from unittest.mock import patch

    import keyring

    # The frozen smoke check also opens widgets whose signals persist settings.
    # Isolate it just like pytest; a release check must not rewrite a real profile.
    report = report.resolve()
    with tempfile.TemporaryDirectory(prefix="subflow-self-test-") as scratch:
        profile = Path(scratch)
        env = {name: scratch for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_CACHE_HOME")}
        env.update({name: "" for name in ("SUBFLOW_API_KEY", "MEDING_API_KEY", "SUBFLOW_GPTSOVITS_REF",
                                         "SUBFLOW_GPTSOVITS_PROMPT", "SUBFLOW_GPTSOVITS_PROMPT_LANG")})
        with patch.dict(os.environ, env), patch.object(keyring, "get_password", return_value=None), \
                patch.object(keyring, "set_password"), patch.object(keyring, "delete_password"):
            _run(report, profile)


def _run(report: Path, profile: Path) -> None:
    os.environ["SUBFLOW_SOVITS_AUTOSTART"] = "0"
    os.environ["SUBFLOW_AUTO_INSTALL"] = "0"
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.adapters.ffmpeg import find_ffmpeg, find_ffprobe, run_cmd
    from bilingual_sub.adapters.runtime_bootstrap import bootstrap_assets, find_uv
    from bilingual_sub.adapters.tts.gptsovits_runtime import bundled_src
    from bilingual_sub.config import user_config_dir
    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.error_dialog import ErrorDialog

    app = QApplication([])
    win = MainWindow()
    win.source_lang_combo.setCurrentIndex(win.source_lang_combo.findData("zh"))
    win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData("zh-Hant"))
    assert not win.dub_check.isChecked()
    source = bundled_src()
    assert source is not None and (source / "api_v2.py").is_file()
    assert (bootstrap_assets() / "download_assets.py").is_file()
    checks: dict[str, object] = {}
    assert user_config_dir().is_relative_to(profile)
    checks["isolated_user_profile"] = True
    from bilingual_sub.core.voice_preview import preview_sample
    from bilingual_sub.gui.progress import stage_text

    for target in ("zh", "zh-Hant", "en", "ja", "es", "ru", "fr", "de"):
        win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData(target))
        request = win._preview_request()
        assert request.lang == target and request.sample_text == preview_sample(target)
        assert request.provider == 'qwen3-native' and not request.ref_audio
        assert win.tts_voice_edit.count() == 24  # Automatic + nine official presets + fourteen designed voices.
        assert win.tts_voice_edit.findData('Eric') > 0 and win.tts_voice_edit.findData('Sohee') > 0
    assert "3/8" in stage_text("dub|synth|3|8|67")
    assert "01:07" in stage_text("dub|synth|3|8|67")
    assert all((bootstrap_assets() / name).is_file() for name in
               ("qwentts.txt", "qwen-model.json", "qwen-native-model.json", "download_qwen.py", "qwen_server.py"))
    import hashlib

    from bilingual_sub.adapters.tts.qwen import DESIGNED_VOICES

    voices_dir = bootstrap_assets() / 'voices'
    voices = json.loads((voices_dir / 'voices.json').read_text(encoding='utf-8'))['voices']
    assert {voice['id'] for voice in voices} == {voice.name for voice in DESIGNED_VOICES}
    for voice in voices:
        assert hashlib.sha256((voices_dir / voice['file']).read_bytes()).hexdigest() == voice['sha256']
    checks["multilingual_dubbing"] = "all eight targets route correctly; localized progress and model bootstrap assets present"
    win.resize(960, 640)
    win.show()
    assert win._device_worker.wait(5000)
    for _ in range(3):
        app.processEvents()
    win.form_scroll.ensureWidgetVisible(win.key_edit)
    app.processEvents()
    assert not win.run_btn.visibleRegion().isEmpty()
    assert not win.key_edit.visibleRegion().isEmpty()
    assert win.gpu_status.isVisible() and win.progress.isVisible() and win.log.isVisible()
    assert win.log.viewport().isAncestorOf(win.gpu_status)
    assert win.product_lbl.text() == win.windowTitle() == "SubFlow 语幕"
    assert win.theme_combo.height() == win.locale_combo.height() == win.github_btn.height() == 40
    assert win.theme_combo.font().pixelSize() == win.locale_combo.font().pixelSize() == 16
    assert abs(win.company_lbl.mapTo(win, win.company_lbl.rect().center()).x() - win.width() / 2) <= 2
    assert win.gpu_status.height() >= win.gpu_status.heightForWidth(win.gpu_status.width())
    checks["idle_hardware"] = win.gpu_status.text()
    assert win.company_lbl.text() == "深度云创科技"
    assert not win.company_lbl.toolTip()
    assert win.company_lbl.accessibleDescription() == "https://nav.meding.site"
    assert win.dub_box.isVisible()
    win._on_progress("dub|synth|3|8|67", 0.94)
    app.processEvents()
    assert not win.progress.visibleRegion().isEmpty() and not win.gpu_status.isVisible()
    win.locale_combo.setCurrentIndex(win.locale_combo.findData("en"))
    assert "3/8" in win.stage_label.text() and win.pct_label.text() == "94%"
    win.locale_combo.setCurrentIndex(win.locale_combo.findData("zh-Hans"))
    checks["workspace"] = "960x640 actions and settings visible; voice panel independent; locale change preserves task progress"
    dialog = ErrorDialog(win, "参考音频不存在：reference.wav", preview=True)
    dialog.show()
    dialog.details_toggle.click()
    app.processEvents()
    assert dialog.details.isVisible() and "reference.wav" in dialog.details.toPlainText()
    assert dialog.width() <= 600
    dialog.close()
    checks["error_dialog"] = "themed dialog opened with expandable plain-text details"
    from bilingual_sub.adapters.whisper_backend import worker_script as whisper_script
    from bilingual_sub.adapters.whisperx_backend import worker_script as whisperx_script

    workers = [whisper_script(), whisperx_script()]
    assert all(path.with_name("transcript_io.py").is_file() for path in workers)
    checks["asr_worker_scripts"] = [str(path) for path in workers]
    for name, binary in (("ffmpeg", find_ffmpeg()), ("ffprobe", find_ffprobe()), ("uv", str(find_uv()))):
        checks[name] = run_cmd([binary, "--version" if name == "uv" else "-version"]).stdout.splitlines()[0]
    from bilingual_sub.adapters.download_worker import run_download_worker
    from bilingual_sub.adapters.ytdlp import DownloadError
    from bilingual_sub.core.control import JobControl

    with tempfile.TemporaryDirectory(prefix="subflow-worker-smoke-") as scratch:
        control = JobControl()
        deadline = threading.Timer(30, control.stop)
        deadline.start()
        try:
            try:
                run_download_worker("invalid://subflow-smoke", Path(scratch), on_progress=None,
                                    control=control, progress_range=(0, 1), source_lang="zh")
            except DownloadError:
                result = json.loads((Path(scratch) / "download-result.json").read_text(encoding="utf-8"))
                assert result.get("error"), "worker did not return a structured download error"
            else:
                raise AssertionError("invalid URL unexpectedly succeeded")
        finally:
            deadline.cancel()
        checks["download_worker"] = "isolated worker started and returned a structured error"
    win.close()
    app.processEvents()
    report.write_text(json.dumps({"ok": True, "checks": checks}, indent=2), encoding="utf-8")
