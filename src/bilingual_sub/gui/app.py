"""语幕 SubFlow desktop client."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
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
from bilingual_sub.gui.widgets.deck import apply_deck_width, build_deck, fill_voice_combo
from bilingual_sub.gui.widgets.field import SCROLL_FLOOR, hairline
from bilingual_sub.gui.widgets.header import build_header
from bilingual_sub.gui.widgets.source_strip import build_source
from bilingual_sub.gui.widgets.stage import build_stage
from bilingual_sub.gui.workers import (
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
    from bilingual_sub.gui.widgets.field import FitScroll
    from bilingual_sub.gui.widgets.filament_btn import FilamentButton


class PreviewRequest(NamedTuple):
    provider: str
    voice: str
    lang: str
    endpoint: str
    ref_audio: str = ""
    prompt_text: str = ""
    prompt_lang: str = ""


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
    more_btn: QToolButton
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
    _slot_burn: QWidget
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
    form_scroll: FitScroll
    more_box: QFrame
    deck_grid: QGridLayout
    _deck_slots: list[QWidget]
    _deck_wide: bool

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1280, 860)
        self.setMinimumSize(1200, 760)
        self._worker: PipelineWorker | None = None
        self._models_worker: ModelsWorker | None = None
        self._preview_worker: VoicePreviewWorker | None = None
        self._sovits_worker: SovitsBootWorker | None = None
        self._sovits_probe_worker: SovitsProbeWorker | None = None
        self._closing = False
        self._preview_player = PreviewPlayer(self)
        self._preview_player.finished.connect(self._on_preview_played)
        self._preview_player.failed.connect(self._on_preview_fail)
        self._dl_worker: DownloadWorker | None = None
        self._last_output: Path | None = None
        self._last_result: JobResult | None = None
        self._last_signature: tuple | None = None
        self._running_signature: tuple | None = None
        self._last_log_stage: str | None = None
        self._bar_floor = 0
        self._video: Path | None = None
        self._control: JobControl | None = None
        self._section_labels: dict[str, QLabel] = {}
        set_locale(DEFAULT_LOCALE)
        self._theme = load_ui_theme()

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(8)
        outer.addLayout(build_header(self))
        outer.addWidget(hairline("headerRule"))
        outer.addWidget(build_source(self))
        outer.addWidget(build_deck(self))
        outer.addWidget(build_action_bar(self))
        outer.addWidget(hairline("stageRule", 2))
        outer.addWidget(build_stage(self), 1)

        icon = load_app_icon(self)
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.source_lang_combo.currentIndexChanged.connect(self._sync_dub_default)
        self.target_lang_combo.currentIndexChanged.connect(self._sync_dub_default)
        self.mode_combo.currentIndexChanged.connect(self._sync_output_name)
        self._apply_theme(persist=False)
        self._hydrate()
        self.retranslateUi()

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        apply_deck_width(self, self.width() >= 1200)
        self._relayout_deck()

    def _chrome_except_deck(self, layout, deck: QWidget, *, stage_floor: int) -> int:
        margins = layout.contentsMargins()
        used = margins.top() + margins.bottom()
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is deck:
                used += layout.spacing()
                continue
            used += self._chrome_item_height(item, widget, stage_floor=stage_floor) + layout.spacing()
        return used

    def _chrome_item_height(self, item, widget: QWidget | None, *, stage_floor: int) -> int:
        if widget is None:
            return max(item.sizeHint().height(), 0)
        if widget.objectName() == "stage":
            return stage_floor
        if 0 < widget.maximumHeight() <= 4:
            return max(widget.minimumHeight(), widget.height(), 1)
        hint = widget.sizeHint().height()
        if hint < 0:
            return max(widget.height(), widget.minimumHeight(), 0)
        return max(hint, 0)

    def _relayout_deck(self) -> None:
        scroll = getattr(self, "form_scroll", None)
        if scroll is not None:
            scroll.set_floor(SCROLL_FLOOR)
            scroll.updateGeometry()
        deck = self.findChild(QWidget, "deck")
        stage = self.findChild(QWidget, "stage")
        root = self.centralWidget()
        layout = root.layout() if root is not None else None
        if deck is None or root is None or layout is None:
            return
        if stage is not None:
            stage.setMinimumHeight(96)
        chrome = self._chrome_except_deck(layout, deck, stage_floor=96)
        room = max(SCROLL_FLOOR, root.height() - chrome)
        deck.setMinimumHeight(SCROLL_FLOOR)
        deck.setMaximumHeight(room)
        deck.updateGeometry()
        layout.invalidate()
        layout.activate()
        bar = getattr(self, "run_btn", None)
        if bar is None:
            return
        gap = bar.mapTo(root, bar.rect().topLeft()).y() - deck.mapTo(root, deck.rect().bottomLeft()).y()
        if gap < 4:
            deck.setMaximumHeight(max(SCROLL_FLOOR, deck.height() + gap - 4))
            layout.activate()

    def _set_key_status(self, text: str) -> None:
        self.key_status.setText(text)
        self.key_status.setVisible(bool(text))

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

    def _toggle_more(self, checked: bool) -> None:
        self.more_box.setVisible(checked)
        self.more_btn.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self._relayout_deck()

    def _refresh_drop(self) -> None:
        tones = tokens_for(self._theme)
        if self._video:
            self.drop.set_prompt(self._video.name, title_color=tones.ink, hint_color=tones.muted)
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
        busy = bool(self._dl_worker and self._dl_worker.isRunning())
        self.download_btn.setEnabled(bool(self.url_edit.text().strip()) and not busy)

    def _download(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, PRODUCT_ZH, tr("need_url"))
            return
        if self._dl_worker and self._dl_worker.isRunning():
            return
        dest = download_folder(url)
        self.download_btn.setEnabled(False)
        self.stage_label.setText(tr("ingest"))
        self.progress.setValue(0)
        self.pct_label.setText(format_pct(0))
        self._bar_floor = 0
        self._set_stage_failed(False)
        self._last_log_stage = None
        source_lang = str(self.source_lang_combo.currentData() or "zh")
        self._dl_worker = DownloadWorker(url, dest, source_lang=source_lang)
        self._dl_worker.progress.connect(self._on_progress)
        self._dl_worker.ok.connect(self._on_downloaded)
        self._dl_worker.fail.connect(self._on_download_fail)
        self._dl_worker.start()

    def _on_downloaded(self, path: str) -> None:
        self._sync_download()
        self._set_video(Path(path))
        self.progress.setValue(100)
        self.pct_label.setText(format_pct(100))
        self.stage_label.setText(tr("ingest"))
        self._log_line(f"{tr('ingest')}  {path}")

    def _on_download_fail(self, msg: str) -> None:
        self._sync_download()
        self.progress.setValue(0)
        self.pct_label.setText(format_pct(0))
        self._bar_floor = 0
        self.stage_label.setText(tr("waiting"))
        QMessageBox.warning(self, PRODUCT_ZH, msg)

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
        if (not translation_needed(source_lang, target_lang, mode)) and getattr(result, "translated", False):
            return None
        return mp4, srt, ass, dub

    def _patch_report_outputs(self) -> None:
        result = self._last_result
        if result is None or not result.report_path.is_file():
            return
        try:
            data = json.loads(result.report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        data["output_mp4"] = str(result.output_mp4) if result.output_mp4 else None
        data["output_srt"] = str(result.output_srt)
        data["output_ass"] = str(result.output_ass)
        data["output_dub"] = str(result.output_dub) if result.output_dub else None
        try:
            result.report_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            return

    def _try_relocate_outputs(self, dest_mp4: Path, *, log: bool = False) -> bool:
        sources = self._reuse_sources()
        if sources is None or self._last_result is None:
            return False
        src_mp4, src_srt, src_ass, src_dub = sources
        same_mp4 = src_mp4 is not None and src_mp4.resolve() == dest_mp4.resolve()
        same_srt = src_srt is not None and src_srt.resolve() == sidecar_srt(dest_mp4).resolve()
        if same_mp4 and same_srt:
            return True
        try:
            copied = copy_finished_outputs(
                dest_mp4,
                src_mp4=src_mp4,
                src_srt=src_srt,
                src_ass=src_ass,
                src_dub=src_dub,
                protected_inputs=(self._video,) if self._video is not None else (),
            )
        except (OSError, ValueError) as exc:
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
        self._patch_report_outputs()
        self.out_edit.setText(str(dest_mp4))
        if log and self._last_result is not None:
            self._log_line(tr("reused_log").format(n=self._last_result.cue_count))
            self.stage_label.setText(tr("done_stage").format(n=self._last_result.cue_count))
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
        self.locale_combo.setAccessibleName(tr("ui_lang"))
        self.theme_combo.setItemText(0, tr("theme_light"))
        self.theme_combo.setItemText(1, tr("theme_dark"))
        self.more_btn.setText(tr("more"))
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
        self.lbl_preview.setText(tr("tts_preview"))
        fill_voice_combo(self.tts_voice_edit)
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
        if self._worker is None or not self._worker.isRunning():
            self.stage_label.setText(tr("waiting"))
        self.log.setPlaceholderText(tr("log_ph"))
        self.drop.setAccessibleName(tr("drop"))

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
        self._sync_tts_fields()

    def _sync_tts_fields(self) -> None:
        on = self.dub_check.isChecked() or self._target_requires_dub()
        self.tts_combo.setEnabled(on)
        if self.tts_combo.findData("gptsovits") >= 0:
            self.tts_combo.setCurrentIndex(self.tts_combo.findData("gptsovits"))
        self.tts_voice_edit.setEnabled(False)
        self.tts_endpoint_edit.setEnabled(on)
        self._slot_voice.setVisible(False)
        self._slot_endpoint.setVisible(on)
        self._slot_preview.setVisible(on)
        self.sovits_box.setVisible(on)
        self.tts_preview_btn.setEnabled(on and not self._preview_busy())
        if self.more_box.isVisible():
            self._toggle_more(True)

    def _preview_request(self) -> PreviewRequest:
        lang = str(self.target_lang_combo.currentData() or "zh")
        source = str(self.source_lang_combo.currentData() or "")
        prompt_lang = "" if source in {"", "auto"} else source
        return PreviewRequest(
            "gptsovits",
            "",
            lang,
            self.tts_endpoint_edit.text().strip(),
            self.tts_ref_edit.text().strip(),
            self.tts_prompt_edit.text().strip(),
            prompt_lang,
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
        return self.tts_endpoint_edit.text().strip() or DEFAULT_ENDPOINT

    def _probe_sovits(self) -> None:
        if self._closing or (self._sovits_probe_worker and self._sovits_probe_worker.isRunning()):
            return
        self._sovits_probe_worker = SovitsProbeWorker(self._sovits_endpoint())
        self._sovits_probe_worker.result.connect(self._on_sovits_probe)
        self._sovits_probe_worker.start()

    def _on_sovits_probe(self, ready: bool, detail: str) -> None:
        if ready:
            self.tts_sovits_status.setText(tr("tts_sovits_ready"))
            self._log_line(tr("tts_sovits_ready"))
            return
        self.tts_sovits_status.setText(detail or tr("tts_sovits_down"))

    def _start_sovits(self, *args, announce: bool = True) -> None:
        if self._closing:
            return
        if self._sovits_worker is not None and self._sovits_worker.isRunning():
            return
        self._sovits_announce = announce
        self.tts_sovits_status.setText(tr("tts_sovits_starting"))
        self._sovits_worker = SovitsBootWorker(self._sovits_endpoint())
        self._sovits_worker.progress.connect(self.tts_sovits_status.setText)
        self._sovits_worker.progress.connect(self._log_line)
        self._sovits_worker.ok.connect(self._on_sovits_boot)
        self._sovits_worker.fail.connect(self._on_sovits_boot_fail)
        self._sovits_worker.start()

    def _on_sovits_boot(self, kind: str) -> None:
        if kind == "ready":
            self.tts_sovits_status.setText(tr("tts_sovits_ready"))
        else:
            self.tts_sovits_status.setText(tr("tts_sovits_started"))
        if getattr(self, "_sovits_announce", True):
            self._log_line(self.tts_sovits_status.text())

    def _on_sovits_boot_fail(self, msg: str) -> None:
        self.tts_sovits_status.setText(msg)
        self._set_key_status(tr("tts_preview_fail").format(msg=msg))
        if getattr(self, "_sovits_announce", True):
            self._log_line(tr("tts_preview_fail").format(msg=msg))

    def _preview_busy(self) -> bool:
        return bool(self._preview_worker is not None and self._preview_worker.isRunning())

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
        if (ref and not Path(ref).expanduser().is_file()) or (not ref and video is None):
            self._set_key_status(tr("tts_sovits_need_ref"))
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
            **({"video": video} if not ref else {}),
        )
        self._preview_worker.ok.connect(self._on_preview_ready)
        self._preview_worker.fail.connect(self._on_preview_fail)
        self._preview_worker.start()

    def _on_preview_ready(self, path: str) -> None:
        if self._closing:
            return
        worker = self.sender()
        if worker is not None and worker is not self._preview_worker:
            return
        req = self._preview_request()
        provider, voice, lang = req.provider, req.voice, req.lang
        if isinstance(worker, VoicePreviewWorker) and (worker.provider, worker.voice, worker.lang) != (
            provider,
            voice,
            lang,
        ):
            self._set_preview_busy(False)
            return
        audio = Path(path)
        if not audio.is_file():
            self._on_preview_fail(tr("tts_preview_fail").format(msg=path))
            return
        label = voice or "GPT-SoVITS"
        self._log_line(tr("tts_preview_ok").format(voice=label))
        self._preview_player.play(audio)

    def _on_preview_played(self) -> None:
        self._set_preview_busy(False)

    def _on_preview_fail(self, msg: str) -> None:
        self._set_preview_busy(False)
        safe = redact_api_key(msg, get_api_key())
        if safe in {tr("need_token"), "请先保存 API 令牌"}:
            self._set_key_status(tr("need_token"))
            return
        self._set_key_status(tr("tts_preview_fail").format(msg=safe))
        self._log_line(tr("tts_preview_fail").format(msg=safe))

    def closeEvent(self, event) -> None:  # noqa: N802
        from bilingual_sub.adapters.tts.gptsovits_runtime import request_shutdown, stop_servers

        workers = (self._worker, self._models_worker, self._preview_worker,
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
        if any(worker is not None and worker.isRunning() for worker in workers):
            # Keep QThreads alive until cooperative cancellation has completed.
            event.ignore()
            self.setEnabled(False)
            QTimer.singleShot(100, self.close)
            return
        stop_servers()
        super().closeEvent(event)

    def _job_busy(self) -> bool:
        return bool(self._worker is not None and self._worker.isRunning())

    def _set_running_ui(self, running: bool, paused: bool = False, stopping: bool = False) -> None:
        busy = bool(running or stopping)
        self.run_btn.setEnabled(not busy)
        self.pause_btn.setEnabled(bool(running) and not paused and not stopping)
        self.resume_btn.setEnabled(bool(running) and paused and not stopping)
        self.stop_btn.setEnabled(bool(running) and not stopping)
        self.run_btn.update()

    def _release_job(self) -> None:
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
        if self._control is None or self._control.is_stopped():
            return
        self._control.resume()
        self._set_running_ui(True, paused=False)
        self._log_line(tr("resume"))

    def _stop(self) -> None:
        if self._control is not None:
            self._control.stop()
        self.stage_label.setText(tr("stop"))
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
            tts_provider="gptsovits",
        )
        if need_xl8 and not get_api_key() and not self.key_edit.text().strip():
            QMessageBox.warning(self, PRODUCT_ZH, tr("need_token"))
            return
        if self.key_edit.text().strip():
            set_api_key(self.key_edit.text().strip())

        model = self.model_combo.currentText().strip()
        if need_xl8 and not model:
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
        tts = "gptsovits" if must_dub or self.dub_check.isChecked() else "none"
        if tts == "gptsovits":
            self._persist_sovits()
            if not self._sovits_worker or not self._sovits_worker.isRunning():
                from bilingual_sub.adapters.tts.gptsovits_runtime import probe_endpoint

                if not probe_endpoint(self._sovits_endpoint()):
                    self._start_sovits()
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
            tts_voice="",
            tts_endpoint="" if tts != "gptsovits" else self._sovits_endpoint(),
            tts_ref_audio="" if tts != "gptsovits" else self.tts_ref_edit.text().strip(),
            tts_prompt_text="" if tts != "gptsovits" else self.tts_prompt_edit.text().strip(),
            tts_prompt_lang=(
                ""
                if tts != "gptsovits" or source_lang in {"", "auto"}
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
        self.stage_label.setText(tr("starting"))
        self._set_stage_failed(False)
        self._control = JobControl()
        self._set_running_ui(True, paused=False)
        self._worker = PipelineWorker(cfg, self._control)
        self._running_signature = self._job_signature()
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_progress(self, stage: str, pct: float) -> None:
        label = stage_text(stage)
        shown = max(self._bar_floor, max(0, min(100, int(pct * 100))))
        self._bar_floor = shown
        self.progress.setValue(shown)
        self.pct_label.setText(format_pct(shown))
        self.stage_label.setText(label)
        self._set_stage_failed(False)
        if should_log_stage(stage, self._last_log_stage):
            self._log_line(label)
            self._last_log_stage = stage

    def _on_done(self, result: object) -> None:
        if not self._is_current_worker():
            return
        assert isinstance(result, JobResult)
        self._set_running_ui(False)
        self.progress.setValue(100)
        self.pct_label.setText(format_pct(100))
        self.stage_label.setText(tr("done_stage").format(n=result.cue_count))
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
        self.log.appendPlainText(redact_api_key(text, get_api_key()))

    def _on_fail(self, msg: str) -> None:
        if self._closing:
            return
        if not self._is_current_worker():
            return
        self._set_running_ui(False)
        stopped = msg in {tr("stop"), "job stopped"} or bool(self._control and self._control.is_stopped())
        safe = redact_api_key(msg, get_api_key())
        self.stage_label.setText(tr("stop") if stopped else tr("fail"))
        self._set_stage_failed(not stopped)
        if stopped:
            if tr("stop") not in self.log.toPlainText().splitlines()[-5:]:
                self._log_line(tr("stop"))
        else:
            self._log_line(tr("error_prefix").format(msg=safe))
            QMessageBox.critical(self, PRODUCT_ZH, safe)

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

    from bilingual_sub.adapters.tts.gptsovits_runtime import reset_boot_state, stop_servers

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    reset_boot_state()
    app.aboutToQuit.connect(stop_servers)
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
