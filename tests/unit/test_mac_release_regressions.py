import json
import platform
import sys
import threading

import pytest

from bilingual_sub.adapters.tts.gptsovits_runtime import bundled_src


def test_frozen_self_test_finds_offline_model_without_checkout(tmp_path, monkeypatch):
    root = tmp_path / 'SubFlow.app/Contents/Resources/offline'
    home = root / 'models/GPT-SoVITS'
    home.mkdir(parents=True)
    (home / 'api_v2.py').touch()
    (root / 'bundle.json').write_text(json.dumps({
        'schema': 1, 'platform': sys.platform, 'machine': platform.machine(),
        'models': {'gptsovits': {'path': 'models/GPT-SoVITS', 'files': {'api_v2.py': {}}}},
    }))
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(root.parents[1] / 'MacOS/SubFlow'))
    monkeypatch.delenv('SUBFLOW_OFFLINE_DIR', raising=False)
    monkeypatch.chdir(tmp_path)
    assert bundled_src() == home
    (home / 'api_v2.py').unlink()
    assert bundled_src() is None


def test_frozen_self_test_cannot_pass_using_build_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path / 'missing'), raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'MacOS/SubFlow'))
    monkeypatch.delenv('SUBFLOW_OFFLINE_DIR', raising=False)
    # This test runs in a checkout containing third_party/GPT-SoVITS.
    assert bundled_src() is None


def test_failed_gui_self_test_waits_for_running_probe(tmp_path, monkeypatch):
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QWidget

    from bilingual_sub.gui import app, self_test

    stopped = threading.Event()
    windows = []

    class Probe(QThread):
        def run(self):
            while not self.isInterruptionRequested():
                self.msleep(5)
            stopped.set()

    class Window(QWidget):
        def __init__(self):
            super().__init__()
            self.probe = Probe(self)
            self.probe.start()
            windows.append(self)

        def closeEvent(self, event):  # noqa: N802
            self.probe.requestInterruption()
            if self.probe.isRunning():
                event.ignore()
            else:
                event.accept()

    def fail(*args):
        assert windows[0].probe.isRunning()
        raise AssertionError('missing bundled model')

    monkeypatch.setattr(app, 'MainWindow', Window)
    monkeypatch.setattr(self_test, '_check_window', fail)
    report = tmp_path / 'report.json'
    with pytest.raises(AssertionError, match='missing bundled model'):
        self_test._run(report, tmp_path)
    assert stopped.is_set() and not windows[0].probe.isRunning()
    assert json.loads(report.read_text()) == {
        'ok': False, 'error': 'AssertionError: missing bundled model',
    }
