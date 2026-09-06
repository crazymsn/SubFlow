import json
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from bilingual_sub.gui.app import MainWindow
from bilingual_sub.models import JobConfig


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.show()
    app.processEvents()
    yield win
    win.close()
    win._device_worker.wait(5000)
    app.processEvents()


def test_idle_only_shows_hardware_and_header_opens_link(window, monkeypatch):
    win = window
    assert win.gpu_status.isVisible()
    assert win.progress.isVisible() and win.log.isVisible() and win.pct_label.isVisible()
    assert win.log.viewport().isAncestorOf(win.gpu_status)
    assert win.product_lbl.text() == win.windowTitle() == "SubFlow 语幕"
    assert win.theme_combo.height() == win.locale_combo.height() == win.github_btn.height() == 40
    assert win.theme_combo.width() == win.locale_combo.width()
    assert win.theme_combo.font().pixelSize() == win.locale_combo.font().pixelSize() == 16
    from PySide6.QtWidgets import QLabel
    badges = win.findChildren(QLabel, 'stepBadge')
    assert len(badges) == 4
    for badge in badges:
        title = badge.parentWidget().findChild(QLabel, 'sectionTitle')
        assert title is not None
        assert abs(badge.geometry().center().y() - title.geometry().center().y()) <= 1
    win._log_line("background warmup")
    assert not win.log.toPlainText() and not win.log.placeholderText()
    urls = []
    monkeypatch.setattr("bilingual_sub.gui.widgets.header.QDesktopServices.openUrl", lambda url: urls.append(url.toString()))
    win.company_lbl.click()
    assert urls == ["https://nav.meding.site"]
    win._on_device_detected("gpu_apple", "Apple M1")
    assert win.gpu_status.text().splitlines()[-1] == "M1"
    win.locale_combo.setCurrentIndex(win.locale_combo.findData("en"))
    assert win.gpu_status.text().splitlines()[-1] == "M1" and not win.log.placeholderText()
    win._on_progress("transcribe", 0.2)
    assert win.progress.isVisible() and win.gpu_status.isHidden()


@pytest.mark.parametrize('size', [(960, 640), (1024, 768), (1280, 800), (1440, 900)])
def test_idle_model_name_fits_inside_log_box(window, size):
    window.resize(*size)
    window._on_device_detected('gpu_cuda', 'NVIDIA GeForce RTX 3060 Laptop GPU')
    app = QApplication.instance()
    for _ in range(3):
        app.processEvents()
    label = window.gpu_status
    assert window.log.viewport().rect().contains(label.geometry())
    assert label.height() >= label.heightForWidth(label.width())


@pytest.mark.parametrize("completed,enabled", [("glossary", True), ("done", True), ("silence", False)])
def test_continue_resumes_exact_work_directory(window, tmp_path, monkeypatch, completed, enabled):
    win = window
    work = tmp_path / "job-1"
    work.mkdir()
    (work / "job_state.json").write_text(json.dumps({"completed_stage": completed}))
    cfg = JobConfig(tmp_path / "input.mp4", None, tmp_path / "out.srt", tmp_path / "auto")
    win._worker = SimpleNamespace(work_dir=work, config=cfg, isRunning=lambda: False)
    win._retry_translation = True
    win._release_job()
    assert win.resume_btn.isEnabled() == enabled
    if enabled:
        captured = []
        monkeypatch.setattr(win, "_launch_job", captured.append)
        win.resume_btn.click()
        assert captured[0].resume_from == "translate"
        assert captured[0].work_dir == work and captured[0].input_video == cfg.input_video
        assert win.progress.value() == 60


def test_video_job_keeps_selected_design_voice(window, tmp_path, monkeypatch):
    win = window
    path = tmp_path / "video.mp4"
    path.write_bytes(b"video")
    win._set_video(path)
    win.source_lang_combo.setCurrentIndex(win.source_lang_combo.findData("zh"))
    win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData("fr"))
    win.tts_combo.setCurrentIndex(win.tts_combo.findData("qwen3-native"))
    win.tts_voice_edit.setCurrentIndex(win.tts_voice_edit.findData("SubFlow_fr_male"))
    win.key_edit.setText("test-key")
    win.model_combo.addItem("test-model")
    win.model_combo.setCurrentText("test-model")
    win.out_edit.setText(str(tmp_path / "result.mp4"))
    captured = []
    monkeypatch.setattr(win, "_launch_job", captured.append)
    win._start()
    assert captured[0].tts_provider == "qwen3-native"
    assert captured[0].tts_voice == "SubFlow_fr_male"
    assert captured[0].tts_endpoint and not captured[0].tts_ref_audio


def test_missing_translation_remains_retryable_after_later_stage_failure(window, tmp_path):
    state = {"completed_stage": "render", "artifact_contexts": {"translate": {"missing": ["line"]}}}
    (tmp_path / "job_state.json").write_text(json.dumps(state))
    cfg = JobConfig(tmp_path / "in.mp4", None, tmp_path / "out.srt", tmp_path)
    window._worker = SimpleNamespace(work_dir=tmp_path, config=cfg, isRunning=lambda: False)
    window._retry_translation = False
    window._release_job()
    assert window.resume_btn.isEnabled() and window._resume_config.resume_from == "translate"


def test_continue_uses_changed_translation_settings_and_original_job(window, tmp_path, monkeypatch):
    cfg = JobConfig(tmp_path / "original.mp4", None, tmp_path / "original.srt", tmp_path,
                    resume_from="translate", translate_model="old-model")
    window._resume_config = cfg
    window.model_combo.addItem("new-model")
    window.model_combo.setCurrentText("new-model")
    window.refine_check.setChecked(True)
    window.key_edit.setText("replacement-test-token")
    keys, launched = [], []
    monkeypatch.setattr("bilingual_sub.gui.app.set_api_key", keys.append)
    monkeypatch.setattr(window, "_launch_job", launched.append)
    window._resume()
    assert keys == ["replacement-test-token"] and not window.key_edit.text()
    assert launched[0].translate_model == "new-model" and launched[0].refine_translate
    assert launched[0].input_video == cfg.input_video and launched[0].work_dir == cfg.work_dir
    assert cfg.translate_model == "old-model"


def test_retry_failure_before_work_ready_keeps_continue_and_dialog_action(window, tmp_path, monkeypatch):
    import time

    from PySide6.QtTest import QTest

    cfg = JobConfig(tmp_path / "video.mp4", None, tmp_path / "out.srt", tmp_path,
                    resume_from="translate")
    (tmp_path / "job_state.json").write_text(json.dumps({"completed_stage": "glossary"}))
    attempts = []
    def locked(config, **kwargs):
        attempts.append(config)
        raise RuntimeError("work directory temporarily locked")
    monkeypatch.setattr("bilingual_sub.pipeline.run", locked)
    def finish():
        deadline = time.monotonic() + 5
        while window._worker is not None and time.monotonic() < deadline:
            QTest.qWait(10)
        assert window._worker is None
        assert window.resume_btn.isEnabled() and window._error_dialog.action.isEnabled()
    window._launch_job(cfg)
    finish()
    window._error_dialog.action.click()
    finish()
    assert len(attempts) == 2
    assert all(c.work_dir == tmp_path and c.resume_from == "translate" for c in attempts)
    assert window._resume_config is not None
    window._error_dialog.close()


@pytest.mark.parametrize("partial", [False, True])
def test_worker_failure_or_partial_result_enables_continue(window, tmp_path, monkeypatch, partial):
    import time

    from PySide6.QtTest import QTest

    from bilingual_sub.models import JobResult

    win = window
    work = tmp_path / "work"
    work.mkdir()
    cfg = JobConfig(tmp_path / "video.mp4", None, tmp_path / "result.srt", tmp_path / "auto")
    requests = []
    def run(config, *, on_progress, control, on_work_ready):
        requests.append(config)
        on_work_ready(work)
        on_progress("translate", 0.6)
        (work / "job_state.json").write_text(json.dumps({"completed_stage": "glossary"}))
        if len(requests) == 1 and not partial:
            raise RuntimeError("translation disconnected")
        return JobResult("test", None, cfg.output_srt, cfg.output_srt.with_suffix(".ass"),
                         1, ["missing"] if len(requests) == 1 else [], 1, work / "report.json")
    monkeypatch.setattr("bilingual_sub.pipeline.run", run)
    monkeypatch.setattr("bilingual_sub.gui.app.show_error", lambda *a, **k: None)
    def wait_finished():
        deadline = time.monotonic() + 5
        while win._worker is not None and time.monotonic() < deadline:
            QTest.qWait(10)
        assert win._worker is None
    win._launch_job(cfg)
    wait_finished()
    assert win.resume_btn.isEnabled()
    win.resume_btn.click()
    wait_finished()
    assert len(requests) == 2 and requests[1].resume_from == "translate"
    assert requests[1].work_dir == work
    assert win.progress.value() == 100 and not win.resume_btn.isEnabled()
