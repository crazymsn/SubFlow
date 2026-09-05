from unittest.mock import Mock

from PySide6.QtWidgets import QApplication, QMessageBox

from bilingual_sub.core.control import JobControl
from bilingual_sub.gui.app import MainWindow


def test_download_uses_pause_resume_stop_and_blocks_pipeline(monkeypatch, tmp_path):
    class Signal:
        def connect(self, slot):
            self.slot = slot

    class Worker:
        def __init__(self, *args, **kwargs):
            self.control = JobControl()
            self.progress, self.ok, self.fail, self.finished = (Signal() for _ in range(4))
            self.running = False

        def start(self):
            self.running = True

        def isRunning(self):
            return self.running

    monkeypatch.setattr("bilingual_sub.gui.app.DownloadWorker", Worker)
    pipeline = Mock()
    monkeypatch.setattr("bilingual_sub.gui.app.PipelineWorker", pipeline)
    monkeypatch.setattr("bilingual_sub.gui.app.download_folder", lambda url: tmp_path)
    warning = Mock()
    monkeypatch.setattr(QMessageBox, "warning", warning)
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        win.url_edit.setText("https://youtu.be/example")
        win._download()
        worker = win._dl_worker
        assert win._control is worker.control
        assert not win.run_btn.isEnabled() and not win.download_btn.isEnabled()
        assert win.pause_btn.isEnabled() and win.stop_btn.isEnabled()
        win._start()
        assert not pipeline.called
        win._pause()
        assert worker.control.is_paused() and win.resume_btn.isEnabled()
        win._resume()
        assert not worker.control.is_paused()
        win._stop()
        assert worker.control.is_stopped()
        assert not win.run_btn.isEnabled()
        worker.running = False
        worker.fail.slot("job stopped")
        assert not warning.called
        # Thread exit alone is insufficient: finish handling releases ownership.
        win._sync_download()
        assert not win.download_btn.isEnabled()
        worker.finished.slot()
        assert win._control is None and win._dl_worker is None
        assert win.run_btn.isEnabled() and win.download_btn.isEnabled()
    finally:
        if win._dl_worker:
            win._dl_worker.running = False
        win.close()
        app.processEvents()
