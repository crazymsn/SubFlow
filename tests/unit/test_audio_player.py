import os
import sys
import time
from types import SimpleNamespace

import psutil
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QProcess, Signal
from PySide6.QtWidgets import QApplication

from bilingual_sub.gui import audio_player as player_module


@pytest.fixture
def playback(tmp_path, pcm_wav):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    player = player_module.PreviewPlayer()
    events = []
    player.started.connect(lambda: events.append("started"))
    player.finished.connect(lambda: events.append("finished"))
    player.failed.connect(lambda message: events.append(message))
    path = tmp_path / "preview.wav"
    path.write_bytes(pcm_wav())
    yield app, player, path, events
    player.stop()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def wait_for(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        assert time.monotonic() < deadline, "playback event timeout"
        app.processEvents()
        time.sleep(.005)


@pytest.fixture
def qt_backend(monkeypatch):
    class Output(QObject):
        def setVolume(self, value):
            pass
    class Media(QObject):
        PlaybackState = SimpleNamespace(PlayingState=1, StoppedState=0)
        MediaStatus = SimpleNamespace(EndOfMedia=7)
        Error = SimpleNamespace(NoError=0, ResourceError=1)
        playbackStateChanged = Signal(int)
        mediaStatusChanged = Signal(int)
        errorOccurred = Signal(int, str)
        def setAudioOutput(self, output):
            pass
        def setSource(self, source):
            pass
        def play(self):
            pass  # Deliberately asynchronous, just like the real backend.
        def stop(self):
            self.playbackStateChanged.emit(0)
        def errorString(self):
            return "codec failure"
    monkeypatch.setitem(sys.modules, "PySide6.QtMultimedia", SimpleNamespace(QAudioOutput=Output, QMediaPlayer=Media))
    monkeypatch.setattr(player_module.PreviewPlayer, "_play_winsound", lambda *a: False)
    monkeypatch.setattr(player_module.PreviewPlayer, "_play_afplay", lambda *a: False)
    return Media


def test_qt_waits_for_loading_and_reports_actual_completion(playback, qt_backend):
    _, player, path, events = playback
    player.play(path)
    backend = player._player
    assert player.is_active() and not events
    backend.playbackStateChanged.emit(1)
    assert events == ["started"]
    backend.playbackStateChanged.emit(0)
    assert player.is_active()  # Stopped can precede a decode error.
    backend.mediaStatusChanged.emit(7)
    assert events == ["started", "finished"] and not player.is_active()


@pytest.mark.parametrize("started", [False, True])
def test_qt_error_finishes_once_before_or_after_start(playback, qt_backend, started):
    _, player, path, events = playback
    player.play(path)
    backend = player._player
    if started:
        backend.playbackStateChanged.emit(1)
    backend.errorOccurred.emit(1, "bad audio")
    backend.errorOccurred.emit(1, "duplicate")
    backend.mediaStatusChanged.emit(7)
    assert events == (["started"] if started else []) + ["bad audio", "finished"]
    assert player._player is None and player._output is None and player._watch is None


def test_old_player_and_timer_cannot_complete_new_playback(playback, qt_backend):
    _, player, path, events = playback
    player.play(path)
    old, timer = player._player, player._watch
    player.play(path)
    old.errorOccurred.emit(1, "stale failure")
    old.mediaStatusChanged.emit(7)
    timer.timeout.emit()
    assert player.is_active() and events == []
    player._watch.timeout.emit()
    assert events == ["播放器未能开始试听", "finished"]


def native_backend(monkeypatch, code, missing=False):
    class Native(QProcess):
        def start(self, program, arguments):
            assert program == "/usr/bin/afplay"
            super().start("nonexistent-subflow-audio-player" if missing else sys.executable,
                          ["-u", "-c", code])
    monkeypatch.setattr(player_module, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(player_module, "QProcess", Native)


@pytest.mark.parametrize("early", [False, True])
def test_stop_reaps_real_native_child_even_during_startup(playback, monkeypatch, early):
    app, player, path, events = playback
    native_backend(monkeypatch, "import time; time.sleep(30)")
    player.play(path)
    process = player._process
    finished = []
    process.finished.connect(lambda *a: finished.append(True))
    if not early:
        wait_for(app, lambda: bool(process.processId()))
    pid = process.processId()
    before = list(events)
    player.stop()
    wait_for(app, lambda: bool(finished))
    assert not pid or not psutil.pid_exists(pid)
    assert not player.is_active() and events == before


@pytest.mark.parametrize("mode", ["success", "error", "missing"])
def test_native_completion_and_failures_use_process_events(playback, monkeypatch, mode):
    app, player, path, events = playback
    native_backend(monkeypatch, "import sys; sys.stderr.write('device failed'); sys.exit(4)"
                   if mode == "error" else "pass", mode == "missing")
    player.play(path)
    wait_for(app, lambda: "finished" in events)
    assert events.count("finished") == 1 and not player.is_active()
    if mode == "success":
        assert events == ["started", "finished"]
    else:
        assert len(events) == (2 if mode == "missing" else 3)
        assert "失败" in events[-2] or "无法" in events[-2]


def test_external_open_failure_is_reported(playback, monkeypatch):
    _, player, path, events = playback
    for name in ("_play_winsound", "_play_afplay", "_play_qt"):
        monkeypatch.setattr(player, name, lambda *a: False)
    monkeypatch.setattr(player_module.QDesktopServices, "openUrl", lambda *a: False)
    player.play(path)
    assert events == ["系统未能打开试听音频", "finished"]
