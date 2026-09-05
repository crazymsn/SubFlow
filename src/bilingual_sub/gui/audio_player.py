"""Play a short local audio file inside the desktop client."""
from __future__ import annotations

import sys
import wave
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QProcess, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices

if TYPE_CHECKING:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer


def _wav_ms(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as handle:
            return min(2**31 - 1, max(800, int(handle.getnframes() / (handle.getframerate() or 1) * 1000) + 200))
    except (OSError, wave.Error, EOFError):
        return 4000


def _as_pcm_wav(path: Path) -> Path:
    from bilingual_sub.adapters.ffmpeg import is_pcm_wav, to_pcm_wav

    return path if is_pcm_wav(path) else to_pcm_wav(path, path.with_name(path.stem + ".play.wav"))


class PreviewPlayer(QObject):
    started = Signal()
    finished = Signal()
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._player: QMediaPlayer | None = None
        self._output: QAudioOutput | None = None
        self._process: QProcess | None = None
        self._watch: QTimer | None = None
        self._winsound_active = False
        self._active = False

    def is_active(self) -> bool:
        return self._active

    def play(self, path: Path) -> None:
        self.stop()
        self._active = True
        audio = Path(path)
        try:
            if not audio.is_file() or audio.stat().st_size < 16:
                self._finish("试听文件是空的")
                return
            wav = _as_pcm_wav(audio)
        except Exception as exc:
            if not self._play_qt(audio):
                self._finish(str(exc) or "无法解码试听音频")
            return
        if self._play_winsound(wav) or self._play_afplay(wav) or self._play_qt(wav):
            return
        if QDesktopServices.openUrl(QUrl.fromLocalFile(str(wav.resolve()))):
            self._finish()  # The external application now owns playback.
        else:
            self._finish("系统未能打开试听音频")

    def _clear_watch(self) -> None:
        watch, self._watch = self._watch, None
        if watch is not None:
            watch.stop()
            watch.deleteLater()

    def stop(self) -> None:
        self._active = False
        self._clear_watch()
        player, self._player = self._player, None
        output, self._output = self._output, None
        if player is not None:
            player.stop()
            player.deleteLater()
        if output is not None:
            output.deleteLater()
        process, self._process = self._process, None
        if process is not None:
            if process.state() != QProcess.ProcessState.NotRunning:
                # QProcess owns/reaps the child. Retain it until its exit event.
                process.finished.connect(process.deleteLater)
                process.started.connect(process.kill)
                process.errorOccurred.connect(lambda error: process.deleteLater()
                    if error == QProcess.ProcessError.FailedToStart else None)
                process.kill()
                process.waitForFinished(1000)
            else:
                process.deleteLater()
        if self._winsound_active:
            self._winsound_active = False
            try:
                import winsound

                winsound.PlaySound(None, winsound.SND_PURGE)
            except (ImportError, RuntimeError):
                pass

    def _finish(self, error: str = "") -> None:
        if not self._active:
            return
        self.stop()
        if error:
            self.failed.emit(error)
        self.finished.emit()

    def _arm_finished(self, ms: int, error: str = "") -> None:
        self._clear_watch()
        watch = QTimer(self)
        watch.setSingleShot(True)
        watch.timeout.connect(lambda: self._finish(error) if self._watch is watch else None)
        self._watch = watch
        watch.start(min(2**31 - 1, max(1, ms)))

    def _play_qt(self, path: Path) -> bool:
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            return False
        output = QAudioOutput(self)
        output.setVolume(1.0)
        player = QMediaPlayer(self)
        self._output, self._player = output, player
        started = False

        def on_state(state: object) -> None:
            nonlocal started
            if self._player is not player:
                return
            if state == QMediaPlayer.PlaybackState.PlayingState and not started:
                started = True
                self._arm_finished(_wav_ms(path) + 10000, "试听播放超时")
                self.started.emit()

        def on_status(status: object) -> None:
            if self._player is player and status == QMediaPlayer.MediaStatus.EndOfMedia:
                self._finish()

        def on_error(error, message="") -> None:
            if self._player is player and error != QMediaPlayer.Error.NoError:
                self._finish(str(message or player.errorString() or "无法播放试听音频"))

        player.playbackStateChanged.connect(on_state)
        player.mediaStatusChanged.connect(on_status)
        player.errorOccurred.connect(on_error)
        self._arm_finished(10000, "播放器未能开始试听")
        player.setAudioOutput(output)
        player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        if self._player is player:
            player.play()  # Loading is asynchronous; wait for state/error signals.
        return True

    def _play_winsound(self, path: Path) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import winsound

            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except (ImportError, RuntimeError):
            return False
        self._winsound_active = True
        self._arm_finished(_wav_ms(path))
        self.started.emit()
        return True

    def _play_afplay(self, path: Path) -> bool:
        if sys.platform != "darwin":
            return False
        process = QProcess(self)
        self._process = process

        def on_started():
            if self._process is process:
                self._arm_finished(_wav_ms(path) + 10000, "试听播放超时")
                self.started.emit()

        def on_error(_error):
            if self._process is process:
                self._finish(f"无法播放试听音频：{process.errorString()}")

        def on_finished(code, status):
            if self._process is process:
                message = ""
                if code or status != QProcess.ExitStatus.NormalExit:
                    detail = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")[-1000:]
                    message = f"试听播放器退出失败：{detail or code}"
                self._finish(message)

        process.started.connect(on_started)
        process.errorOccurred.connect(on_error)
        process.finished.connect(on_finished)
        self._arm_finished(10000, "播放器未能开始试听")
        process.start("/usr/bin/afplay", [str(path)])
        return True
