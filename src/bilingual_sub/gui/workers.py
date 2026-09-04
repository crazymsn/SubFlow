"""Background workers for the SubFlow desktop client."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from bilingual_sub.adapters.meding import MedingAuthError, create_client
from bilingual_sub.core.control import JobStopped
from bilingual_sub.i18n import tr
from bilingual_sub.models import JobConfig
from bilingual_sub.secrets.store import get_api_key


class PipelineWorker(QThread):
    progress = Signal(str, float)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, config: JobConfig, control) -> None:
        super().__init__()
        self.config = config
        self.control = control

    def run(self) -> None:
        try:
            from bilingual_sub.pipeline import run as run_job

            result = run_job(
                self.config,
                on_progress=lambda s, p: self.progress.emit(s, p),
                control=self.control,
            )
            self.finished_ok.emit(result)
        except JobStopped:
            self.failed.emit(tr("stop"))
        except Exception as exc:
            if self.control is not None and self.control.is_stopped():
                self.failed.emit(tr("stop"))
            else:
                self.failed.emit(str(exc))


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


class DownloadWorker(QThread):
    ok = Signal(str)
    fail = Signal(str)

    def __init__(self, url: str, dest: Path) -> None:
        super().__init__()
        self.url = url
        self.dest = dest

    def run(self) -> None:
        try:
            from bilingual_sub.adapters.ytdlp import download as ytdlp_download

            path = ytdlp_download(self.url, self.dest)
            self.ok.emit(str(path))
        except Exception as exc:
            from bilingual_sub.adapters.ytdlp import explain_download_error

            self.fail.emit(explain_download_error(exc))
