"""Background workers for the SubFlow desktop client."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from bilingual_sub.adapters.meding import MedingAuthError, create_client
from bilingual_sub.core.control import JobControl, JobStopped
from bilingual_sub.i18n import tr
from bilingual_sub.models import JobConfig
from bilingual_sub.secrets.store import get_api_key


class PipelineWorker(QThread):
    progress = Signal(str, float)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, config: JobConfig, control, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.control = control
        self.work_dir: Path | None = None

    def _work_ready(self, path: Path) -> None:
        self.work_dir = path

    def run(self) -> None:
        try:
            from bilingual_sub.pipeline import run as run_job

            result = run_job(
                self.config,
                on_progress=lambda s, p: self.progress.emit(s, p),
                control=self.control,
                on_work_ready=self._work_ready,
            )
            self.finished_ok.emit(result)
        except JobStopped:
            self.failed.emit(tr("stop"))
        except Exception as exc:
            if self.control is not None and self.control.is_stopped():
                self.failed.emit(tr("stop"))
            else:
                self.failed.emit(str(exc))


class DeviceProbeWorker(QThread):
    result = Signal(str, str)

    def run(self) -> None:
        from bilingual_sub.gui.hardware import detect_hardware

        key, name = detect_hardware()
        self.result.emit(key, name)


class ModelsWorker(QThread):
    ok = Signal(list)
    fail = Signal(str)

    def run(self) -> None:
        key = get_api_key()
        if not key:
            self.fail.emit(tr("need_token"))
            return
        try:
            models = create_client(key).list_models()
            self.ok.emit(models)
        except MedingAuthError as exc:
            self.fail.emit(str(exc))
        except Exception as exc:
            self.fail.emit(str(exc))


class VoicePreviewWorker(QThread):
    ok = Signal(str)
    fail = Signal(str)
    progress = Signal(str, float)

    def __init__(
        self,
        provider: str,
        voice: str,
        lang: str,
        endpoint: str = "",
        ref_audio: str = "",
        prompt_text: str = "",
        prompt_lang: str = "",
        video: Path | None = None,
        sample_text: str = "",
    ) -> None:
        super().__init__()
        self.provider = provider
        self.voice = voice
        self.lang = lang
        self.endpoint = endpoint
        self.ref_audio = ref_audio
        self.prompt_text = prompt_text
        self.prompt_lang = prompt_lang
        self.video = video
        self.sample_text = sample_text
        self.control = JobControl()

    def run(self) -> None:
        try:
            from bilingual_sub.adapters.tts.base import TtsUnavailable
            from bilingual_sub.core.voice_preview import synth_voice_preview

            ref_audio = self.ref_audio
            if not ref_audio and self.video is not None and self.provider != 'qwen3-native':
                import hashlib

                from bilingual_sub.adapters.tts.gptsovits_runtime import ensure_ref_audio
                from bilingual_sub.core.file_io import file_digest
                from bilingual_sub.core.resource_claims import claim_resources
                from bilingual_sub.core.voice_preview import preview_cache_dir

                source_digest = file_digest(self.video, checkpoint=self.control.wait_if_paused)
                key = hashlib.sha256(f"{self.video.resolve()}|{source_digest}".encode()).hexdigest()[:16]
                reference = preview_cache_dir() / f"ref-{key}.wav"
                with claim_resources(reads=[self.video], writes=[reference, reference.with_suffix(".wav.json")],
                                     checkpoint=self.control.wait_if_paused):
                    ref_audio = str(ensure_ref_audio(self.video, reference, control=self.control))
                    if file_digest(self.video, checkpoint=self.control.wait_if_paused) != source_digest:
                        raise RuntimeError("试听准备期间源视频发生变化，请重试")

            path = synth_voice_preview(
                provider=self.provider,
                voice=self.voice,
                lang=self.lang,
                endpoint=self.endpoint,
                ref_audio=ref_audio,
                # Automatically extracted speech has no user-verified transcript.
                prompt_text=self.prompt_text if self.ref_audio else "",
                prompt_lang=self.prompt_lang,
                sample_text=self.sample_text,
                control=self.control,
                on_progress=self.progress.emit,
            )
            if not self.ref_audio and self.video is not None and self.provider != 'qwen3-native':
                if file_digest(self.video, checkpoint=self.control.wait_if_paused) != source_digest:
                    raise RuntimeError("试听合成期间源视频发生变化，请重试")
            self.ok.emit(str(path))
        except TtsUnavailable as exc:
            self.fail.emit(str(exc))
        except Exception as exc:
            self.fail.emit(str(exc))


class SovitsBootWorker(QThread):
    ok = Signal(str)
    fail = Signal(str)
    progress = Signal(str)

    def __init__(self, endpoint: str = "", provider: str = "gptsovits") -> None:
        super().__init__()
        self.endpoint = endpoint
        self.provider = provider
        self.control = JobControl()

    def run(self) -> None:
        try:
            from bilingual_sub.adapters.tts.routing import ensure_running

            self.ok.emit(ensure_running(self.provider, self.endpoint, wait_sec=300, control=self.control, progress=self.progress.emit))
        except Exception as exc:
            self.fail.emit(str(exc))


class SovitsProbeWorker(QThread):
    result = Signal(bool, str)

    def __init__(self, endpoint: str, provider: str = "gptsovits") -> None:
        super().__init__()
        self.endpoint = endpoint
        self.provider = provider

    def run(self) -> None:
        from bilingual_sub.adapters.tts.gptsovits_runtime import diagnose_runtime, probe_endpoint

        try:
            if self.provider.startswith("qwen3"):
                from bilingual_sub.adapters.tts.qwen_runtime import probe_endpoint as qwen_probe
                from bilingual_sub.adapters.tts.qwen_runtime import runtime_device

                ready = qwen_probe(self.endpoint, native=self.provider == 'qwen3-native')
                self.result.emit(ready, runtime_device(self.endpoint) if ready else '')
                return
            ready = probe_endpoint(self.endpoint)
            self.result.emit(ready, "" if ready else diagnose_runtime() or "")
        except Exception as exc:
            self.result.emit(False, str(exc))


class DownloadWorker(QThread):
    progress = Signal(str, float)
    ok = Signal(str)
    fail = Signal(str)

    def __init__(self, url: str, dest: Path, source_lang: str = "") -> None:
        super().__init__()
        self.url = url
        self.dest = dest
        self.source_lang = source_lang or "zh"
        self.control = JobControl()

    def run(self) -> None:
        try:
            from bilingual_sub.adapters.ytdlp import download as ytdlp_download

            path = ytdlp_download(
                self.url,
                self.dest,
                on_progress=lambda stage, pct: self.progress.emit(stage, pct),
                progress_range=(0.0, 1.0),
                control=self.control,
                source_lang=self.source_lang,
            )
            self.progress.emit("ingest", 1.0)
            self.ok.emit(str(path))
        except JobStopped:
            self.fail.emit(tr("stop"))
        except Exception as exc:
            from bilingual_sub.adapters.ytdlp import explain_download_error

            self.fail.emit(explain_download_error(exc))
