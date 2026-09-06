"""语幕 SubFlow desktop client."""

from __future__ import annotations

import hashlib
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from PySide6.QtCore import QSize, Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QFileDialog,
    QFrame,
    QLabel,
    QLayout,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bilingual_sub.adapters.tts.gptsovits import DEFAULT_ENDPOINT
from bilingual_sub.adapters.ytdlp import download_folder
from bilingual_sub.brand import (
    API_PORTAL_URL,
    APP_USER_MODEL_ID,
    COMPANY_ZH,
    GITHUB_URL,
    PRODUCT_EN,
    PRODUCT_ZH,
    WINDOW_TITLE,
)
from bilingual_sub.config import (
    default_glossary_path,
    load_gptsovits_settings,
    load_settings,
    load_style_preset,
    load_subtitle_colors,
    load_ui_theme,
    save_gptsovits_settings,
    save_user_overrides,
)
from bilingual_sub.core.control import JobControl
from bilingual_sub.core.langs import (
    effective_target_lang,
    output_stem_suffix,
    should_dub,
    token_required_for_job,
    translation_needed,
    wants_spoken_target,
)
from bilingual_sub.gui.assets import (
    GITHUB_MARK_PX,
    HEADER_MARK_PX,
    load_app_icon,
    load_brand_mark,
    load_github_mark,
)
from bilingual_sub.gui.audio_player import PreviewPlayer
from bilingual_sub.gui.error_dialog import show_error
from bilingual_sub.gui.model_choice import merge_model_list, preferred_model
from bilingual_sub.gui.output_path import (
    copy_finished_outputs,
    next_output_path,
    refresh_output_path,
    relocate_output,
    resolve_output_mp4,
    sidecar_srt,
)
from bilingual_sub.gui.progress import format_pct, should_log_stage, stage_text
from bilingual_sub.gui.styles import app_qss
from bilingual_sub.gui.theme import tokens_for, type_font
from bilingual_sub.gui.widgets.action_bar import build_action_bar
from bilingual_sub.gui.widgets.deck import build_deck
from bilingual_sub.gui.widgets.field import WorkspaceScroll, hairline
from bilingual_sub.gui.widgets.header import build_header
from bilingual_sub.gui.widgets.source_strip import build_source
from bilingual_sub.gui.widgets.stage import build_stage
from bilingual_sub.gui.workers import (
    DeviceProbeWorker,
    DownloadWorker,
    ModelsWorker,
    PipelineWorker,
    SovitsBootWorker,
    SovitsProbeWorker,
    VoicePreviewWorker,
)
from bilingual_sub.i18n import DEFAULT_LOCALE, set_locale, tr
from bilingual_sub.logging_util import redact_api_key
from bilingual_sub.models import JobConfig, JobResult
from bilingual_sub.secrets.store import delete_api_key, get_api_key, set_api_key

if TYPE_CHECKING:
    from PySide6.QtWidgets import (
        QComboBox,
        QFrame,
        QGridLayout,
        QLineEdit,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QToolButton,
    )

    from bilingual_sub.gui.widgets.brand_check import BrandCheck
    from bilingual_sub.gui.widgets.color_chip import ColorChip
    from bilingual_sub.gui.widgets.drop_card import DropCard
    from bilingual_sub.gui.widgets.filament_btn import FilamentButton


class PreviewRequest(NamedTuple):
    provider: str
    voice: str
    lang: str
    endpoint: str
    ref_audio: str = ""
    prompt_text: str = ""
    prompt_lang: str = ""
    sample_text: str = ""


class MainWindow(QMainWindow):
    # Populated by the widget builders before signals are connected.
    stage_label: QLabel
    pct_label: QLabel
    company_lbl: QLabel
    lbl_source_file: QLabel
    lbl_source_url: QLabel
    lbl_out: QLabel
    lbl_source: QLabel
    lbl_target: QLabel
    lbl_mode: QLabel
    lbl_asr: QLabel
    rec_lab: QLabel
    lbl_api: QLabel
    lbl_model: QLabel
    key_status: QLabel
    asr_help: QLabel
    lbl_zh_color: QLabel
    lbl_en_color: QLabel
    lbl_tts: QLabel
    lbl_voice: QLabel
    lbl_endpoint: QLabel
    lbl_ref: QLabel
    lbl_prompt: QLabel
    lbl_preview: QLabel
    tts_help: QLabel
    tts_sovits_status: QLabel
    logo_mark: QLabel
    source_lang_combo: QComboBox
    target_lang_combo: QComboBox
    mode_combo: QComboBox
    asr_backend_combo: QComboBox
    whisper_combo: QComboBox
    model_combo: QComboBox
    tts_combo: QComboBox
    tts_voice_edit: QComboBox
    theme_combo: QComboBox
    locale_combo: QComboBox
    url_edit: QLineEdit
    out_edit: QLineEdit
    key_edit: QLineEdit
    tts_endpoint_edit: QLineEdit
    tts_ref_edit: QLineEdit
    tts_prompt_edit: QLineEdit
    tts_sample_edit: QLineEdit
    lbl_sample: QLabel
    pause_btn: QPushButton
    resume_btn: QPushButton
    stop_btn: QPushButton
    browse_out_btn: QPushButton
    open_btn: QPushButton
    save_btn: QPushButton
    clear_key_btn: QPushButton
    api_portal_btn: QPushButton
    fetch_models_btn: QPushButton
    tts_preview_btn: QPushButton
    tts_ref_btn: QPushButton
    tts_sovits_probe_btn: QPushButton
    tts_sovits_start_btn: QPushButton
    github_btn: QToolButton
    burn_check: BrandCheck
    color_check: BrandCheck
    dub_check: BrandCheck
    refine_check: BrandCheck
    _slot_source: QWidget
    _slot_target: QWidget
    _slot_mode: QWidget
    _slot_asr: QWidget
    _slot_model: QWidget
    color_box: QWidget
    dub_box: QWidget
    _slot_tts: QWidget
    _slot_voice: QWidget
    _slot_endpoint: QWidget
    _slot_preview: QWidget
    sovits_box: QWidget
    _slot_ref: QWidget
    _slot_prompt: QWidget
    zh_color_btn: ColorChip
    en_color_btn: ColorChip
    download_btn: FilamentButton
    run_btn: FilamentButton
    start_btn: FilamentButton
    progress: QProgressBar
    log: QPlainTextEdit
    drop: DropCard
    form_scroll: QScrollArea
    more_box: QFrame
    deck_grid: QGridLayout

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1280, 860)
        self.setMinimumSize(960, 640)
        self._worker: PipelineWorker | None = None
        self._resume_config: JobConfig | None = None
        self._retry_translation = False
        self._gpu_key = "gpu_checking"
        self._gpu_name = ""
        self._task_started = False
        self._device_worker = DeviceProbeWorker(self)
        self._models_worker: ModelsWorker | None = None
        self._preview_worker: VoicePreviewWorker | None = None
        self._sovits_worker: SovitsBootWorker | None = None
        self._sovits_probe_worker: SovitsProbeWorker | None = None
        self._closing = False
        self._preview_player = PreviewPlayer(self)
        self._preview_player.started.connect(self._on_preview_started)
        self._preview_player.finished.connect(self._on_preview_played)
        self._preview_player.failed.connect(self._on_preview_fail)
        self._dl_worker: DownloadWorker | None = None
        self._last_output: Path | None = None
        self._last_result: JobResult | None = None
        self._last_signature: tuple | None = None
        self._running_signature: tuple | None = None
        self._last_log_stage: str | None = None
        self._bar_floor = 0
        self._stage_key = "waiting"
        self._stage_values: dict[str, object] = {}
        self._progress_stage = ""
        self._video: Path | None = None
        self._control: JobControl | None = None
        self._section_labels: dict[str, QLabel] = {}
        set_locale(DEFAULT_LOCALE)
        self._theme = load_ui_theme()

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(14)
        outer.addLayout(build_header(self))
        outer.addWidget(hairline("headerRule"))
        self.workspace_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.workspace_layout.setSpacing(14)
        self.form_scroll = WorkspaceScroll()
        self.form_scroll.setObjectName("formScroll")
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.form_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.form_scroll.viewport().setObjectName("formViewport")
        workspace = QWidget()
        workspace.setObjectName("workspace")
        flow = QVBoxLayout(workspace)
        flow.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        flow.setContentsMargins(0, 0, 8, 0)
        flow.setSpacing(12)
        flow.addWidget(build_source(self))
        flow.addWidget(build_deck(self))
        flow.addWidget(self.voice_card)
        flow.addWidget(self.settings_card)
        flow.addStretch(1)
        self.form_scroll.setWidget(workspace)
        self.workspace_layout.addWidget(self.form_scroll, 3)
        self.task_panel = build_stage(self)
        self.workspace_layout.addWidget(self.task_panel, 1)
        outer.addLayout(self.workspace_layout, 1)
        outer.addWidget(build_action_bar(self))

        icon = load_app_icon(self)
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.source_lang_combo.currentIndexChanged.connect(self._sync_dub_default)
        self.target_lang_combo.currentIndexChanged.connect(self._sync_dub_default)
        self.target_lang_combo.currentIndexChanged.connect(self._sync_preview_text)
        self.mode_combo.currentIndexChanged.connect(self._sync_output_name)
        self._apply_theme(persist=False)
        self._hydrate()
        self._sync_preview_text()
        self.retranslateUi()
        self._device_worker.result.connect(self._on_device_detected)
        self._device_worker.start()
        self._relayout_deck()
        from bilingual_sub.gui.widgets.field import protect_combo_scroll
        protect_combo_scroll(self)
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._keep_focus_visible)

    def _keep_focus_visible(self, old, current) -> None:
        if current is not None and self.form_scroll.widget().isAncestorOf(current):
            self.form_scroll.ensureWidgetVisible(current)

    def _show_stage(self, key: str, **values: object) -> None:
        if key != "waiting":
            self._show_task_activity()
        self._stage_key, self._stage_values, self._progress_stage = key, values, ""
        self.stage_label.setText(tr(key).format(**values))

    def _show_task_activity(self) -> None:
        self._task_started = True
        self.gpu_status.hide()
        self.log.setPlaceholderText(tr("log_ph"))
        self.task_activity.show()

    def _on_device_detected(self, key: str, name: str = "") -> None:
        from bilingual_sub.gui.hardware import short_device_name

        self._gpu_key = key
        self._gpu_name = name
        detail = short_device_name(name) or (tr("gpu_model_unknown") if key in {"gpu_apple", "gpu_cuda"} else "")
        self.gpu_status.setText(tr(key) + ("\n" + detail if detail else ""))

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout_deck()

    def _relayout_deck(self) -> None:
        if not hasattr(self, "task_panel"):
            return
        wide = self.width() >= 1180
        direction = QBoxLayout.Direction.LeftToRight if wide else QBoxLayout.Direction.TopToBottom
        if self.workspace_layout.direction() != direction:
            self.workspace_layout.setDirection(direction)
        self.task_panel.setMinimumWidth(300 if wide else 0)
        self.task_panel.setMaximumWidth(380 if wide else 16777215)
        # macOS font metrics need more room for the two hardware lines and
        # the log viewport padding than the former 228 px compact panel.
        self.task_panel.setMinimumHeight(0 if wide else 240)
        self.task_panel.setMaximumHeight(16777215 if wide else 240)
        self.form_scroll.widget().updateGeometry()

    def _set_key_status(self, text: str) -> None:
        self.key_status.setText(text)
        self.key_status.setVisible(bool(text))

    def _reveal_settings(self, field: QWidget) -> None:
        # Scroll the always-visible settings card into view before focusing.
        def reveal() -> None:
            self.form_scroll.ensureWidgetVisible(field, 16, 24)
            field.setFocus(Qt.FocusReason.OtherFocusReason)
        QTimer.singleShot(0, reveal)

    def _hydrate(self) -> None:
        if get_api_key():
            self.key_edit.setPlaceholderText(tr("token_kept"))
        zh, en = load_subtitle_colors()
        self.zh_color_btn.set_hex(zh)
        self.en_color_btn.set_hex(en)
        sovits = load_gptsovits_settings()
        if sovits.get("endpoint"):
            self.tts_endpoint_edit.setText(sovits["endpoint"])
        if sovits.get("ref_audio"):
            self.tts_ref_edit.setText(sovits["ref_audio"])
        if sovits.get("prompt_text"):
            self.tts_prompt_edit.setText(sovits["prompt_text"])
        self._sync_tts_fields()
        from bilingual_sub.adapters.tts.gptsovits_runtime import should_autostart

        if should_autostart():
            QTimer.singleShot(0, lambda: self._start_sovits(announce=False))

    def _persist_sub_color(self, which: str, color: str) -> None:
        key = "zh_color" if which == "zh" else "en_color"
        save_user_overrides({"style": {key: color}})

    def _apply_logo(self) -> None:
        pix = load_brand_mark(HEADER_MARK_PX, self, self._theme)
        if not pix.isNull():
            self.logo_mark.setPixmap(pix)
            self.logo_mark.setFixedSize(HEADER_MARK_PX, HEADER_MARK_PX)

    def _apply_github(self) -> None:
        pix = load_github_mark(GITHUB_MARK_PX, self, self._theme)
        if not pix.isNull():
            self.github_btn.setIcon(QIcon(pix))
            self.github_btn.setIconSize(QSize(GITHUB_MARK_PX, GITHUB_MARK_PX))

    def _open_api_portal(self) -> None:
        QDesktopServices.openUrl(QUrl(API_PORTAL_URL))

    def _open_github(self) -> None:
        QDesktopServices.openUrl(QUrl(GITHUB_URL))

    def _clear_key(self) -> None:
        delete_api_key()
        self.key_edit.clear()
        self.key_edit.setPlaceholderText(tr("token_ph"))
        self._set_key_status(tr("token_cleared"))

    def _apply_theme(self, persist: bool = True) -> None:
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(app_qss(self._theme))
        self._apply_logo()
        self._apply_github()
        self._refresh_drop()
        for widget in (
            self.run_btn,
            self.download_btn,
            self.burn_check,
            self.color_check,
            self.refine_check,
            self.dub_check,
            self.zh_color_btn,
            self.en_color_btn,
        ):
            apply = getattr(widget, "apply_theme", None)
            if callable(apply):
                apply(self._theme)
        if persist:
            save_user_overrides({"ui": {"theme": self._theme}})

    def _on_theme(self) -> None:
        self._theme = str(self.theme_combo.currentData() or "dark")
        self._apply_theme(persist=True)

    def _target_requires_dub(self) -> bool:
        source_lang = str(self.source_lang_combo.currentData() or "zh")
        target_lang = str(self.target_lang_combo.currentData() or "zh")
        return should_dub(source_lang, source_lang, target_lang)

    def _sync_dub_default(self) -> None:
        self.dub_check.setEnabled(self._target_requires_dub())
        if self._target_requires_dub():
            self.dub_check.setChecked(True)
        else:
            source_lang = str(self.source_lang_combo.currentData() or "zh")
            target_lang = str(self.target_lang_combo.currentData() or "zh")
            self.dub_check.setChecked(wants_spoken_target(source_lang, target_lang))
        # Changing between two dubbed languages need not toggle the checkbox.
        # Refresh engine name and endpoint visibility even when it stays checked.
        self._sync_tts_fields()

    def _refresh_drop(self) -> None:
        tones = tokens_for(self._theme)
        if self._video:
            self.drop.set_prompt(self._video.name, title_color=tones.ink, hint_color=tones.muted)
            self.drop.setToolTip(str(self._video))
        else:
            self.drop.set_prompt(tr("drop"), title_color=tones.ink, hint_color=tones.muted)

    def _sync_output_name(self) -> None:
        mode = str(self.mode_combo.currentData() or "bilingual")
        refreshed = refresh_output_path(self.out_edit.text(), self._video, mode)
        if str(refreshed) != self.out_edit.text():
            self.out_edit.setText(str(refreshed))

    def _output_mode(self) -> str:
        return str(self.mode_combo.currentData() or "bilingual")

    def _set_video(self, path: Path) -> None:
        out = next_output_path(self.out_edit.text(), self._video, path, mode=self._output_mode())
        self._video = path
        self._refresh_drop()
        self.out_edit.setText(str(out))

    def _sync_download(self) -> None:
        busy = self._job_busy()
        self.download_btn.setEnabled(bool(self.url_edit.text().strip()) and not busy)

    def _download(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, PRODUCT_ZH, tr("need_url"))
            return
        if self._job_busy():
            return
        dest = download_folder(url)
        self.download_btn.setEnabled(False)
        self._show_stage("ingest")
        self.progress.setValue(0)
        self.pct_label.setText(format_pct(0))
        self._bar_floor = 0
        self._set_stage_failed(False)
        self._last_log_stage = None
        source_lang = str(self.source_lang_combo.currentData() or "zh")
        self._dl_worker = DownloadWorker(url, dest, source_lang=source_lang)
        self._control = self._dl_worker.control
        self._dl_worker.progress.connect(self._on_progress)
        self._dl_worker.ok.connect(self._on_downloaded)
        self._dl_worker.fail.connect(self._on_download_fail)
        self._dl_worker.finished.connect(self._on_download_finished)
        self._dl_worker.start()
        self._set_running_ui(True)

    def _on_download_finished(self) -> None:
        if self.sender() is not None and self.sender() is not self._dl_worker:
            return
        self._dl_worker = None
        if not self._job_busy():
            self._release_job()

    def _on_downloaded(self, path: str) -> None:
        if self.sender() is not None and self.sender() is not self._dl_worker:
            return
        self._sync_download()
        self._set_video(Path(path))
        self.progress.setValue(100)
        self.pct_label.setText(format_pct(100))
        self._show_stage("ingest")
        self._log_line(f"{tr('ingest')}  {path}")

    def _on_download_fail(self, msg: str) -> None:
        if self.sender() is not None and self.sender() is not self._dl_worker:
            return
        self._sync_download()
        self.progress.setValue(0)
        self.pct_label.setText(format_pct(0))
        self._bar_floor = 0
        stopped = bool(self._control and self._control.is_stopped()) or msg in {tr("stop"), "job stopped"}
        self._show_stage("stop" if stopped else "waiting")
        if not stopped and not self._closing:
            QMessageBox.warning(self, PRODUCT_ZH, redact_api_key(msg, get_api_key()))

    def _job_signature(self) -> tuple:
        video = ""
        video_revision: tuple = ()
        if self._video is not None:
            try:
                video = str(self._video.resolve())
                if self._video.is_file():
                    stat = self._video.stat()
                    video_revision = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                video = str(self._video)
        url = ""
        if not (self._video and self._video.is_file()):
            url = self.url_edit.text().strip()
        dubbing = bool(self.dub_check.isChecked() or self._target_requires_dub())
        assets: tuple
        try:
            glossary = default_glossary_path()
            ref = Path(self.tts_ref_edit.text().strip())
            assets = (
                load_settings().model_dump(), load_style_preset("no-plate-large").model_dump(),
                hashlib.sha256(glossary.read_bytes()).hexdigest() if glossary.is_file() else "",
                hashlib.sha256(ref.read_bytes()).hexdigest() if dubbing and ref.is_file() else "",
            )
        except Exception:
            # A broken or concurrently edited configuration cannot authorize reuse.
            # The processing worker will report its actual configuration error.
            assets = (object(),)
        return (
            video,
            video_revision,
            assets,
            url,
            self.whisper_combo.currentText(),
            self.model_combo.currentText().strip(),
            str(self.source_lang_combo.currentData() or "zh"),
            str(self.target_lang_combo.currentData() or "zh"),
            str(self.mode_combo.currentData() or "bilingual"),
            str(self.asr_backend_combo.currentData() or "whisper"),
            bool(self.refine_check.isChecked()),
            bool(self.burn_check.isChecked()),
            bool(self.dub_check.isChecked()),
            self.zh_color_btn.hex(),
            self.en_color_btn.hex(),
            self.tts_ref_edit.text().strip() if dubbing else "",
            self.tts_prompt_edit.text().strip() if dubbing else "",
            self._sovits_endpoint() if dubbing else "",
        )

    def _reuse_sources(self) -> tuple[Path | None, Path | None, Path | None, Path | None] | None:
        result = self._last_result
        if result is None or self._last_signature != self._job_signature() or self._job_busy():
            return None
        mp4, srt, ass, dub = result.output_mp4, result.output_srt, result.output_ass, result.output_dub
        if not any(path is not None and path.is_file() for path in (mp4, srt, ass)):
            return None
        source_lang = str(self.source_lang_combo.currentData() or "zh")
        mode = str(self.mode_combo.currentData() or "bilingual")
        target_lang = effective_target_lang(
            source_lang,
            str(self.target_lang_combo.currentData() or "zh"),
            mode,
        )
        if source_lang != "auto" and (not translation_needed(source_lang, target_lang, mode)) and getattr(result, "translated", False):
            return None
        return mp4, srt, ass, dub

    def _try_relocate_outputs(self, dest_mp4: Path, *, log: bool = False) -> bool:
        sources = self._reuse_sources()
        if sources is None or self._last_result is None:
            return False
        src_mp4, src_srt, src_ass, src_dub = sources
        try:
            copied = copy_finished_outputs(
                dest_mp4,
                src_mp4=src_mp4,
                src_srt=src_srt,
                src_ass=src_ass,
                src_dub=src_dub,
                protected_inputs=(self._video,) if self._video is not None else (),
                report_path=self._last_result.report_path,
                job_id=self._last_result.job_id,
                source_video=self._video,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, PRODUCT_ZH, tr("out_mkdir").format(exc=exc))
            return False
        if not copied:
            return False
        dest_srt = sidecar_srt(dest_mp4)
        self._last_result = replace(
            self._last_result,
            output_mp4=copied.get("mp4", src_mp4),
            output_srt=copied.get("srt", self._last_result.output_srt),
            output_ass=copied.get("ass", self._last_result.output_ass),
            output_dub=copied.get("dub", src_dub),
            reused=True,
        )
        self._last_output = self._last_result.output_mp4 or self._last_result.output_dub or dest_srt
        self.open_btn.setEnabled(True)
        self.out_edit.setText(str(dest_mp4))
        if log and self._last_result is not None:
            self._show_stage("done_stage", n=self._last_result.cue_count)
            self._log_line(tr("reused_log").format(n=self._last_result.cue_count))
            self.progress.setValue(100)
            self.pct_label.setText(format_pct(100))
            self._set_stage_failed(False)
        return True

    def _on_out_path_committed(self) -> None:
        if self._job_busy() or self._last_result is None:
            return
        try:
            dest = resolve_output_mp4(self.out_edit.text(), self._video, mode=self._output_mode())
        except ValueError:
            return
        if self._video and dest.resolve() == self._video.resolve():
            return
        self._try_relocate_outputs(dest, log=True)

    def _browse_output(self) -> None:
        start = self.out_edit.text().strip()
        if start:
            start_path = Path(start).expanduser()
            start = str(start_path if start_path.is_dir() else start_path.parent)
        elif self._video:
            start = str(self._video.parent)
        else:
            start = str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, tr("select_out"), start)
        if not folder:
            return
        chosen = relocate_output(self.out_edit.text(), Path(folder), self._video, mode=self._output_mode())
        self.out_edit.setText(str(chosen))
        self._try_relocate_outputs(chosen, log=True)
        self.out_edit.setFocus()

    def _save_key(self) -> None:
        key = self.key_edit.text().strip()
        if not key:
            QMessageBox.warning(self, PRODUCT_ZH, tr("need_token"))
            return
        set_api_key(key)
        self.key_edit.clear()
        self.key_edit.setPlaceholderText(tr("token_kept"))
        self._set_key_status(tr("token_saved"))

    def _refresh_models(self) -> None:
        if self._models_worker and self._models_worker.isRunning():
            return
        if not get_api_key() and not self.key_edit.text().strip():
            self._set_key_status(tr("need_token"))
            return
        if self.key_edit.text().strip():
            set_api_key(self.key_edit.text().strip())
            self.key_edit.clear()
            self.key_edit.setPlaceholderText(tr("token_kept"))
        self.fetch_models_btn.setEnabled(False)
        self._set_key_status(tr("fetching_models"))
        self._models_worker = ModelsWorker()
        self._models_worker.ok.connect(self._on_models)
        self._models_worker.fail.connect(self._on_models_fail)
        self._models_worker.start()

    def _on_models(self, models: list) -> None:
        self.fetch_models_btn.setEnabled(True)
        current = self.model_combo.currentText().strip()
        items = merge_model_list([str(m) for m in models], current)
        pick = preferred_model(items, current)
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        if items:
            self.model_combo.addItems(items)
            if pick:
                self.model_combo.setCurrentText(pick)
            else:
                self.model_combo.setCurrentIndex(-1)
            self._set_key_status("")
            QTimer.singleShot(0, self.model_combo.showPopup)
        else:
            self._set_key_status(tr("models_empty"))
        self.model_combo.blockSignals(False)

    def _on_models_fail(self, msg: str) -> None:
        self.fetch_models_btn.setEnabled(True)
        self._set_key_status(tr("models_fail").format(msg=msg))

    def _persist_model(self, *_args: object) -> None:
        model = self.model_combo.currentText().strip()
        if model:
            save_user_overrides({"translate": {"model": model}})

    def _on_locale(self) -> None:
        code = str(self.locale_combo.currentData() or "zh-Hans")
        set_locale(code)
        self.retranslateUi()

    def retranslateUi(self) -> None:
        self._on_device_detected(self._gpu_key, self._gpu_name)
        self.locale_combo.setAccessibleName(tr("ui_lang"))
        self.theme_combo.setItemText(0, tr("theme_light"))
        self.theme_combo.setItemText(1, tr("theme_dark"))
        for key, label in self._section_labels.items():
            label.setText(tr(key))
        self.voice_note.setText(tr("ui_original_voice"))
        self.lbl_api.setText(tr("api"))
        self.asr_help.setText(tr("asr_help"))
        self.tts_help.setText(tr("tts_help"))
        for key, i18n_key in {
            "models": "models",
            "out": "out",
        }.items():
            label = self._section_labels.get(key)
            if label:
                label.setText(tr(i18n_key))
        self.url_edit.setPlaceholderText(tr("url_ph"))
        self.download_btn.setText(tr("download"))
        self.lbl_source_file.setText(tr("source_file"))
        self.lbl_source_url.setText(tr("source_url"))
        self._refresh_drop()
        self.lbl_out.setText(tr("out"))
        self.lbl_source.setText(tr("source"))
        self.lbl_target.setText(tr("target"))
        self.lbl_mode.setText(tr("mode"))
        for index in range(self.mode_combo.count()):
            data = self.mode_combo.itemData(index)
            if data == "bilingual":
                self.mode_combo.setItemText(index, tr("mode_bi"))
            elif data == "enzh":
                self.mode_combo.setItemText(index, tr("mode_enzh"))
            elif data == "netflix_single":
                self.mode_combo.setItemText(index, tr("mode_nf"))
        if get_api_key() and not self.key_edit.text().strip():
            self.key_edit.setPlaceholderText(tr("token_kept"))
        else:
            self.key_edit.setPlaceholderText(tr("token_ph"))
        self.save_btn.setText(tr("save_token"))
        self.clear_key_btn.setText(tr("clear_token"))
        self.api_portal_btn.setText(tr("api_portal"))
        self.github_btn.setToolTip(tr("github"))
        self.model_combo.setPlaceholderText(tr("model_ph"))
        self.out_edit.setPlaceholderText(tr("out_ph"))
        self.fetch_models_btn.setText(tr("fetch_models"))
        self.rec_lab.setText(tr("asr"))
        self.lbl_asr.setText(tr("engine"))
        self.asr_backend_combo.setItemText(0, tr("engine_whisper"))
        self.asr_backend_combo.setItemText(1, tr("engine_whisperx"))
        self.lbl_model.setText(tr("models"))
        self.burn_check.setText(tr("burn"))
        self.color_check.setText(tr("sub_color"))
        self.refine_check.setText(tr("refine"))
        self.dub_check.setText(tr("dub"))
        self.lbl_zh_color.setText(tr("zh_color"))
        self.lbl_en_color.setText(tr("en_color"))
        self.lbl_tts.setText(tr("tts_provider"))
        self.lbl_voice.setText(tr("tts_voice"))
        self.lbl_endpoint.setText(tr("tts_endpoint"))
        self.lbl_ref.setText(tr("tts_ref_audio"))
        self.lbl_prompt.setText(tr("tts_prompt"))
        self.lbl_sample.setText(tr("tts_sample"))
        self.tts_sample_edit.setToolTip(tr("tts_sample_tip"))
        self.lbl_preview.setText(tr("tts_preview"))
        self._sync_tts_fields()
        if not self._preview_busy():
            self.tts_preview_btn.setText(tr("tts_preview"))
        self.tts_ref_btn.setText(tr("browse"))
        self.tts_prompt_edit.setPlaceholderText(tr("tts_prompt_ph"))
        self.tts_sovits_probe_btn.setText(tr("tts_sovits_probe"))
        self.tts_sovits_start_btn.setText(tr("tts_sovits_start"))
        if self.tts_endpoint_edit.placeholderText() == "":
            self.tts_endpoint_edit.setPlaceholderText(DEFAULT_ENDPOINT)
        self.browse_out_btn.setText(tr("browse"))
        self.run_btn.setText(tr("start"))
        self.pause_btn.setText(tr("pause"))
        self.resume_btn.setText(tr("resume"))
        self.stop_btn.setText(tr("stop"))
        self.open_btn.setText(tr("open"))
        self.stage_label.setText(stage_text(self._progress_stage) if self._progress_stage else
                                 tr(self._stage_key).format(**self._stage_values))
        self.log.setPlaceholderText(tr("log_ph") if self._task_started else "")
        self.drop.setAccessibleName(tr("drop"))
        self.url_edit.setAccessibleName(tr("source_url"))
        self.out_edit.setAccessibleName(tr("out"))
        self.progress.setAccessibleName(tr("ui_task"))
        self.log.setAccessibleName(tr("ui_log"))
        for label in self.findChildren(QLabel, "fieldLabel"):
            if label.buddy() is not None:
                label.buddy().setAccessibleName(label.text())

    def _toggle_color(self, checked: bool) -> None:
        self.color_box.setVisible(checked)
        if self.more_box.isVisible():
            self._relayout_deck()

    def _toggle_dub(self, checked: bool) -> None:
        required = self._target_requires_dub()
        if checked != required:
            self.dub_check.blockSignals(True)
            self.dub_check.setChecked(required)
            self.dub_check.blockSignals(False)
            checked = required
        self.dub_box.setVisible(checked)
        self.voice_note.setVisible(not checked)
        self._sync_tts_fields()

    def _sync_tts_fields(self) -> None:
        engine = self._tts_engine()
        if engine != getattr(self, "_displayed_tts_engine", engine):
            self.tts_sovits_status.clear()
            self._stop_voice_preview()
        self._displayed_tts_engine = engine
        on = self.dub_check.isChecked() or self._target_requires_dub()
        self.dub_box.setVisible(on)
        self.voice_note.setVisible(not on)
        self.tts_combo.setEnabled(on)
        native = self._tts_engine() == 'qwen3-native'
        previous_voice = self.tts_voice_edit.currentData()
        self.tts_voice_edit.blockSignals(True)
        self.tts_voice_edit.clear()
        self.tts_voice_edit.addItem(tr('tts_auto_voice'), '')
        from bilingual_sub.adapters.tts.qwen import standard_voices

        for voice in standard_voices(str(self.target_lang_combo.currentData() or 'zh')):
            origin = tr('tts_origin_' + voice.origin)
            label = f"{voice.name} · {tr('tts_' + voice.gender)} · {origin}"
            if voice.designed:
                label = f"SubFlow · {origin} · {tr('tts_' + voice.gender)} · {tr('tts_designed')}"
            self.tts_voice_edit.addItem(label, voice.name)
            self.tts_voice_edit.setItemData(self.tts_voice_edit.count() - 1,
                tr('tts_designed_tip' if voice.designed else 'tts_voice_origin_tip').format(language=origin), Qt.ItemDataRole.ToolTipRole)
        self.tts_voice_edit.setCurrentIndex(max(0, self.tts_voice_edit.findData(previous_voice)))
        self.tts_voice_edit.blockSignals(False)
        self.tts_combo.setItemText(self.tts_combo.findData('qwen3-native'), tr('tts_standard'))
        self.tts_combo.setItemText(self.tts_combo.findData('qwen3'), tr('tts_clone'))
        self.tts_voice_edit.setEnabled(on and native)
        self.tts_endpoint_edit.setEnabled(on)
        self._slot_voice.setVisible(on and native)
        self._slot_endpoint.setVisible(on and self._tts_engine() == "gptsovits")
        self._slot_ref.setVisible(on and not native)
        self._slot_prompt.setVisible(on and not native)
        self._slot_preview.setVisible(on)
        self.sovits_box.setVisible(on)
        self.tts_preview_btn.setEnabled(on and not self._preview_busy())
        self._relayout_deck()

    def _sync_preview_text(self) -> None:
        from bilingual_sub.core.voice_preview import preview_sample

        self.tts_sample_edit.setText(preview_sample(str(self.target_lang_combo.currentData() or "zh")))
        self._stop_voice_preview()
        self._set_preview_busy(False)

    def _preview_request(self) -> PreviewRequest:
        lang = str(self.target_lang_combo.currentData() or "zh")
        source = str(self.source_lang_combo.currentData() or "")
        prompt_lang = "" if source in {"", "auto"} else source
        return PreviewRequest(
            self._tts_engine(),
            str(self.tts_voice_edit.currentData() or '') if self._tts_engine() == 'qwen3-native' else '',
            lang,
            self._sovits_endpoint(),
            '' if self._tts_engine() == 'qwen3-native' else self.tts_ref_edit.text().strip(),
            '' if self._tts_engine() == 'qwen3-native' else self.tts_prompt_edit.text().strip(),
            prompt_lang,
            self.tts_sample_edit.text().strip(),
        )

    def _persist_sovits(self) -> None:
        source = str(self.source_lang_combo.currentData() or "")
        save_gptsovits_settings(
            endpoint=self.tts_endpoint_edit.text().strip() or DEFAULT_ENDPOINT,
            ref_audio=self.tts_ref_edit.text().strip(),
            prompt_text=self.tts_prompt_edit.text().strip(),
            prompt_lang="" if source in {"", "auto"} else source,
        )

    def _browse_ref_audio(self) -> None:
        start = self.tts_ref_edit.text().strip()
        if start:
            start_path = Path(start).expanduser()
            start = str(start_path if start_path.is_dir() else start_path.parent)
        else:
            start = str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("select_ref"),
            start,
            "Audio (*.wav *.mp3 *.flac *.m4a *.ogg *.aac);;All (*.*)",
        )
        if not path:
            return
        self.tts_ref_edit.setText(path)
        self._persist_sovits()

    def _sovits_endpoint(self) -> str:
        from bilingual_sub.adapters.tts.routing import provider_endpoint

        return provider_endpoint(self._tts_engine(), self.tts_endpoint_edit.text().strip())

    def _tts_engine(self) -> str:
        from bilingual_sub.adapters.tts.routing import resolve_provider

        return resolve_provider(str(self.tts_combo.currentData() or 'qwen3-native'), str(self.target_lang_combo.currentData() or "zh"),
                                str(self.source_lang_combo.currentData() or "auto"))

    def _probe_sovits(self) -> None:
        if self._closing or (self._sovits_probe_worker and self._sovits_probe_worker.isRunning()):
            return
        self._sovits_probe_worker = SovitsProbeWorker(self._sovits_endpoint(), self._tts_engine())
        self._sovits_probe_worker.result.connect(self._on_sovits_probe)
        self._sovits_probe_worker.start()

    def _tts_status_text(self, key: str) -> str:
        return tr(key).format(engine=self.tts_combo.currentText())

    def _on_sovits_probe(self, ready: bool, detail: str) -> None:
        worker = self.sender()
        if worker is not None and getattr(worker, "provider", self._tts_engine()) != self._tts_engine():
            return
        if ready:
            status = self._tts_status_text("tts_sovits_ready")
            device = ('NVIDIA GPU (CUDA)' if detail.startswith('cuda') else
                      'Apple GPU (MPS)' if detail == 'mps' else 'CPU' if detail == 'cpu' else '')
            self.tts_sovits_status.setText(status + (f' · {device}' if device else ''))
            self._log_line(self.tts_sovits_status.text())
            return
        self.tts_sovits_status.setText(detail or self._tts_status_text("tts_sovits_down"))

    def _start_sovits(self, *args, announce: bool = True) -> None:
        if self._closing:
            return
        if self._sovits_worker is not None and self._sovits_worker.isRunning():
            return
        self._sovits_announce = announce
        self.tts_sovits_status.setText(self._tts_status_text("tts_sovits_starting"))
        self._sovits_worker = SovitsBootWorker(self._sovits_endpoint(), self._tts_engine())
        self._sovits_worker.progress.connect(self._on_sovits_boot_progress)
        self._sovits_worker.progress.connect(self._log_line)
        self._sovits_worker.ok.connect(self._on_sovits_boot)
        self._sovits_worker.fail.connect(self._on_sovits_boot_fail)
        self._sovits_worker.start()

    def _on_sovits_boot_progress(self, message: str) -> None:
        worker = self.sender()
        if worker is None or getattr(worker, "provider", self._tts_engine()) == self._tts_engine():
            self.tts_sovits_status.setText(message)

    def _on_sovits_boot(self, kind: str) -> None:
        worker = self.sender()
        if worker is not None and getattr(worker, "provider", self._tts_engine()) != self._tts_engine():
            return
        if kind == "ready":
            self.tts_sovits_status.setText(self._tts_status_text("tts_sovits_ready"))
        else:
            self.tts_sovits_status.setText(self._tts_status_text("tts_sovits_started"))
        if getattr(self, "_sovits_announce", True):
            self._log_line(self.tts_sovits_status.text())
        self._probe_sovits()

    def _on_sovits_boot_fail(self, msg: str) -> None:
        worker = self.sender()
        if worker is not None and getattr(worker, "provider", self._tts_engine()) != self._tts_engine():
            return
        self.tts_sovits_status.setText(msg)
        self._set_key_status(tr("tts_preview_fail").format(msg=msg))
        if getattr(self, "_sovits_announce", True):
            self._log_line(tr("tts_preview_fail").format(msg=msg))

    def _preview_busy(self) -> bool:
        return self._preview_player.is_active() or bool(self._preview_worker is not None and self._preview_worker.isRunning())

    def _set_preview_busy(self, busy: bool) -> None:
        self.tts_preview_btn.setText(tr("tts_previewing") if busy else tr("tts_preview"))
        on = self.dub_check.isChecked() or self._target_requires_dub()
        self.tts_preview_btn.setEnabled(on and not busy)

    def _stop_voice_preview(self) -> None:
        self._preview_player.stop()
        worker = self._preview_worker
        if worker is not None:
            if hasattr(worker, "control"):
                worker.control.stop()
            try:
                worker.ok.disconnect()
                worker.fail.disconnect()
            except RuntimeError:
                pass

    def _preview_voice(self) -> None:
        if self._preview_busy():
            return
        req = self._preview_request()
        ref = req.ref_audio
        video = self._video if self._video and self._video.is_file() else None
        if req.provider != 'qwen3-native' and ((ref and not Path(ref).expanduser().is_file()) or (not ref and video is None)):
            self._set_key_status(tr("tts_sovits_need_ref"))
            show_error(self, f"参考音频不存在：{ref}" if ref else tr("tts_sovits_need_ref"), preview=True)
            return
        self._persist_sovits()
        if self.key_edit.text().strip():
            set_api_key(self.key_edit.text().strip())
            self.key_edit.clear()
            self.key_edit.setPlaceholderText(tr("token_kept"))
        self._stop_voice_preview()
        self._set_preview_busy(True)
        self._preview_worker = VoicePreviewWorker(
            req.provider,
            req.voice,
            req.lang,
            req.endpoint,
            req.ref_audio,
            req.prompt_text,
            req.prompt_lang,
            sample_text=req.sample_text,
              **({"video": video} if not ref and req.provider != 'qwen3-native' else {}),
        )
        self._preview_worker.ok.connect(self._on_preview_ready)
        self._preview_worker.fail.connect(self._on_preview_fail)
        self._preview_worker.progress.connect(self._on_preview_progress)
        self._preview_worker.start()

    def _on_preview_progress(self, stage: str, pct: float) -> None:
        worker = self._preview_worker
        if (self._closing or self.sender() is not worker or worker is None
                or worker.control.is_stopped()
                or worker.lang != str(self.target_lang_combo.currentData() or "zh")):
            return
        self.tts_sovits_status.setText(stage_text(stage))

    def _on_preview_ready(self, path: str) -> None:
        if self._closing:
            return
        worker = self.sender()
        if worker is not None and worker is not self._preview_worker:
            return
        req = self._preview_request()
        voice = req.voice
        if isinstance(worker, VoicePreviewWorker) and any(
            getattr(worker, field) != getattr(req, field)
            for field in ("provider", "voice", "lang", "endpoint", "ref_audio", "prompt_text", "prompt_lang", "sample_text")
        ):
            self._set_preview_busy(False)
            return
        if isinstance(worker, VoicePreviewWorker) and worker.provider != 'qwen3-native' and not worker.ref_audio and worker.video != self._video:
            self._set_preview_busy(False)
            return
        audio = Path(path)
        if not audio.is_file():
            self._on_preview_fail(tr("tts_preview_fail").format(msg=path))
            return
        self._preview_voice_label = voice or "GPT-SoVITS"
        self._preview_player.play(audio)

    def _on_preview_started(self) -> None:
        self._log_line(tr("tts_preview_ok").format(voice=self._preview_voice_label))

    def _on_preview_played(self) -> None:
        self._set_preview_busy(False)

    def _on_preview_fail(self, msg: str) -> None:
        if self._closing:
            return
        worker = self.sender()
        if isinstance(worker, VoicePreviewWorker) and worker is not self._preview_worker:
            return
        self._set_preview_busy(False)
        safe = redact_api_key(msg, get_api_key())
        if safe in {tr("need_token"), "请先保存 API 令牌"}:
            self._set_key_status(tr("need_token"))
            return
        self._set_key_status(tr("tts_preview_fail").format(msg=safe))
        self._log_line(tr("tts_preview_fail").format(msg=safe))
        show_error(self, safe, preview=True)

    def closeEvent(self, event) -> None:  # noqa: N802
        from bilingual_sub.adapters.tts import qwen_runtime
        from bilingual_sub.adapters.tts.gptsovits_runtime import request_shutdown, stop_servers

        workers = (self._worker, self._models_worker, self._preview_worker, self._device_worker,
                   self._sovits_worker, self._sovits_probe_worker, self._dl_worker)
        if not self._closing:
            self._closing = True
            self._stop_voice_preview()
            if self._control:
                self._control.stop()
            for worker in workers:
                if worker is not None and hasattr(worker, "control"):
                    worker.control.stop()
            request_shutdown()
            qwen_runtime.request_shutdown()
        if any(worker is not None and worker.isRunning() for worker in workers):
            # Keep QThreads alive until cooperative cancellation has completed.
            event.ignore()
            self.setEnabled(False)
            QTimer.singleShot(100, self.close)
            return
        stop_servers()
        qwen_runtime.stop_servers()
        super().closeEvent(event)

    def _job_busy(self) -> bool:
        return self._dl_worker is not None or bool(self._worker is not None and self._worker.isRunning())

    def _set_running_ui(self, running: bool, paused: bool = False, stopping: bool = False) -> None:
        busy = bool(running or stopping)
        self.run_btn.setEnabled(not busy)
        self.pause_btn.setEnabled(bool(running) and not paused and not stopping)
        self.resume_btn.setEnabled((bool(running) and paused and not stopping)
                                  or (not busy and not self._job_busy() and self._resume_config is not None))
        self.resume_btn.setToolTip(tr("resume_translation") if self._resume_config is not None else tr("resume"))
        self.stop_btn.setEnabled(bool(running) and not stopping)
        self.run_btn.update()
        self._sync_download()

    def _release_job(self) -> None:
        worker = self._worker
        if isinstance(worker, QThread):
            # finished is emitted before native thread-local cleanup completes.
            # Keep Qt ownership until the native thread has fully terminated.
            if worker.isRunning():
                return
            worker.wait()
            worker.deleteLater()
        if worker is not None and getattr(worker, "work_dir", None) is not None:
            import json

            try:
                state = json.loads((worker.work_dir / "job_state.json").read_text(encoding="utf-8"))
                completed = state.get("completed_stage", state.get("stage"))
                translation = (state.get("artifact_contexts") or {}).get("translate") or {}
                retry = self._retry_translation or bool(translation.get("missing"))
                from bilingual_sub.pipeline import STAGES

                if retry and completed in STAGES and STAGES.index(completed) >= STAGES.index("glossary"):
                    self._resume_config = replace(worker.config, work_dir=worker.work_dir, resume_from="translate")
                    self._log_line(tr("resume_translation"))
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        self._worker = None
        self._control = None
        self._set_running_ui(False)

    def _is_current_worker(self) -> bool:
        worker = self.sender()
        return worker is None or worker is self._worker

    def _on_worker_finished(self) -> None:
        if not self._is_current_worker():
            return
        if not self._job_busy():
            self._release_job()

    def _set_stage_failed(self, failed: bool) -> None:
        self.stage_label.setProperty("failed", failed)
        self.stage_label.style().unpolish(self.stage_label)
        self.stage_label.style().polish(self.stage_label)

    def _pause(self) -> None:
        if self._control is None or self._control.is_stopped():
            return
        self._control.pause()
        self._set_running_ui(True, paused=True)
        self._log_line(tr("pause"))

    def _resume(self) -> None:
        if not self._job_busy() and self._resume_config is not None:
            cfg = self._resume_config
            if self.key_edit.text().strip():
                set_api_key(self.key_edit.text().strip())
            self._bar_floor = 60
            self.progress.setValue(60)
            self.pct_label.setText(format_pct(60))
            self._last_log_stage = None
            self._show_stage("translate")
            self._log_line(tr("resume_translation_running"))
            self._launch_job(cfg)
            return
        if self._control is None or self._control.is_stopped():
            return
        self._control.resume()
        self._set_running_ui(True, paused=False)
        self._log_line(tr("resume"))

    def _stop(self) -> None:
        self._retry_translation = self._retry_translation or self._progress_stage == "translate"
        if self._control is not None:
            self._control.stop()
        self._show_stage("stop")
        self._set_stage_failed(False)
        if tr("stop") not in self.log.toPlainText().splitlines()[-3:]:
            self._log_line(tr("stop"))
        if self._job_busy():
            self._set_running_ui(True, stopping=True)
            return
        self._release_job()

    def _start(self) -> None:
        if self._job_busy():
            return
        url = self.url_edit.text().strip()
        if (not self._video or not self._video.is_file()) and not url:
            QMessageBox.warning(self, PRODUCT_ZH, tr("need_video"))
            return
        source_lang = str(self.source_lang_combo.currentData() or "zh")
        subtitle_mode = str(self.mode_combo.currentData() or "bilingual")
        target_lang = effective_target_lang(
            source_lang,
            str(self.target_lang_combo.currentData() or "zh"),
            subtitle_mode,
        )
        must_dub = should_dub(source_lang, source_lang, target_lang)
        need_xl8 = token_required_for_job(
            source_lang,
            target_lang,
            subtitle_mode,
            enable_dub=must_dub or self.dub_check.isChecked(),
            tts_provider=self._tts_engine(),
        )
        if need_xl8 and not get_api_key() and not self.key_edit.text().strip():
            self._reveal_settings(self.key_edit)
            QMessageBox.warning(self, PRODUCT_ZH, tr("need_token"))
            return
        if self.key_edit.text().strip():
            set_api_key(self.key_edit.text().strip())

        model = self.model_combo.currentText().strip()
        if need_xl8 and not model:
            self._reveal_settings(self.model_combo)
            QMessageBox.warning(self, PRODUCT_ZH, tr("need_model"))
            return
        if model:
            save_user_overrides({"translate": {"model": model}})

        if not self.out_edit.text().strip() and url and not self._video:
            from bilingual_sub.adapters.ytdlp import media_slug

            self.out_edit.setText(
                str(
                    Path.home()
                    / "Downloads"
                    / f"{media_slug(url)}{output_stem_suffix(subtitle_mode)}.mp4"
                )
            )
        try:
            out_mp4 = resolve_output_mp4(self.out_edit.text(), self._video, mode=subtitle_mode)
        except ValueError:
            QMessageBox.warning(self, PRODUCT_ZH, tr("need_out"))
            return
        if self._video and out_mp4.resolve() == self._video.resolve():
            QMessageBox.warning(self, PRODUCT_ZH, tr("out_same"))
            return
        try:
            out_mp4.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, PRODUCT_ZH, tr("out_mkdir").format(exc=exc))
            return
        self.out_edit.setText(str(out_mp4))
        if self._try_relocate_outputs(out_mp4, log=True):
            return
        self._last_log_stage = None
        subtitle_mode = str(self.mode_combo.currentData() or "bilingual")
        source_lang = str(self.source_lang_combo.currentData() or "zh")
        target_lang = effective_target_lang(
            source_lang,
            str(self.target_lang_combo.currentData() or "zh"),
            subtitle_mode,
        )
        must_dub = should_dub(source_lang, source_lang, target_lang)
        tts = self._tts_engine() if must_dub or self.dub_check.isChecked() else "none"
        if tts != "none":
            self._persist_sovits()
        cfg = JobConfig(
            input_video=self._video or Path(url),
            output_video=out_mp4 if self.burn_check.isChecked() else None,
            output_srt=out_mp4.with_name(out_mp4.stem + ".bilingual.srt"),
            work_dir=Path("auto"),
            whisper_model=self.whisper_combo.currentText(),
            translate_model=model,
            burn=self.burn_check.isChecked(),
            source_lang=source_lang,
            target_lang=target_lang,
            subtitle_mode=subtitle_mode,
            asr_backend="whisperx" if self.asr_backend_combo.currentData() == "whisperx" else "whisper",
            refine_translate=self.refine_check.isChecked(),
            source_url=url or None,
            glossary_path=None,
            glossary_generate=False,
            enable_dub=must_dub or (self.dub_check.isChecked() and tts != "none"),
            tts_provider=tts,  # type: ignore[arg-type]
            tts_voice=str(self.tts_voice_edit.currentData() or '') if tts == 'qwen3-native' else '',
            tts_endpoint=self._sovits_endpoint() if tts != "none" else "",
            tts_ref_audio="" if tts == "qwen3-native" else self.tts_ref_edit.text().strip(),
            tts_prompt_text="" if tts == "qwen3-native" else self.tts_prompt_edit.text().strip(),
            tts_prompt_lang=(
                ""
                if tts == "qwen3-native" or source_lang in {"", "auto"}
                else source_lang
            ),
            ui_locale=str(self.locale_combo.currentData() or "zh-Hans"),
            subtitle_zh_color=self.zh_color_btn.hex(),
            subtitle_en_color=self.en_color_btn.hex(),
        )
        if self._video and self._video.is_file():
            cfg.source_url = None
        self.log.clear()
        self.progress.setValue(0)
        self.pct_label.setText(format_pct(0))
        self._bar_floor = 0
        self._show_stage("starting")
        self._launch_job(cfg)

    def _launch_job(self, cfg: JobConfig) -> None:
        self._resume_config = None
        self._retry_translation = False
        self._set_stage_failed(False)
        self._control = JobControl()
        self._set_running_ui(True, paused=False)
        self._worker = PipelineWorker(cfg, self._control, parent=self)
        if not cfg.resume_from:
            self._running_signature = self._job_signature()
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_progress(self, stage: str, pct: float) -> None:
        if self._closing or not self._is_current_worker() or (self._control and self._control.is_stopped()):
            return
        self._show_task_activity()
        label = stage_text(stage)
        shown = max(self._bar_floor, max(0, min(100, int(pct * 100))))
        self._bar_floor = shown
        self.progress.setValue(shown)
        self.pct_label.setText(format_pct(shown))
        self._progress_stage = stage
        self.stage_label.setText(label)
        self._set_stage_failed(False)
        if should_log_stage(stage, self._last_log_stage):
            self._log_line(label)
            self._last_log_stage = stage

    def _on_done(self, result: object) -> None:
        if not self._is_current_worker():
            return
        assert isinstance(result, JobResult)
        self._retry_translation = bool(result.missing_en)
        self._set_running_ui(False)
        self.progress.setValue(100)
        self.pct_label.setText(format_pct(100))
        self._show_stage("done_stage", n=result.cue_count)
        self._set_stage_failed(False)
        folder = result.output_mp4 or result.output_srt
        self._last_output = folder
        self._last_result = result
        self._last_signature = self._running_signature or self._job_signature()
        self.open_btn.setEnabled(True)
        if result.reused:
            self._log_line(tr("reused_log").format(n=result.cue_count))
        else:
            self._log_line(tr("done_log").format(n=result.cue_count))
        if result.missing_en:
            self._log_line(tr("missing_en_log").format(n=len(result.missing_en)))

    def _log_line(self, text: str) -> None:
        if not self._task_started:
            return
        self.log.appendPlainText(redact_api_key(text, get_api_key()))

    def _on_fail(self, msg: str) -> None:
        if self._closing:
            return
        if not self._is_current_worker():
            return
        self._retry_translation = self._retry_translation or self._progress_stage == "translate"
        self._set_running_ui(False)
        stopped = msg in {tr("stop"), "job stopped"} or bool(self._control and self._control.is_stopped())
        safe = redact_api_key(msg, get_api_key())
        self._show_stage("stop" if stopped else "fail")
        self._set_stage_failed(not stopped)
        if stopped:
            if tr("stop") not in self.log.toPlainText().splitlines()[-5:]:
                self._log_line(tr("stop"))
        else:
            self._log_line(tr("error_prefix").format(msg=safe))
            show_error(self, safe)

    def _open_folder(self) -> None:
        if not self._last_output:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_output.parent)))


def _install_app_icon(app: QApplication) -> QIcon:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except (AttributeError, OSError):
            pass
    icon = load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    return icon


def main() -> None:
    from PySide6.QtGui import QGuiApplication

    from bilingual_sub.adapters.tts import qwen_runtime
    from bilingual_sub.adapters.tts.gptsovits_runtime import reset_boot_state, stop_servers

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    reset_boot_state()
    qwen_runtime.reset_boot_state()
    app.aboutToQuit.connect(stop_servers)
    app.aboutToQuit.connect(qwen_runtime.stop_servers)
    app.setApplicationName(PRODUCT_EN)
    app.setOrganizationName(COMPANY_ZH)
    set_locale(DEFAULT_LOCALE)
    icon = _install_app_icon(app)
    app.setFont(type_font(size=14))
    app.setStyleSheet(app_qss(load_ui_theme()))
    win = MainWindow()
    if not icon.isNull():
        win.setWindowIcon(icon)
    win.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
