"""Play a short local audio file inside the desktop client."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices


class PreviewPlayer(QObject):
    finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._player = None
        self._output = None

    def play(self, path: Path) -> None:
        self.stop()
        audio = Path(path)
        if not audio.is_file() or audio.stat().st_size < 16:
            self.finished.emit()
            return
        if self._play_qt(audio):
            return
        if self._play_winsound(audio):
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(audio.resolve())))
        QTimer.singleShot(0, self.finished.emit)

    def stop(self) -> None:
        player = self._player
        self._player = None
        self._output = None
        if player is not None:
            try:
                player.stop()
            except Exception:
                pass
        try:
            import winsound

            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

    def _play_qt(self, path: Path) -> bool:
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            return False
        output = QAudioOutput(self)
        player = QMediaPlayer(self)
        player.setAudioOutput(output)
        player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        player.playbackStateChanged.connect(self._on_qt_state)
        self._output = output
        self._player = player
        player.play()
        return True

    def _on_qt_state(self, state: object) -> None:
        try:
            from PySide6.QtMultimedia import QMediaPlayer
        except ImportError:
            return
        if state == QMediaPlayer.PlaybackState.StoppedState:
            self.finished.emit()

    def _play_winsound(self, path: Path) -> bool:
        if path.suffix.lower() not in {".wav", ".wave"}:
            return False
        try:
            import winsound
        except ImportError:
            return False
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        QTimer.singleShot(4000, self.finished.emit)
        return True
