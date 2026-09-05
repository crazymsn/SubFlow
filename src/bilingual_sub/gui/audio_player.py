"""Play a short local audio file inside the desktop client."""

from __future__ import annotations

import sys
import wave
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices

if TYPE_CHECKING:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer


def _wav_ms(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate() or 1
            return max(800, int(frames / rate * 1000) + 200)
    except Exception:
        return 4000


def _as_pcm_wav(path: Path) -> Path:
    from bilingual_sub.adapters.ffmpeg import is_pcm_wav, to_pcm_wav

    audio = Path(path)
    if is_pcm_wav(audio):
        return audio
    return to_pcm_wav(audio, audio.with_name(audio.stem + ".play.wav"))


class PreviewPlayer(QObject):
    finished = Signal()
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._player: QMediaPlayer | None = None
        self._output: QAudioOutput | None = None
        self._watch: QTimer | None = None

    def play(self, path: Path) -> None:
        self.stop()
        audio = Path(path)
        if not audio.is_file() or audio.stat().st_size < 16:
            self.failed.emit("试听文件是空的")
            self.finished.emit()
            return
        try:
            wav = _as_pcm_wav(audio)
        except Exception as exc:
            if self._play_qt(audio):
                return
            self.failed.emit(str(exc) or "无法解码试听音频")
            self.finished.emit()
            return
        if self._play_winsound(wav):
            return
        if self._play_afplay(wav):
            return
        if self._play_qt(wav):
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(wav.resolve())))
        QTimer.singleShot(0, self.finished.emit)

    def stop(self) -> None:
        watch = self._watch
        self._watch = None
        if watch is not None:
            watch.stop()
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
        output.setVolume(1.0)
        player = QMediaPlayer(self)
        player.setAudioOutput(output)
        player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        self._output = output
        self._player = player
        started = {"ok": False}

        def on_state(state: object) -> None:
            if state == QMediaPlayer.PlaybackState.PlayingState:
                started["ok"] = True
            elif state == QMediaPlayer.PlaybackState.StoppedState and started["ok"]:
                self.finished.emit()

        def on_error(*_a) -> None:
            if not started["ok"]:
                self._player = None
                self._output = None

        player.playbackStateChanged.connect(on_state)
        player.errorOccurred.connect(on_error)
        player.play()
        if player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            started["ok"] = True
            return True
        # Import succeeded but the Windows FFmpeg plugin is often missing in
        # the frozen client. Do not treat a silent play() as success.
        try:
            player.stop()
        except Exception:
            pass
        self._player = None
        self._output = None
        return False

    def _arm_finished(self, ms: int) -> None:
        watch = QTimer(self)
        watch.setSingleShot(True)
        watch.timeout.connect(self.finished.emit)
        self._watch = watch
        watch.start(ms)

    def _play_winsound(self, path: Path) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import winsound
        except ImportError:
            return False
        try:
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            return False
        self._arm_finished(_wav_ms(path))
        return True

    def _play_afplay(self, path: Path) -> bool:
        if sys.platform != "darwin":
            return False
        import subprocess

        try:
            subprocess.Popen(
                ["afplay", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return False
        self._arm_finished(_wav_ms(path))
        return True
